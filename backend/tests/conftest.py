import os
import tempfile
from pathlib import Path

# Never load the operator's database or exchange/provider credentials in tests.
_test_database = Path(tempfile.mkdtemp(prefix="supersignal-tests-")) / "test.sqlite"
os.environ["DATABASE_URL"] = f"sqlite:///{_test_database.as_posix()}"
os.environ["BINANCE_API_KEY"] = ""
os.environ["BINANCE_API_SECRET"] = ""
os.environ["THREEROUTER_API_KEY"] = ""
os.environ["BINANCE_TESTNET"] = "true"
os.environ["CORS_ORIGINS"] = "http://localhost:5173,http://127.0.0.1:5173"
os.environ["CREDENTIALS_ENCRYPTION_KEY"] = ""
# Pin the execution gate too. Without these the suite inherits whatever the
# operator's .env says, so a developer running AI_GATE_MODE=deterministic would
# get a green suite that never exercised the LLM fail-closed path at all.
os.environ["AI_GATE_MODE"] = "threerouter"
os.environ["TRADING_ENV"] = "none"
os.environ["PORTFOLIO_MARGIN"] = "false"
os.environ["KILL_SWITCH"] = "false"
os.environ["LIVE_TRADING_OPT_IN"] = "false"
os.environ["LIVE_TRADING_ACKNOWLEDGEMENT"] = ""
os.environ["REQUIRE_TESTNET_SOAK_HOURS"] = "0"
# Test-only credentials; never use these outside the test suite.
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["JWT_SECRET_KEY"] = "test-only-key-not-for-production-000000000000"
from passlib.hash import bcrypt

os.environ["ADMIN_PASSWORD_HASH"] = bcrypt.hash("test-password")
os.environ["APP_ENV"] = "development"

import pytest
from app.db.base import Base
import app.db.models  # noqa: F401


@pytest.fixture(autouse=True, scope="session")
def ensure_tables_session():
    from app.core.config import get_settings
    from app.db.session import ensure_schema_columns, get_sync_session_factory, reset_session_factory

    get_settings.cache_clear()  # type: ignore
    reset_session_factory()
    try:
        factory = get_sync_session_factory()
        engine = factory.kw["bind"]
        Base.metadata.create_all(bind=engine)
        ensure_schema_columns(engine)
    except Exception as e:
        print(f"ensure tables failed: {e}")
    yield


@pytest.fixture(autouse=True)
def ensure_tables_each():
    from app.db.base import Base
    from app.db.session import ensure_schema_columns, get_sync_session_factory
    from app.security.auth import clear_revoked_jtis

    clear_revoked_jtis()
    try:
        factory = get_sync_session_factory()
        engine = factory.kw["bind"]
        Base.metadata.create_all(bind=engine)
        ensure_schema_columns(engine)
    except Exception:
        pass
    yield
