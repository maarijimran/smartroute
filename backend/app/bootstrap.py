"""First-start setup: the superadmin account, the default policy and the tier slots."""

import logging
import secrets

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import get_settings
from .core.policy_config import load_policy
from .core.tiers import ensure_slots
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
    """Creates the three tier slots and, on a development machine, the mock models.

    No cloud model is seeded: the superadmin chooses the provider, model and key for
    the cheap and strong tiers in Settings -> Models (see core/tiers.py)."""
    first_start = not db.execute(select(func.count()).select_from(ModelEntry)).scalar_one()
    ensure_slots(db)
    if not (first_start and get_settings().mock_models_enabled):
        return
    db.add_all([
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
    ])
    db.commit()


def bootstrap(db: Session) -> None:
    load_policy(db)  # creates the default policy row
    ensure_superadmin(db)
    seed_models(db)
