"""Model tiers and their provider keys (superadmin), the model list, and SmartRoute API keys."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..core import tiers
from ..core.providers import VENDORS
from ..db import get_db
from ..deps import get_current_user, require_superadmin
from ..models import ROLE_USER, ApiKey, ModelEntry, ProviderCredential, User, utcnow
from ..schemas import (
    ApiKeyCreated,
    ApiKeyIn,
    ApiKeyOut,
    CredentialOut,
    ModelOut,
    ModelUpdate,
    TierIn,
    TierOut,
)
from ..security import new_api_key

router = APIRouter(prefix="/api", tags=["registry"])


@router.get("/vendors")
def vendors(_: User = Depends(get_current_user)):
    production = get_settings().is_production
    return [
        {
            "id": key,
            "label": v.label,
            "adapter": v.adapter,
            "needs_key": v.needs_key,
            "needs_base_url": v.needs_base_url,
            "default_base_url": v.base_url,
        }
        for key, v in VENDORS.items()
        if not (production and v.adapter == "mock")
    ]


# ---------------------------------------------------------------------- models


@router.get("/models", response_model=list[ModelOut])
def list_models(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = select(ModelEntry).order_by(ModelEntry.tier, ModelEntry.name)
    if user.role == ROLE_USER:
        q = q.where(ModelEntry.enabled.is_(True))
    return db.execute(q).scalars().all()


@router.patch("/models/{model_id}", response_model=ModelOut)
def update_model(model_id: str, body: ModelUpdate, _: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    model = db.get(ModelEntry, model_id)
    if model is None:
        raise HTTPException(404, "Model not found")
    data = body.model_dump(exclude_unset=True)
    if data.get("enabled"):
        if not tiers.is_configured(model):
            raise HTTPException(422, "Choose a provider and model for this tier first")
        if not model.name.startswith("mock-"):
            others = db.execute(
                select(ModelEntry).where(ModelEntry.tier == model.tier, ModelEntry.id != model.id, ModelEntry.enabled.is_(True))
            ).scalars().all()
            if any(not m.name.startswith("mock-") for m in others):
                raise HTTPException(409, "A tier has one model. Change the tier's model instead of enabling another.")
    if "price_in_per_mtok" in data or "price_out_per_mtok" in data:
        model.price_updated_at = utcnow()  # prices are dated so experiments can cite them
    for key, value in data.items():
        setattr(model, key, value)
    if "context_window" in data and VENDORS.get(model.vendor) and VENDORS[model.vendor].adapter == "ollama":
        params = dict(model.params or {})
        params["options"] = {**(params.get("options") or {}), "num_ctx": model.context_window}
        model.params = params  # Ollama's num_ctx must follow the context window
    db.commit()
    return model


@router.post("/models/{model_id}/reset-health", response_model=ModelOut)
def reset_health(model_id: str, _: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    model = db.get(ModelEntry, model_id)
    if model is None:
        raise HTTPException(404, "Model not found")
    model.unhealthy_until, model.last_error = None, None
    db.commit()
    return model


# ----------------------------------------------------------------------- tiers


def _tier_out(db: Session, tier: str) -> TierOut:
    entry = tiers.slot(db, tier)
    cred = tiers.tier_credential(db, tier)
    return TierOut(
        tier=tier,
        configured=tiers.is_configured(entry),
        model=ModelOut.model_validate(entry) if entry is not None else None,
        key_vendor=cred.vendor if cred else None,
        key_hint=cred.key_hint if cred else None,
        api_version=cred.api_version if cred else None,
    )


@router.get("/tiers", response_model=list[TierOut])
def list_tiers(_: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    tiers.ensure_slots(db)
    return [_tier_out(db, t) for t in tiers.TIERS]


@router.put("/tiers/{tier}", response_model=TierOut)
def put_tier(tier: str, body: TierIn, actor: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    """Sets the provider, model and key of a tier. The tier keeps its trained router weights."""
    try:
        tiers.set_tier(db, tier, actor, **body.model_dump())
    except tiers.TierError as exc:
        raise HTTPException(422, str(exc)) from exc
    return _tier_out(db, tier)


# ----------------------------------------------------------------- credentials


@router.get("/credentials", response_model=list[CredentialOut])
def list_credentials(_: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    """The organisation's provider keys (key values are never returned). Keys are set per
    tier with PUT /api/tiers/{tier}; users cannot add their own."""
    q = select(ProviderCredential).where(ProviderCredential.user_id.is_(None))
    return db.execute(q.order_by(ProviderCredential.created_at.desc())).scalars().all()


@router.delete("/credentials/{cred_id}", status_code=204)
def delete_credential(cred_id: str, _: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    cred = db.get(ProviderCredential, cred_id)
    if cred is None or cred.user_id is not None:
        raise HTTPException(404, "Credential not found")
    db.delete(cred)
    db.commit()


# -------------------------------------------------------------------- API keys


@router.get("/keys", response_model=list[ApiKeyOut])
def list_keys(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.execute(
        select(ApiKey).where(ApiKey.user_id == user.id).order_by(ApiKey.created_at.desc())
    ).scalars().all()


@router.post("/keys", response_model=ApiKeyCreated, status_code=201)
def create_key(body: ApiKeyIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    plain, prefix, key_hash = new_api_key()
    key = ApiKey(
        user_id=user.id,
        name=body.name,
        prefix=prefix,
        key_hash=key_hash,
        default_privacy_mode=body.default_privacy_mode,
    )
    db.add(key)
    db.commit()
    return ApiKeyCreated(**ApiKeyOut.model_validate(key).model_dump(), key=plain)


@router.delete("/keys/{key_id}", status_code=204)
def revoke_key(key_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    key = db.get(ApiKey, key_id)
    if key is None or key.user_id != user.id:
        raise HTTPException(404, "API key not found")
    key.revoked = True
    db.commit()
