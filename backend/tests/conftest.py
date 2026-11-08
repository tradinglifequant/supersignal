import os
os.environ.setdefault("ALLOW_DEV_BYPASS", "true")
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
