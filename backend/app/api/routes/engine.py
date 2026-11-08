from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas import EngineStatusResponse, EngineActionRequest
from app.security.auth import get_current_user, get_current_user_optional
from app.core.config import get_settings
# Engine service is singleton-like; we instantiate per request with shared adapter mock if needed
from app.exchange.binance_adapter import BinanceAdapter
from app.exchange.mock_adapter import MockBinanceAdapter
from app.engine.service import EngineService

router = APIRouter(prefix="/engine", tags=["engine"])

# Global engine instance placeholder (in production, managed via lifespan)
_engine_instance: EngineService | None = None

def get_engine(db: Session = Depends(get_db)) -> EngineService:
    global _engine_instance
    if _engine_instance is None:
        settings = get_settings()
        # Choose adapter: if no api key, use mock for dev/testnet without creds
        if settings.binance_api_key and settings.binance_api_secret:
            adapter = BinanceAdapter()
        else:
            adapter = MockBinanceAdapter()
        _engine_instance = EngineService(db, adapter)
    else:
        # update db reference
        _engine_instance.db = db
    return _engine_instance

@router.get("/status", response_model=EngineStatusResponse)
async def engine_status(db: Session = Depends(get_db), engine: EngineService = Depends(get_engine)):
    s = engine.get_status()
    settings = get_settings()
    return EngineStatusResponse(
        state=s["state"],
        environment=settings.app_env,
        changed_at=s.get("changed_at"),
        reason=s.get("reason"),
        binance_connected=False,  # TODO: WS health
        ai_connected=bool(settings.threerouter_api_key),
        db_connected=True,
        symbol_coverage=s.get("symbol_coverage", 0),
        open_positions=s.get("open_positions", 0),
        unprotected_positions=0,
    )

@router.post("/start")
async def engine_start(payload: EngineActionRequest = None, user=Depends(get_current_user), engine: EngineService = Depends(get_engine)):
    ok, issues = await engine.start()
    if not ok:
        raise HTTPException(status_code=400, detail={"message": "Readiness failed", "issues": issues})
    return {"status": "started"}

@router.post("/stop")
async def engine_stop(payload: EngineActionRequest = None, user=Depends(get_current_user), engine: EngineService = Depends(get_engine)):
    await engine.stop(reason=payload.reason if payload else "operator stop")
    return {"status": "stopped"}

@router.post("/emergency-stop")
async def emergency_stop(payload: EngineActionRequest = None, user=Depends(get_current_user), engine: EngineService = Depends(get_engine)):
    if not payload or not payload.confirm:
        raise HTTPException(status_code=400, detail="Emergency stop requires confirm=true")
    await engine.emergency_stop(reason=payload.reason or "emergency")
    return {"status": "emergency_stopped"}

@router.get("/readiness")
async def readiness_check(engine: EngineService = Depends(get_engine)):
    ok, issues = await engine.readiness_checks()
    return {"ready": ok, "issues": issues}
