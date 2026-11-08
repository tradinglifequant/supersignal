"""Security tests: credential encryption, secret masking, auth, no withdrawal."""
import pytest
from app.security.encryption import encrypt_value, decrypt_value, mask_secret, generate_key
from app.security.auth import hash_password, verify_password, create_access_token, decode_token
from app.core.config import Settings
from decimal import Decimal

def test_encryption_roundtrip():
    key = generate_key()
    plaintext = "my-binance-secret-123"
    ct = encrypt_value(plaintext, key=key)
    assert ct != plaintext
    pt = decrypt_value(ct, key=key)
    assert pt == plaintext

def test_encryption_wrong_key_fails():
    key1 = generate_key()
    key2 = generate_key()
    ct = encrypt_value("secret", key=key1)
    with pytest.raises(ValueError):
        decrypt_value(ct, key=key2)

def test_mask_secret():
    assert mask_secret("1234567890", visible=4) == "1234***90"
    assert mask_secret("") == "***"
    assert mask_secret("ab") == "***"

def test_password_hashing():
    h = hash_password("admin123")
    assert verify_password("admin123", h)
    assert not verify_password("wrong", h)

def test_jwt_creation_and_decode():
    token = create_access_token({"sub": "admin"})
    payload = decode_token(token)
    assert payload["sub"] == "admin"
    assert "exp" in payload

def test_hard_limits_blocks_engine_start():
    settings = Settings(database_url="sqlite:///:memory:", app_env="production", daily_loss_limit=Decimal("0"), max_drawdown_pct=Decimal("0"), max_aggregate_exposure=Decimal("0"), max_trade_allocation=Decimal("0"), max_slippage_bps=Decimal("0"))  # type: ignore
    ok, missing = settings.check_hard_limits_configured()
    assert not ok
    assert len(missing) >= 4

def test_log_redaction():
    from app.core.logging import redact_obj
    obj = {"api_key": "12345", "username": "admin", "nested": {"api_secret": "shh"}}
    redacted = redact_obj(obj)
    assert redacted["api_key"] == "***REDACTED***"
    assert redacted["username"] == "admin"
    assert redacted["nested"]["api_secret"] == "***REDACTED***"

    text = "api_key=123456 and Bearer token abcdef123"
    from app.core.logging import REDACT_PATTERNS
    import re
    s = text
    for pat, repl in REDACT_PATTERNS:
        s = pat.sub(repl, s)
    assert "***REDACTED***" in s
    assert "123456" not in s
