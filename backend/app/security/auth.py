from __future__ import annotations

import re
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


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(plain, hashed)
    except (ValueError, TypeError):
        return False


def require_auth_config() -> None:
    settings = get_settings()
    if (not settings.admin_username.strip()
            or not _BCRYPT_HASH.fullmatch(settings.admin_password_hash)
            or not 12 <= int(settings.admin_password_hash[4:6]) <= 16
            or len(settings.jwt_secret_key) < 32
            or settings.jwt_secret_key in _LEGACY_SECRETS
            or settings.jwt_algorithm != "HS256"
            or settings.jwt_expire_minutes <= 0):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="Authentication is not configured")


def get_admin_credentials() -> tuple[str, str]:
    require_auth_config()
    settings = get_settings()
    return settings.admin_username, settings.admin_password_hash


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    require_auth_config()
    settings = get_settings()
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.jwt_expire_minutes))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    require_auth_config()
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm],
                             options={"require_exp": True, "require_sub": True})
        if payload.get("sub") != settings.admin_username:
            raise JWTError("Invalid subject")
        return payload
    except (JWTError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> dict:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    payload = decode_token(credentials.credentials)
    return {"username": payload["sub"]}
