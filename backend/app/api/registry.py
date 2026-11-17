"""Model registry, cloud provider credentials and SmartRoute API keys."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.providers import VENDORS
from ..db import get_db
from ..deps import get_current_user, require_superadmin
from ..models import ROLE_SUPERADMIN, ROLE_USER, ApiKey, ModelEntry, ProviderCredential, User, utcnow
from ..schemas import (
    ApiKeyCreated,
    ApiKeyIn,
    ApiKeyOut,
    CredentialIn,
    CredentialOut,
    ModelIn,
    ModelOut,
    ModelUpdate,
)
from ..security import encrypt_secret, new_api_key

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


def _check_vendor(vendor: str, is_local: bool) -> None:
    preset = VENDORS.get(vendor)
    if preset is None:
        raise HTTPException(422, f"Unknown vendor '{vendor}'")
    if preset.adapter == "mock" and get_settings().is_production:
        raise HTTPException(422, "Mock models are not available in production")
    if preset.adapter == "ollama" and not is_local:
        raise HTTPException(422, "Ollama models run on this host and must be marked local")
    if preset.adapter not in ("ollama", "mock") and is_local:
        # A cloud vendor marked local would bypass the privacy gate.
        raise HTTPException(422, "Only Ollama models can be marked local")


@router.get("/models", response_model=list[ModelOut])
def list_models(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = select(ModelEntry).order_by(ModelEntry.tier, ModelEntry.name)
    if user.role == ROLE_USER:
        q = q.where(ModelEntry.enabled.is_(True))
    return db.execute(q).scalars().all()


@router.post("/models", response_model=ModelOut, status_code=201)
def create_model(body: ModelIn, _: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    _check_vendor(body.vendor, body.is_local)
    if db.execute(select(ModelEntry).where(ModelEntry.name == body.name)).scalars().first():
        raise HTTPException(409, "A model with this name already exists")
    model = ModelEntry(**body.model_dump())
    db.add(model)
    db.commit()
    return model


@router.patch("/models/{model_id}", response_model=ModelOut)
def update_model(model_id: str, body: ModelUpdate, _: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    model = db.get(ModelEntry, model_id)
    if model is None:
        raise HTTPException(404, "Model not found")
    data = body.model_dump(exclude_unset=True)
    if "price_in_per_mtok" in data or "price_out_per_mtok" in data:
        model.price_updated_at = utcnow()  # prices are dated so experiments can cite them
    for key, value in data.items():
        setattr(model, key, value)
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


@router.delete("/models/{model_id}", status_code=204)
def delete_model(model_id: str, _: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    model = db.get(ModelEntry, model_id)
    if model is None:
        raise HTTPException(404, "Model not found")
    db.delete(model)
    db.commit()


# ----------------------------------------------------------------- credentials


@router.get("/credentials", response_model=list[CredentialOut])
def list_credentials(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Own keys; the superadmin also sees the platform keys. Key values are never returned."""
    q = select(ProviderCredential)
    if user.role == ROLE_SUPERADMIN:
        q = q.where(or_(ProviderCredential.user_id == user.id, ProviderCredential.user_id.is_(None)))
    else:
        q = q.where(ProviderCredential.user_id == user.id)
    return db.execute(q.order_by(ProviderCredential.created_at.desc())).scalars().all()


@router.post("/credentials", response_model=CredentialOut, status_code=201)
def add_credential(body: CredentialIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    preset = VENDORS.get(body.vendor)
    if preset is None or not preset.needs_key:
        raise HTTPException(422, f"Vendor '{body.vendor}' does not take an API key")
    if body.platform and user.role != ROLE_SUPERADMIN:
        raise HTTPException(403, "Only the superadmin can add platform keys")
    if preset.needs_base_url and not body.base_url:
        raise HTTPException(422, f"{preset.label} needs an endpoint URL")
    if body.base_url and not body.base_url.startswith("https://") and get_settings().is_production:
        raise HTTPException(422, "Endpoint URLs must use https")
    cred = ProviderCredential(
        user_id=None if body.platform else user.id,
        vendor=body.vendor,
        label=body.label,
        base_url=body.base_url or None,
        api_version=body.api_version or None,
        encrypted_key=encrypt_secret(body.api_key),
        key_hint=body.api_key[-4:],
    )
    db.add(cred)
    db.commit()
    return cred


@router.delete("/credentials/{cred_id}", status_code=204)
def delete_credential(cred_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cred = db.get(ProviderCredential, cred_id)
    owns = cred is not None and (
        cred.user_id == user.id or (cred.user_id is None and user.role == ROLE_SUPERADMIN)
    )
    if not owns:
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
