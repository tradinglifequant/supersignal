from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes.auth import router as auth_router
from app.api.routes.config import router as config_router
from app.api.routes.engine import router as engine_router, shutdown_engine_singleton
from app.api.routes.health import router as health_router
from app.api.routes.market import router as market_router, signals_alias_router
from app.api.routes.metrics import router as metrics_router
from app.api.routes.trades import router as trades_router
from app.api.websocket import router as ws_router
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.base import Base
import app.db.models  # noqa: F401 - ensure models registered
from app.db.session import create_sync_engine, ensure_schema_columns
from app.security.auth import get_current_user

settings = get_settings()
setup_logging(settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s %s env=%s", settings.app_name, settings.app_version, settings.app_env)
    bootstrap_engine = None
    try:
        bootstrap_engine = create_sync_engine()
        Base.metadata.create_all(bind=bootstrap_engine)
        ensure_schema_columns(bootstrap_engine)
        logger.info("DB tables ensured")
    except Exception as e:
        logger.error("DB init error: %s", e)
    finally:
        # The request/engine sessions use their own pooled engine; dispose this one
        # so startup does not leak a second connection pool for the process lifetime.
        if bootstrap_engine is not None:
            bootstrap_engine.dispose()
    yield
    await shutdown_engine_singleton()
    logger.info("Shutting down")


app = FastAPI(
    title="Super Signal API",
    version=settings.app_version,
    description="AI-powered Binance USDT-M Futures trading bot - FastAPI backend",
    lifespan=lifespan,
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    openapi_url=None if settings.is_production else "/api/openapi.json",
)

# CORS (explicit configured origins only; never wildcard)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled error %s: %s", request.url.path, exc, exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error", "code": "INTERNAL_ERROR"})


# Routers
app.include_router(health_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(config_router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(engine_router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(market_router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(signals_alias_router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(trades_router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(metrics_router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(ws_router, prefix="/api")


@app.get("/")
async def root():
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "environment": settings.app_env,
        "docs": None if settings.is_production else "/docs",
    }


@app.get("/api/healthz")
async def healthz():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
