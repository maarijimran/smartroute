"""Login, registration and user management (RBAC)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.ocr import get_ocr
from ..core.policy_config import load_policy
from ..core.privacy.gate import user_may_send_confidential
from ..db import get_db
from ..deps import get_current_user, require_admin
from ..models import ROLE_SUPERADMIN, ROLE_USER, PolicyChange, User
from ..schemas import LoginIn, RegisterIn, TokenOut, UserCreate, UserOut, UserUpdate
from ..security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/api", tags=["auth"])


def _token(user: User) -> TokenOut:
    return TokenOut(access_token=create_access_token(user.id, user.role), user=UserOut.model_validate(user))


@router.post("/auth/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.execute(select(User).where(User.email == body.email.lower().strip())).scalars().first()
    # Same error for unknown email and wrong password, so accounts cannot be enumerated.
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Incorrect email or password")
    if not user.is_active:
        raise HTTPException(403, "This account has been disabled")
    return _token(user)


@router.post("/auth/register", response_model=TokenOut)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    if not load_policy(db).allow_self_registration:
        raise HTTPException(403, "Self-registration is disabled. Ask an administrator for an account.")
    email = body.email.lower().strip()
    if db.execute(select(User).where(User.email == email)).scalars().first():
        raise HTTPException(409, "An account with this email already exists")
    user = User(email=email, name=body.name, password_hash=hash_password(body.password), role=ROLE_USER)
    db.add(user)
    db.commit()
    return _token(user)


@router.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.get("/auth/permissions")
def permissions(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """What the current user is allowed to do, so the interface can explain it up front."""
    cfg = load_policy(db)
    return {
        "role": user.role,
        "cloud_enabled": cfg.cloud_enabled,
        "may_send_confidential_to_cloud": cfg.cloud_enabled
        and user_may_send_confidential(user.allow_confidential_cloud, cfg),
        "consent_required": cfg.require_consent_for_confidential,
        "may_pin_model": cfg.users_may_pin_model or user.role != ROLE_USER,
        "monthly_budget_usd": user.monthly_budget_usd,
        "ocr_enabled": get_ocr() is not None,
    }


@router.get("/users", response_model=list[UserOut])
def list_users(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return db.execute(select(User).order_by(User.created_at)).scalars().all()


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, actor: User = Depends(require_admin), db: Session = Depends(get_db)):
    if body.role != ROLE_USER and actor.role != ROLE_SUPERADMIN:
        raise HTTPException(403, "Only the superadmin can create admin or superadmin accounts")
    email = body.email.lower().strip()
    if db.execute(select(User).where(User.email == email)).scalars().first():
        raise HTTPException(409, "An account with this email already exists")
    user = User(email=email, name=body.name, password_hash=hash_password(body.password), role=body.role)
    db.add(user)
    db.commit()
    return user


def _superadmin_count(db: Session) -> int:
    return db.execute(
        select(func.count()).select_from(User).where(User.role == ROLE_SUPERADMIN, User.is_active.is_(True))
    ).scalar_one()


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: str, body: UserUpdate, actor: User = Depends(require_admin), db: Session = Depends(get_db)):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "User not found")
    is_super = actor.role == ROLE_SUPERADMIN
    if not is_super and target.role != ROLE_USER:
        raise HTTPException(403, "Admins can only manage ordinary user accounts")
    privileged = body.role is not None or body.allow_confidential_cloud is not None or body.inherit_confidential_default
    if privileged and not is_super:
        raise HTTPException(403, "Only the superadmin can change roles or confidential-data permissions")

    changes: dict = {}
    if body.name is not None:
        target.name = body.name
    if body.password:
        target.password_hash = hash_password(body.password)
        changes["password"] = ["(hidden)", "(changed)"]
    if body.monthly_budget_usd is not None or body.clear_budget:
        new_budget = None if body.clear_budget else body.monthly_budget_usd
        if new_budget != target.monthly_budget_usd:
            changes["monthly_budget_usd"] = [target.monthly_budget_usd, new_budget]
            target.monthly_budget_usd = new_budget
    removing_super = target.role == ROLE_SUPERADMIN and (
        (body.role is not None and body.role != ROLE_SUPERADMIN) or body.is_active is False
    )
    if removing_super and _superadmin_count(db) <= 1:
        raise HTTPException(409, "The last active superadmin cannot be demoted or disabled")
    if body.is_active is not None and body.is_active != target.is_active:
        changes["is_active"] = [target.is_active, body.is_active]
        target.is_active = body.is_active
    if body.role is not None and body.role != target.role:
        changes["role"] = [target.role, body.role]
        target.role = body.role
    if body.inherit_confidential_default or body.allow_confidential_cloud is not None:
        new_value = None if body.inherit_confidential_default else body.allow_confidential_cloud
        if new_value != target.allow_confidential_cloud:
            changes["allow_confidential_cloud"] = [target.allow_confidential_cloud, new_value]
            target.allow_confidential_cloud = new_value
    if changes:
        db.add(PolicyChange(actor_id=actor.id, actor_email=actor.email, target=f"user:{target.email}", changes=changes))
    db.commit()
    return target
