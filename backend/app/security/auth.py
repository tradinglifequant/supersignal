from __future__ import annotations

import logging
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer(auto_error=False)
_BCRYPT_HASH = re.compile(r"^\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}$")
_LEGACY_SECRETS = {"change-me-jwt-secret-key-32-chars-min", "change-me-jwt-secret"}

# Some reverse proxies and sandbox preview tunnels forward custom headers but drop
# or rewrite `Authorization`. The token is accepted from either header; both carry
# the same bearer token and go through identical verification and jti revocation.
TOKEN_HEADER_NAME = "x-access-token"

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


class AuthFailure(Exception):
    """Carries a machine-readable reason so callers can log without leaking the token."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def extract_token(credentials: Optional[HTTPAuthorizationCredentials], request: Optional[Request]) -> tuple[Optional[str], str]:
    """Return (token, source). `Authorization: Bearer` wins, then X-Access-Token."""
    if credentials is not None and credentials.credentials:
        return credentials.credentials, "authorization"
    if request is not None:
        authorization = request.headers.get("authorization") or ""
        if authorization.lower().startswith("bearer "):
            raw = authorization[7:].strip()
            if raw:
                return raw, "authorization"
        header = request.headers.get(TOKEN_HEADER_NAME) or ""
        raw = header[7:].strip() if header.lower().startswith("bearer ") else header.strip()
        if raw:
            return raw, TOKEN_HEADER_NAME
    return None, "none"


def verify_token(token: str) -> dict:
    """Decode and validate a token, raising AuthFailure with a precise reason."""
    require_auth_config()
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"require_exp": True, "require_sub": True},
        )
    except JWTError as exc:
        name = type(exc).__name__
        if name == "ExpiredSignatureError":
            raise AuthFailure("token_expired") from exc
        if name in ("JWTClaimsError",):
            raise AuthFailure("missing_required_claim") from exc
        raise AuthFailure("signature_or_format_invalid") from exc
    except (ValueError, TypeError) as exc:
        raise AuthFailure("malformed_token") from exc

    if payload.get("sub") != settings.admin_username:
        raise AuthFailure("subject_mismatch")
    if is_jti_revoked(payload.get("jti")):
        raise AuthFailure("token_revoked")
    return payload


def decode_token(token: str) -> dict:
    """Backwards-compatible wrapper used by the WebSocket handler."""
    try:
        return verify_token(token)
    except AuthFailure as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> dict:
    token, source = extract_token(credentials, request)
    if not token:
        # Log which token-bearing headers actually arrived. This is what makes a
        # proxy that drops `Authorization` visible instead of an unexplained 401.
        logger.warning(
            "Auth rejected: no bearer token (authorization_header=%s, %s=%s)",
            bool(request.headers.get("authorization")),
            TOKEN_HEADER_NAME,
            bool(request.headers.get(TOKEN_HEADER_NAME)),
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = verify_token(token)
    except AuthFailure as exc:
        logger.warning("Auth rejected via %s header: %s", source, exc.reason)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc
    return {"username": payload["sub"], "jti": payload.get("jti"), "exp": payload.get("exp")}
