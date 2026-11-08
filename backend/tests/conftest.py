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
# Test-only credentials; never use these outside the test suite.
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["JWT_SECRET_KEY"] = "test-only-key-not-for-production-000000000000"
from passlib.hash import bcrypt
os.environ["ADMIN_PASSWORD_HASH"] = bcrypt.hash("test-password")
os.environ.setdefault("APP_ENV", "development")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.base import Base
import app.db.models

@pytest.fixture(autouse=True, scope="session")
def ensure_tables_session():
    # Ensure file DB has tables before any test
    from app.db.session import get_sync_session_factory, reset_session_factory
    from app.core.config import get_settings
    # Reset cached settings/engine to ensure fresh
    get_settings.cache_clear()  # type: ignore
    reset_session_factory()
    try:
        factory = get_sync_session_factory()
        engine = factory.kw["bind"]
        Base.metadata.create_all(bind=engine)
        print(f"DB tables ensured at {engine.url}")
    except Exception as e:
        print(f"ensure tables failed: {e}")
    yield

@pytest.fixture(autouse=True)
def ensure_tables_each():
    # Also ensure per-test tables in case of memory DB overrides
    from app.db.base import Base
    from app.db.session import get_sync_session_factory
    try:
        factory = get_sync_session_factory()
        engine = factory.kw["bind"]
        Base.metadata.create_all(bind=engine)
    except Exception:
        pass
    yield
