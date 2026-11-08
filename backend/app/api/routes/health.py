from __future__ import annotations

import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import get_db
from app.schemas import HealthResponse, ReadyResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
async def health():
    settings = get_settings()
    return HealthResponse(
        status="ok",
        version=settings.app_version,
        environment=settings.app_env,
        timestamp=datetime.now(timezone.utc),
    )


@router.get("/ready", response_model=ReadyResponse)
async def readiness(db: Session = Depends(get_db)):
    settings = get_settings()
    checks: dict = {}
    ready = True
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        logger.error("Readiness database check failed: %s", e)
        checks["database"] = "error"
        ready = False
    checks["binance"] = "entry_locked (safety gate)" if settings.binance_api_key else "mock_mode (no credentials)"
    checks["threerouter"] = "configured" if settings.threerouter_api_key else "not configured (fail-closed)"
    ok, missing = settings.check_hard_limits_configured()
    checks["hard_limits"] = "ok" if ok else f"missing: {missing}"
    if not ok:
        ready = False

    return ReadyResponse(ready=ready, checks=checks, timestamp=datetime.now(timezone.utc))
