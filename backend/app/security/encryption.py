from __future__ import annotations

import logging
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_DEV_EPHEMERAL_KEY: str | None = None


def generate_key() -> str:
    return Fernet.generate_key().decode()


def reset_encryption_cache() -> None:
    global _DEV_EPHEMERAL_KEY
    _DEV_EPHEMERAL_KEY = None


def get_fernet(key: str | None = None) -> Fernet:
    global _DEV_EPHEMERAL_KEY
    settings = get_settings()
    k = key or settings.credentials_encryption_key
    if not k:
        if settings.is_production:
            raise ValueError("CREDENTIALS_ENCRYPTION_KEY must be configured in production")
        if _DEV_EPHEMERAL_KEY is None:
            _DEV_EPHEMERAL_KEY = generate_key()
            logger.warning("CREDENTIALS_ENCRYPTION_KEY not set; using process-local ephemeral key for non-production")
        k = _DEV_EPHEMERAL_KEY
    try:
        return Fernet(k.encode() if isinstance(k, str) else k)
    except Exception as e:
        raise ValueError(f"Invalid encryption key: {e}") from e


def encrypt_value(plaintext: str, key: str | None = None) -> str:
    f = get_fernet(key)
    return f.encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str, key: str | None = None) -> str:
    f = get_fernet(key)
    try:
        return f.decrypt(ciphertext.encode()).decode()
    except InvalidToken as e:
        raise ValueError("Failed to decrypt credential - invalid key or corrupted data") from e


def mask_secret(value: str, visible: int = 4) -> str:
    if not value:
        return "***"
    if len(value) <= visible:
        return "***"
    return value[:visible] + "***" + value[-2:]
