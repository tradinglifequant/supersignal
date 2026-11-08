from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.session import create_sync_engine
from app.db.base import Base
import app.db.models  # ensure models registered

# Routers
from app.api.routes.health import router as health_router
from app.api.routes.auth import router as auth_router
from app.api.routes.config import router as config_router
from app.api.routes.engine import router as engine_router
from app.api.routes.market import router as market_router
from app.api.routes.trades import router as trades_router
from app.api.routes.metrics import router as metrics_router
from app.api.websocket import router as ws_router
from app.security.auth import get_current_user

settings = get_settings()
setup_logging(settings.log_level)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info(f"Starting {settings.app_name} {settings.app_version} env={settings.app_env}")
    # Ensure DB tables exist (for SQLite dev, auto create; production uses Alembic)
    try:
        engine = create_sync_engine()
        Base.metadata.create_all(bind=engine)
        logger.info("DB tables ensured")
    except Exception as e:
        logger.error(f"DB init error: {e}")
    yield
    # Shutdown
    logger.info("Shutting down")

app = FastAPI(
    title="Super Signal API",
    version=settings.app_version,
    description="AI-powered Binance USDT-M Futures trading bot - FastAPI backend",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/api/openapi.json",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global exception handler with redaction
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"Unhandled error {request.url.path}: {exc}", exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error", "code": "INTERNAL_ERROR"})

# Routers
app.include_router(health_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(config_router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(engine_router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(market_router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(trades_router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(metrics_router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(ws_router, prefix="/api")

@app.get("/")
async def root():
    return {"name": settings.app_name, "version": settings.app_version, "environment": settings.app_env, "docs": "/docs"}

@app.get("/api/healthz")
async def healthz():
    return {"status": "ok"}

# For local dev, expose app for uvicorn
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
