from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db, get_sync_session_factory
from app.engine.service import EngineService
from app.exchange.binance_adapter import BinanceAdapter
from app.exchange.mock_adapter import MockBinanceAdapter
from app.schemas import EngineActionRequest, EngineStatusResponse
from app.security.auth import get_current_user

router = APIRouter(prefix="/engine", tags=["engine"])

_engine_instance: EngineService | None = None


def get_engine(db: Session = Depends(get_db)) -> EngineService:
    global _engine_instance
    if _engine_instance is None:
        settings = get_settings()
        if settings.binance_api_key and settings.binance_api_secret:
            adapter = BinanceAdapter()
        else:
            adapter = MockBinanceAdapter()
        _engine_instance = EngineService(db, adapter, session_factory=get_sync_session_factory())
    else:
        _engine_instance.db = db
    return _engine_instance


async def shutdown_engine_singleton() -> None:
    global _engine_instance
    if _engine_instance is not None:
        await _engine_instance.shutdown()
        _engine_instance = None


@router.get("/status", response_model=EngineStatusResponse)
async def engine_status(
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
    engine: EngineService = Depends(get_engine),
):
    s = engine.get_status()
    settings = get_settings()
    return EngineStatusResponse(
        state=s["state"],
        environment=settings.app_env,
        changed_at=s.get("changed_at"),
        reason=s.get("reason"),
        risk_blocks=s.get("risk_blocks", []),
        binance_connected=s.get("binance_connected", False),
        ai_connected=bool(settings.threerouter_api_key),
        db_connected=True,
        symbol_coverage=s.get("symbol_coverage", 0),
        open_positions=s.get("open_positions", 0),
        unprotected_positions=s.get("unprotected_positions", 0),
    )


@router.post("/start")
async def engine_start(
    payload: EngineActionRequest | None = None,
    user=Depends(get_current_user),
    engine: EngineService = Depends(get_engine),
):
    ok, issues = await engine.start(actor=user["username"])
    if not ok:
        raise HTTPException(status_code=400, detail={"message": "Readiness failed", "issues": issues})
    return {"status": "started"}


@router.post("/stop")
async def engine_stop(
    payload: EngineActionRequest | None = None,
    user=Depends(get_current_user),
    engine: EngineService = Depends(get_engine),
):
    await engine.stop(reason=(payload.reason if payload and payload.reason else "operator stop"), actor=user["username"])
    return {"status": "stopped"}


@router.post("/emergency-stop")
async def emergency_stop(
    payload: EngineActionRequest | None = None,
    user=Depends(get_current_user),
    engine: EngineService = Depends(get_engine),
):
    if not payload or not payload.confirm:
        raise HTTPException(status_code=400, detail="Emergency stop requires confirm=true")
    await engine.emergency_stop(reason=payload.reason or "emergency", actor=user["username"])
    return {"status": "emergency_stopped"}


@router.get("/readiness")
async def readiness_check(
    user=Depends(get_current_user),
    engine: EngineService = Depends(get_engine),
):
    ok, issues = await engine.readiness_checks()
    return {"ready": ok, "issues": issues}
