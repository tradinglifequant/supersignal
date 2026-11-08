from __future__ import annotations

import base64
import os
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


def generate_key() -> str:
    return Fernet.generate_key().decode()


def get_fernet(key: str | None = None) -> Fernet:
    settings = get_settings()
    k = key or settings.credentials_encryption_key
    if not k:
        # For dev/test, generate ephemeral key (not persisted)
        # In production this MUST be set via env
        k = generate_key()
    # Validate
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
