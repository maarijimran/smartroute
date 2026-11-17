"""Authentication and role-based access control dependencies.

Roles (single organisation):
  superadmin  privacy policy, model registry, platform keys, roles, everything below
  admin       manage ordinary users, view analytics and the confidential audit log
  user        chat, own documents, own cloud keys, own SmartRoute API keys
"""

import threading
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import ROLE_ADMIN, ROLE_SUPERADMIN, ApiKey, User
from .security import API_KEY_PREFIX, decode_access_token, hash_api_key

_bearer = HTTPBearer(auto_error=False)


def _unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"})


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer), db: Session = Depends(get_db)
) -> User:
    """Login-token authentication for the web interface."""
    if creds is None:
        raise _unauthorized()
    claims = decode_access_token(creds.credentials)
    if not claims:
        raise _unauthorized("Invalid or expired session")
    user = db.get(User, claims.get("sub"))
    if user is None or not user.is_active:
        raise _unauthorized("Account is disabled or no longer exists")
    return user


def require_roles(*roles: str):
    def guard(user: User = Depends(get_current_user)) -> User:
        # The role is read from the database on every request, so a demotion takes
        # effect immediately instead of when the token expires.
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have permission for this action")
        return user

    return guard


require_superadmin = require_roles(ROLE_SUPERADMIN)
require_admin = require_roles(ROLE_SUPERADMIN, ROLE_ADMIN)


class _RateLimiter:
    """Sliding one-minute window per key. In-process: with several workers each
    worker counts separately, so put a shared limiter (reverse proxy) in front for
    strict limits."""

    def __init__(self):
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > 60:
                hits.popleft()
            if len(hits) >= limit:
                return False
            hits.append(now)
            return True


rate_limiter = _RateLimiter()


def get_api_principal(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer), db: Session = Depends(get_db)
) -> tuple[User, ApiKey]:
    """SmartRoute API-key authentication for the /v1 router API."""
    if creds is None or not creds.credentials.startswith(API_KEY_PREFIX):
        raise _unauthorized("Provide a SmartRoute API key: Authorization: Bearer sr-...")
    key = db.execute(select(ApiKey).where(ApiKey.key_hash == hash_api_key(creds.credentials))).scalars().first()
    if key is None or key.revoked:
        raise _unauthorized("Invalid or revoked API key")
    user = db.get(User, key.user_id)
    if user is None or not user.is_active:
        raise _unauthorized("The account that owns this key is disabled")
    if not rate_limiter.allow(key.id, get_settings().rate_limit_rpm):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Rate limit exceeded", headers={"Retry-After": "60"})
    return user, key
