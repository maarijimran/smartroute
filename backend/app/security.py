"""Password hashing, login tokens, API keys and secret encryption."""

import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from cryptography.fernet import Fernet, InvalidToken

from .config import get_settings

API_KEY_PREFIX = "sr-"
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode()


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = base64.urlsafe_b64decode(salt_b64)
        expected = base64.urlsafe_b64decode(digest_b64)
        actual = hashlib.scrypt(password.encode(), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: str, role: str) -> str:
    settings = get_settings()
    expires = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_minutes)
    return jwt.encode({"sub": user_id, "role": role, "exp": expires}, settings.secret_key, algorithm="HS256")


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


def new_api_key() -> tuple[str, str, str]:
    """Returns (plain key shown once, display prefix, hash stored in the database)."""
    plain = API_KEY_PREFIX + secrets.token_urlsafe(32)
    return plain, plain[:10], hash_api_key(plain)


def hash_api_key(plain: str) -> str:
    return hashlib.sha256(plain.encode()).hexdigest()


def _fernet() -> Fernet:
    settings = get_settings()
    if settings.encryption_key:
        return Fernet(settings.encryption_key.encode())
    # Development only: derive a key so the app runs without extra setup.
    # validate_for_startup() refuses to start in production without a real key.
    derived = base64.urlsafe_b64encode(hashlib.sha256(settings.secret_key.encode()).digest())
    return Fernet(derived)


def encrypt_secret(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_secret(token: str) -> str | None:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return None
