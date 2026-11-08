from __future__ import annotations

from typing import AsyncGenerator, Generator
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.core.config import get_settings


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def get_engine_args(database_url: str) -> dict:
    if _is_sqlite(database_url):
        return {"connect_args": {"check_same_thread": False}}
    # Postgres production: require TLS
    return {
        "pool_size": 10,
        "max_overflow": 20,
        "pool_pre_ping": True,
    }


def create_sync_engine(database_url: str | None = None):
    settings = get_settings()
    url = database_url or settings.database_url
    # For sqlite, ensure directory exists
    if url.startswith("sqlite:///"):
        import os
        path = url.replace("sqlite:///", "")
        # handle relative
        if path.startswith("./"):
            path = path[2:]
        dirpath = os.path.dirname(path)
        if dirpath:
            os.makedirs(dirpath, exist_ok=True)
    engine = create_engine(url, **get_engine_args(url), future=True)

    if _is_sqlite(url):
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, connection_record):  # type: ignore
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA foreign_keys=ON;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.close()

    return engine


def create_async_engine_async(database_url: str | None = None):
    settings = get_settings()
    url = database_url or settings.database_url
    # Convert to async URL
    if url.startswith("sqlite:///"):
        url = url.replace("sqlite:///", "sqlite+aiosqlite:///")
        import os
        path = url.replace("sqlite+aiosqlite:///", "").split("?")[0]
        if path.startswith("./"):
            path = path[2:]
        dirpath = os.path.dirname(path)
        if dirpath:
            os.makedirs(dirpath, exist_ok=True)
        return create_async_engine(url, connect_args={"check_same_thread": False}, future=True)
    # Postgres async
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    return create_async_engine(url, pool_size=5, max_overflow=10, pool_pre_ping=True, future=True)


# Sync session factory (used for migrations and simple API)
_sync_engine = None  # type: ignore
_sync_session_factory: sessionmaker[Session] | None = None  # type: ignore

def get_sync_session_factory() -> sessionmaker[Session]:
    global _sync_engine, _sync_session_factory
    if _sync_session_factory is None:
        _sync_engine = create_sync_engine()
        _sync_session_factory = sessionmaker(bind=_sync_engine, autoflush=False, autocommit=False, future=True)
        # Ensure tables exist (dev auto-create; production uses Alembic but safe to ensure)
        try:
            from app.db.base import Base
            import app.db.models  # noqa: F401
            Base.metadata.create_all(bind=_sync_engine)
        except Exception:
            pass
    return _sync_session_factory

def reset_session_factory():
    global _sync_engine, _sync_session_factory
    _sync_engine = None
    _sync_session_factory = None

def get_db() -> Generator[Session, None, None]:
    factory = get_sync_session_factory()
    db = factory()
    try:
        yield db
    finally:
        db.close()

# Async
_async_engine = None
_async_session_factory: async_sessionmaker[AsyncSession] | None = None

def get_async_session_factory() -> async_sessionmaker[AsyncSession]:
    global _async_engine, _async_session_factory
    if _async_session_factory is None:
        _async_engine = create_async_engine_async()
        _async_session_factory = async_sessionmaker(bind=_async_engine, autoflush=False, expire_on_commit=False)
    return _async_session_factory

async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    factory = get_async_session_factory()
    async with factory() as session:
        yield session
