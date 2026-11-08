from __future__ import annotations

import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer(auto_error=False)
_BCRYPT_HASH = re.compile(r"^\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}$")
_LEGACY_SECRETS = {"change-me-jwt-secret-key-32-chars-min", "change-me-jwt-secret"}

# Bounded process-local JTI revocation map (jti -> exp unix timestamp)
_revoked_jtis: dict[str, float] = {}


def _prune_revoked_jtis() -> None:
    now = time.time()
    expired = [jti for jti, exp in _revoked_jtis.items() if exp <= now]
    for jti in expired:
        _revoked_jtis.pop(jti, None)


def is_jti_revoked(jti: Optional[str]) -> bool:
    if not jti:
        return False
    _prune_revoked_jtis()
    return jti in _revoked_jtis


def revoke_token_payload(payload: dict) -> None:
    _prune_revoked_jtis()
    jti = payload.get("jti")
    exp = payload.get("exp")
    if isinstance(jti, str) and jti and exp is not None:
        _revoked_jtis[jti] = float(exp)


def clear_revoked_jtis() -> None:
    _revoked_jtis.clear()


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(plain, hashed)
    except (ValueError, TypeError):
        return False


def require_auth_config() -> None:
    settings = get_settings()
    if (
        not settings.admin_username.strip()
        or not _BCRYPT_HASH.fullmatch(settings.admin_password_hash)
        or not 12 <= int(settings.admin_password_hash[4:6]) <= 16
        or len(settings.jwt_secret_key) < 32
        or settings.jwt_secret_key in _LEGACY_SECRETS
        or settings.jwt_algorithm != "HS256"
        or settings.jwt_expire_minutes <= 0
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured",
        )


def get_admin_credentials() -> tuple[str, str]:
    require_auth_config()
    settings = get_settings()
    return settings.admin_username, settings.admin_password_hash


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    require_auth_config()
    settings = get_settings()
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.jwt_expire_minutes))
    to_encode.setdefault("jti", uuid.uuid4().hex)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    require_auth_config()
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"require_exp": True, "require_sub": True},
        )
        if payload.get("sub") != settings.admin_username:
            raise JWTError("Invalid subject")
        if is_jti_revoked(payload.get("jti")):
            raise JWTError("Token has been revoked")
        return payload
    except (JWTError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> dict:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    payload = decode_token(credentials.credentials)
    return {"username": payload["sub"], "jti": payload.get("jti"), "exp": payload.get("exp")}
