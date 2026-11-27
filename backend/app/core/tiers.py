"""The three model tiers (local, cheap, strong) and the model behind each one.

The organisation has exactly one model per tier, chosen by the superadmin together
with the provider key that unlocks it. Users only use the tiers; they cannot add keys
or models.

Each tier is a fixed registry entry, its "slot". Changing a tier's provider or model
edits that entry in place and keeps its name. The learners (frozen ridge, epsilon-greedy,
LinUCB) store their weights under the entry's name, so a new cheap model starts from the
trained cheap weights instead of from scratch, and the same holds for strong and local.
Retrain later on outcomes from the new model if its behaviour differs a lot.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import ModelEntry, PolicyChange, ProviderCredential, User, utcnow
from ..security import encrypt_secret
from .cache import response_cache
from .providers import VENDORS

TIERS = ("local", "cheap", "strong")
# Names given to slots created on a fresh install. Existing installations keep the
# names they already have (e.g. sim-cheap), because the trained weights are stored
# under those names.
DEFAULT_SLOT_NAMES = {"local": "local-default", "cheap": "cheap", "strong": "strong"}
DEFAULT_LATENCY_MS = 3000.0
# Models the first versions seeded before any provider was chosen; removed if unused.
LEGACY_SEEDS = {("claude-haiku", "claude-haiku-5-5"), ("claude-opus", "claude-opus-5-5")}


class TierError(ValueError):
    """A tier change that is not allowed; the message is shown to the superadmin."""


def credential_label(tier: str) -> str:
    return f"tier:{tier}"


def _is_mock(m: ModelEntry) -> bool:
    return VENDORS.get(m.vendor) is not None and VENDORS[m.vendor].adapter == "mock" and m.name.startswith("mock-")


def slot(db: Session, tier: str) -> ModelEntry | None:
    """The registry entry that serves a tier. The development mock models are not slots."""
    rows = db.execute(
        select(ModelEntry).where(ModelEntry.tier == tier).order_by(ModelEntry.enabled.desc(), ModelEntry.created_at)
    ).scalars().all()
    rows = [m for m in rows if not _is_mock(m)]
    return rows[0] if rows else None


def tier_credential(db: Session, tier: str) -> ProviderCredential | None:
    return db.execute(
        select(ProviderCredential)
        .where(ProviderCredential.user_id.is_(None), ProviderCredential.label == credential_label(tier))
        .order_by(ProviderCredential.created_at.desc())
    ).scalars().first()


def is_configured(m: ModelEntry | None) -> bool:
    return m is not None and bool(m.vendor) and bool(m.model_id)


def ensure_slots(db: Session) -> None:
    """Creates a slot for every tier that has none, and removes the unused legacy seeds."""
    settings = get_settings()
    for name, model_id in LEGACY_SEEDS:
        row = db.execute(select(ModelEntry).where(ModelEntry.name == name)).scalars().first()
        if row is not None and row.model_id == model_id and not row.enabled:
            db.delete(row)
    db.flush()
    for tier in TIERS:
        if slot(db, tier) is not None:
            continue
        if tier == "local":
            db.add(ModelEntry(
                name=DEFAULT_SLOT_NAMES[tier],
                display_name=f"Local ({settings.local_model})",
                vendor="ollama",
                model_id=settings.local_model,
                tier="local",
                is_local=True,
                context_window=8192,
                max_output_tokens=2048,
                # Ollama truncates silently when num_ctx is below the real prompt size.
                params={"options": {"num_ctx": 8192}},
                # With mock models seeded (laptop) nothing should try to reach Ollama.
                enabled=not settings.mock_models_enabled,
            ))
        else:
            db.add(ModelEntry(
                name=DEFAULT_SLOT_NAMES[tier], display_name="Not set", vendor="", model_id="",
                tier=tier, is_local=False, enabled=False,
            ))
    db.commit()


def _is_local_vendor(vendor: str, tier: str) -> bool:
    adapter = VENDORS[vendor].adapter
    return adapter == "ollama" or (adapter == "mock" and tier == "local")


def set_tier(
    db: Session,
    tier: str,
    actor: User | None,
    *,
    vendor: str,
    model_id: str,
    display_name: str = "",
    base_url: str | None = None,
    api_version: str | None = None,
    api_key: str | None = None,
    context_window: int = 8192,
    max_output_tokens: int = 2048,
    price_in_per_mtok: float = 0.0,
    price_out_per_mtok: float = 0.0,
    params: dict | None = None,
) -> ModelEntry:
    """Points a tier at a provider and model, keeping the slot (and so the trained weights).

    Raises TierError for anything that is not allowed."""
    settings = get_settings()
    if tier not in TIERS:
        raise TierError(f"Unknown tier '{tier}'")
    preset = VENDORS.get(vendor)
    if preset is None:
        raise TierError(f"Unknown provider '{vendor}'")
    if preset.adapter == "mock" and settings.is_production:
        raise TierError("Mock models are not available in production")
    if tier == "local" and not _is_local_vendor(vendor, tier):
        # The local tier is where confidential requests go; it must run on this server.
        raise TierError("The local tier must be a model served by Ollama on this server")
    model_id = (model_id or "").strip()
    if not model_id:
        raise TierError("Model ID is required")
    base_url = (base_url or "").strip() or None
    if preset.needs_base_url and not base_url:
        raise TierError(f"{preset.label} needs an endpoint URL")
    if base_url and preset.adapter not in ("ollama", "mock") and settings.is_production and not base_url.startswith("https://"):
        raise TierError("Endpoint URLs must use https")
    api_key = (api_key or "").strip() or None
    cred = tier_credential(db, tier)
    if preset.needs_key and api_key is None and (cred is None or cred.vendor != vendor):
        raise TierError(f"An API key for {preset.label} is required")

    ensure_slots(db)
    entry = slot(db, tier)
    old = {
        "vendor": entry.vendor, "model_id": entry.model_id, "display_name": entry.display_name,
        "base_url": entry.base_url, "context_window": entry.context_window,
        "max_output_tokens": entry.max_output_tokens, "price_in_per_mtok": entry.price_in_per_mtok,
        "price_out_per_mtok": entry.price_out_per_mtok, "enabled": entry.enabled,
    }
    changed_model = (entry.vendor, entry.model_id) != (vendor, model_id)

    new_params = dict(params) if params is not None else ({} if changed_model else dict(entry.params or {}))
    if preset.adapter == "ollama":
        options = dict(new_params.get("options") or {})
        options["num_ctx"] = context_window  # must equal the context window (see SETUP.md)
        new_params["options"] = options

    entry.vendor = vendor
    entry.model_id = model_id
    entry.display_name = display_name.strip() or model_id
    entry.base_url = base_url
    entry.is_local = _is_local_vendor(vendor, tier)
    entry.context_window = context_window
    entry.max_output_tokens = max_output_tokens
    if (entry.price_in_per_mtok, entry.price_out_per_mtok) != (price_in_per_mtok, price_out_per_mtok) or changed_model:
        entry.price_updated_at = utcnow()
    entry.price_in_per_mtok = price_in_per_mtok
    entry.price_out_per_mtok = price_out_per_mtok
    entry.params = new_params
    entry.enabled = True
    if changed_model:
        # Health and latency belong to the old model.
        entry.latency_ewma_ms = DEFAULT_LATENCY_MS
        entry.unhealthy_until = None
        entry.last_error = None

    # One model per tier: any other entry in the tier stops being routable.
    for other in db.execute(select(ModelEntry).where(ModelEntry.tier == tier, ModelEntry.id != entry.id)).scalars():
        if not _is_mock(other):
            other.enabled = False

    key_change = None
    if preset.needs_key:
        if api_key is not None:
            if cred is not None:
                db.delete(cred)
            db.add(ProviderCredential(
                user_id=None, vendor=vendor, label=credential_label(tier), base_url=None,
                api_version=(api_version or "").strip() or None,
                encrypted_key=encrypt_secret(api_key), key_hint=api_key[-4:],
            ))
            key_change = [f"…{cred.key_hint}" if cred else None, f"…{api_key[-4:]}"]
        elif cred is not None and api_version is not None:
            cred.api_version = api_version.strip() or None
    elif cred is not None:
        db.delete(cred)  # a local model needs no key; do not keep an unused secret
        key_change = [f"…{cred.key_hint}", None]

    new = {
        "vendor": entry.vendor, "model_id": entry.model_id, "display_name": entry.display_name,
        "base_url": entry.base_url, "context_window": entry.context_window,
        "max_output_tokens": entry.max_output_tokens, "price_in_per_mtok": entry.price_in_per_mtok,
        "price_out_per_mtok": entry.price_out_per_mtok, "enabled": entry.enabled,
    }
    changes = {k: [old[k], new[k]] for k in new if old[k] != new[k]}
    if key_change:
        changes["api_key"] = key_change
    if changes and actor is not None:
        db.add(PolicyChange(actor_id=actor.id, actor_email=actor.email, target=f"tier:{tier}", changes=changes))
    db.commit()
    db.refresh(entry)
    if changed_model:
        response_cache.clear()  # cached answers came from the previous model
    return entry


def remap_arms_to_slots(db: Session, arms: dict, tiers: dict[str, str]) -> tuple[dict, dict[str, str]]:
    """Renames learner arms from the model names they were trained under to the names of
    the current slots, using each trained model's tier. Returns (arms, renames)."""
    renames: dict[str, str] = {}
    out = {}
    for name, state in arms.items():
        tier = tiers.get(name)
        target = slot(db, tier) if tier else None
        new_name = target.name if target is not None else name
        if new_name in out:
            raise TierError(f"Two trained models map to the {tier} tier: {name} and another")
        out[new_name] = state
        if new_name != name:
            renames[name] = new_name
    return out, renames
