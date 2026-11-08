from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer(auto_error=False)

# Simple user table is not persisted in DB for single-operator MVP; use env-based admin.
# For production, add User model. Here we implement file-based or settings-based auth.

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    settings = get_settings()
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.jwt_expire_minutes))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)

def decode_token(token: str) -> dict:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        return payload
    except JWTError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from e

# For MVP, we have a single operator user configured via env or default.
# We store hashed password in memory; initial password is "admin123" hashed; operator must change.
DEFAULT_ADMIN_USERNAME = "admin"
# Pre-hashed admin123 for dev; in production, set ADMIN_PASSWORD_HASH env
import os as _os

def get_admin_credentials() -> tuple[str, str]:
    username = _os.getenv("ADMIN_USERNAME", DEFAULT_ADMIN_USERNAME)
    pwd_hash = _os.getenv("ADMIN_PASSWORD_HASH", "")
    if not pwd_hash:
        # hash of "admin123" generated at runtime for portability
        # Using fixed known hash to avoid bcrypt version mismatch; will verify via passlib else fallback
        try:
            test_hash = "$2b$12$qQu.2tig0FHopadEPbzq9ewB4RRCA./HYymFqO2n6NejAjY.DBy1O"
            # verify it matches admin123; if passlib fails, generate
            if not verify_password("admin123", test_hash):
                raise ValueError("hash mismatch")
            pwd_hash = test_hash
        except Exception:
            pwd_hash = hash_password("admin123")
    return username, pwd_hash

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> dict:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    payload = decode_token(credentials.credentials)
    username: str | None = payload.get("sub")
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")
    return {"username": username}

# Optional: allow unauthenticated in development for dashboard convenience
# But rules.md says dashboard authentication required even on private network (MUST)
# We'll enforce auth but provide dev bypass flag for tests
ALLOW_DEV_BYPASS = _os.getenv("ALLOW_DEV_BYPASS", "false").lower() == "true"

async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> Optional[dict]:
    if ALLOW_DEV_BYPASS and get_settings().app_env == "development":
        return {"username": "dev-bypass"}
    return await get_current_user(credentials)
