"""First-start setup: the superadmin account, the default policy and seed models."""

import logging
import secrets

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import get_settings
from .core.policy_config import load_policy
from .models import ROLE_SUPERADMIN, ModelEntry, User
from .security import hash_password

log = logging.getLogger(__name__)


def ensure_superadmin(db: Session) -> None:
    settings = get_settings()
    exists = db.execute(select(func.count()).select_from(User).where(User.role == ROLE_SUPERADMIN)).scalar_one()
    if exists:
        return
    password = settings.bootstrap_admin_password
    if not password:
        password = secrets.token_urlsafe(12)
        # Development convenience only; production startup refuses an empty password.
        log.warning("Created superadmin %s with generated password: %s", settings.bootstrap_admin_email, password)
    db.add(
        User(
            email=settings.bootstrap_admin_email.lower(),
            name="Super Admin",
            password_hash=hash_password(password),
            role=ROLE_SUPERADMIN,
        )
    )
    db.commit()


def seed_models(db: Session) -> None:
    """Seeds the registry once. Prices are per million tokens and must be re-checked
    against each provider's pricing page before experiments are frozen."""
    if db.execute(select(func.count()).select_from(ModelEntry)).scalar_one():
        return
    settings = get_settings()
    mock = settings.mock_models_enabled
    # With mock models present (laptop development) the real models start disabled,
    # so nothing tries to reach an Ollama server or a cloud API that is not there.
    real_enabled = not mock
    entries = [
        ModelEntry(
            name="local-default",
            display_name=f"Local ({settings.local_model})",
            vendor="ollama",
            model_id=settings.local_model,
            tier="local",
            is_local=True,
            context_window=8192,
            max_output_tokens=2048,
            # Ollama's default context is smaller than most models support and it
            # truncates longer prompts without an error. num_ctx must equal
            # context_window, otherwise the context filter trusts a size that is not real.
            params={"options": {"num_ctx": 8192}},
            enabled=real_enabled,
        ),
        ModelEntry(
            name="claude-haiku",
            display_name="Claude Haiku 5.5 (cheap cloud)",
            vendor="anthropic",
            model_id="claude-haiku-5-5",
            tier="cheap",
            context_window=100_000,  # stays inside the base price band
            max_output_tokens=8192,
            price_in_per_mtok=0.10,
            price_out_per_mtok=0.50,
            params={"reasoning_overhead_tokens": 2000, "request": {"output_config": {"effort": "low"}}},
            enabled=real_enabled,
        ),
        ModelEntry(
            name="claude-opus",
            display_name="Claude Opus 5.5 (strong cloud)",
            vendor="anthropic",
            model_id="claude-opus-5-5",
            tier="strong",
            context_window=1_000_000,
            max_output_tokens=8192,
            price_in_per_mtok=4.00,
            price_out_per_mtok=20.00,
            params={"reasoning_overhead_tokens": 4000},
            enabled=real_enabled,
        ),
    ]
    if mock:
        entries += [
            ModelEntry(
                name="mock-local", display_name="Mock local model", vendor="mock", model_id="mock-local",
                tier="local", is_local=True, context_window=8192, latency_ewma_ms=5000,
            ),
            ModelEntry(
                name="mock-cheap", display_name="Mock cheap cloud model", vendor="mock", model_id="mock-cheap",
                tier="cheap", context_window=128_000, price_in_per_mtok=0.10, price_out_per_mtok=0.50,
                latency_ewma_ms=2000,
            ),
            ModelEntry(
                name="mock-strong", display_name="Mock strong cloud model", vendor="mock", model_id="mock-strong",
                tier="strong", context_window=128_000, price_in_per_mtok=4.00, price_out_per_mtok=20.00,
                latency_ewma_ms=6000,
            ),
        ]
    db.add_all(entries)
    db.commit()


def bootstrap(db: Session) -> None:
    load_policy(db)  # creates the default policy row
    ensure_superadmin(db)
    seed_models(db)
