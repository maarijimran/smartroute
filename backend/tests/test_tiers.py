"""Tier slots: one model per tier, set by the superadmin, keeping the trained weights."""

import numpy as np
import pytest
from sqlalchemy import select

from app.core import pipeline, tiers
from app.core.routing import state as learner_state
from app.core.routing.arms import ArmSet
from app.models import ModelEntry, PolicyChange, ProviderCredential, User


def superadmin(db) -> User:
    return db.execute(select(User).where(User.role == "superadmin")).scalars().first()


def test_no_cloud_model_is_seeded(db):
    names = {m.name for m in db.execute(select(ModelEntry)).scalars()}
    assert not {"claude-haiku", "claude-opus"} & names
    for tier in ("cheap", "strong"):
        entry = tiers.slot(db, tier)
        assert entry is not None and not entry.enabled and not tiers.is_configured(entry)
    assert tiers.slot(db, "local").vendor == "ollama"


def test_unused_legacy_seeds_are_removed(db):
    db.add(ModelEntry(name="claude-haiku", vendor="anthropic", model_id="claude-haiku-5-5", tier="cheap", enabled=False))
    db.commit()
    tiers.ensure_slots(db)
    assert db.execute(select(ModelEntry).where(ModelEntry.name == "claude-haiku")).scalars().first() is None


def test_changing_a_tier_keeps_its_name_and_trained_weights(db):
    actor = superadmin(db)
    first = tiers.set_tier(db, "cheap", actor, vendor="openai", model_id="model-a", api_key="sk-aaaa-1111",
                           price_in_per_mtok=0.1, price_out_per_mtok=0.5)
    name = first.name

    # Weights trained for the cheap tier, stored under the slot's name.
    arms = ArmSet(d=3, lam=1.0)
    for _ in range(20):
        arms.arm(name).update(np.array([1.0, 0.5, 1.0]), 0.8, 1.0)
    learner_state.save_arms(db, "frozen", arms, note="trained")
    db.commit()
    before = arms.arm(name).predict(np.array([1.0, 0.5, 1.0]))

    first.unhealthy_until, first.last_error, first.latency_ewma_ms = None, "old error", 9999.0
    db.commit()
    second = tiers.set_tier(db, "cheap", actor, vendor="anthropic", model_id="model-b", api_key="sk-bbbb-2222",
                            price_in_per_mtok=0.2, price_out_per_mtok=1.0)

    assert second.id == first.id and second.name == name  # same slot, so the same arm
    assert (second.vendor, second.model_id, second.enabled) == ("anthropic", "model-b", True)
    assert second.last_error is None and second.latency_ewma_ms == tiers.DEFAULT_LATENCY_MS
    loaded, _ = learner_state.load_arms(db, "frozen", 3, 1.0)
    assert loaded.arm(name).predict(np.array([1.0, 0.5, 1.0])) == pytest.approx(before)

    cred = tiers.tier_credential(db, "cheap")
    assert cred.vendor == "anthropic" and cred.key_hint == "2222"
    assert len(db.execute(select(ProviderCredential)).scalars().all()) == 1  # the old key is gone
    change = db.execute(select(PolicyChange).where(PolicyChange.target == "tier:cheap")).scalars().all()[-1]
    assert change.changes["model_id"] == ["model-a", "model-b"]
    assert "sk-" not in str(change.changes)  # only key hints are logged


def test_tier_key_is_used_for_dispatch(db):
    entry = tiers.set_tier(db, "strong", superadmin(db), vendor="openai", model_id="big", api_key="sk-strong-9999")
    resolved = pipeline.resolve_credential(db, entry)
    assert resolved.api_key == "sk-strong-9999" and resolved.scope == "platform"
    # Personal keys are no longer honoured: only the organisation's tier keys are.
    db.add(ProviderCredential(user_id="someone", vendor="openai", label="mine", encrypted_key="x", key_hint="x"))
    db.commit()
    assert pipeline.resolve_credential(db, entry).api_key == "sk-strong-9999"


def test_local_tier_must_run_here_and_keys_are_required(db):
    actor = superadmin(db)
    with pytest.raises(tiers.TierError):
        tiers.set_tier(db, "local", actor, vendor="openai", model_id="x", api_key="sk-1234")
    with pytest.raises(tiers.TierError):
        tiers.set_tier(db, "cheap", actor, vendor="openai", model_id="x")  # no key
    ollama = tiers.set_tier(db, "cheap", actor, vendor="ollama", model_id="qwen", context_window=16384)
    assert ollama.is_local and ollama.params["options"]["num_ctx"] == 16384


def test_one_model_per_tier(db, client, root):
    actor = superadmin(db)
    # An older installation may have two enabled entries in a tier.
    db.add_all([
        ModelEntry(name="old-a", vendor="openai", model_id="a", tier="cheap", enabled=True),
        ModelEntry(name="old-b", vendor="openai", model_id="b", tier="cheap", enabled=True),
    ])
    db.commit()
    entry = tiers.set_tier(db, "cheap", actor, vendor="openai", model_id="m", api_key="sk-1234")
    enabled = [m for m in db.execute(select(ModelEntry).where(ModelEntry.tier == "cheap")).scalars()
               if m.enabled and not m.name.startswith("mock-")]
    assert enabled == [entry]
    other = next(m for m in db.execute(select(ModelEntry).where(ModelEntry.tier == "cheap")).scalars()
                 if m.name in ("old-a", "old-b") and m.id != entry.id)
    assert client.patch(f"/api/models/{other.id}", json={"enabled": True}, headers=root).status_code == 409
    placeholder = tiers.slot(db, "strong")  # not configured yet
    assert client.patch(f"/api/models/{placeholder.id}", json={"enabled": True}, headers=root).status_code == 422


def test_imported_weights_attach_to_the_current_slots(db):
    # Trained under the server's names; this machine's cheap slot is called differently.
    arms = {"sim-cheap": {"A": [[1.0]], "b": [0.5], "n": 3}, "local-default": {"A": [[1.0]], "b": [0.1], "n": 3}}
    out, renames = tiers.remap_arms_to_slots(db, arms, {"sim-cheap": "cheap", "local-default": "local"})
    cheap = tiers.slot(db, "cheap").name
    assert renames == ({"sim-cheap": cheap} if cheap != "sim-cheap" else {})
    assert out[cheap]["b"] == [0.5] and out["local-default"]["b"] == [0.1]
