from __future__ import annotations

import os
from typing import AsyncGenerator, Generator
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.core.config import get_settings


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def ensure_sqlite_parent_dir(url: str) -> None:
    if not _is_sqlite(url) or ":memory:" in url:
        return
    # Strip scheme (sqlite:/// or sqlite+aiosqlite:///)
    for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
        if url.startswith(prefix):
            path = url[len(prefix):].split("?")[0]
            if path.startswith("./"):
                path = path[2:]
            dirpath = os.path.dirname(path)
            if dirpath:
                os.makedirs(dirpath, exist_ok=True)
            return


def get_engine_args(database_url: str) -> dict:
    if _is_sqlite(database_url):
        return {"connect_args": {"check_same_thread": False}}
    return {
        "pool_size": 10,
        "max_overflow": 20,
        "pool_pre_ping": True,
    }


def create_sync_engine(database_url: str | None = None):
    settings = get_settings()
    url = database_url or settings.database_url
    ensure_sqlite_parent_dir(url)
    engine = create_engine(url, **get_engine_args(url), future=True)

    if _is_sqlite(url):
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, connection_record):  # type: ignore
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA foreign_keys=ON;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.execute("PRAGMA busy_timeout=5000;")
            cursor.close()

    return engine


def ensure_schema_columns(engine) -> None:
    """Ensure additive columns exist on pre-existing dev SQLite databases."""
    try:
        insp = inspect(engine)
        if "app_config" in insp.get_table_names():
            cols = {c["name"] for c in insp.get_columns("app_config")}
            if "max_consecutive_losses" not in cols:
                with engine.begin() as conn:
                    conn.execute(text("ALTER TABLE app_config ADD COLUMN max_consecutive_losses INTEGER DEFAULT 5 NOT NULL"))
    except Exception:
        pass


def create_async_engine_async(database_url: str | None = None):
    settings = get_settings()
    url = database_url or settings.database_url
    if url.startswith("sqlite:///"):
        url = url.replace("sqlite:///", "sqlite+aiosqlite:///")
        ensure_sqlite_parent_dir(url)
        return create_async_engine(url, connect_args={"check_same_thread": False}, future=True)
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    return create_async_engine(url, pool_size=5, max_overflow=10, pool_pre_ping=True, future=True)


_sync_engine = None  # type: ignore
_sync_session_factory: sessionmaker[Session] | None = None  # type: ignore


def get_sync_session_factory() -> sessionmaker[Session]:
    global _sync_engine, _sync_session_factory
    if _sync_session_factory is None:
        _sync_engine = create_sync_engine()
        _sync_session_factory = sessionmaker(bind=_sync_engine, autoflush=False, autocommit=False, future=True)
        try:
            from app.db.base import Base
            import app.db.models  # noqa: F401
            Base.metadata.create_all(bind=_sync_engine)
            ensure_schema_columns(_sync_engine)
        except Exception:
            pass
    return _sync_session_factory


def reset_session_factory():
    global _sync_engine, _sync_session_factory
    if _sync_engine is not None:
        try:
            _sync_engine.dispose()
        except Exception:
            pass
    _sync_engine = None
    _sync_session_factory = None


def get_db() -> Generator[Session, None, None]:
    factory = get_sync_session_factory()
    db = factory()
    try:
        yield db
    finally:
        db.close()


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
