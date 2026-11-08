from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db, get_sync_session_factory
from app.engine.service import EngineService
from app.exchange.factory import build_adapter
from app.schemas import EngineActionRequest, EngineStatusResponse, PreflightResponse
from app.security.auth import get_current_user

router = APIRouter(prefix="/engine", tags=["engine"])

_engine_instance: EngineService | None = None


def get_engine(db: Session = Depends(get_db)) -> EngineService:
    global _engine_instance
    if _engine_instance is None:
        # build_adapter always attaches a trading gate; an adapter without one
        # would refuse every entry.
        adapter, _gate = build_adapter()
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
        trading_env=s.get("trading_env", settings.trading_env),
        ai_gate_mode=s.get("ai_gate_mode", settings.ai_gate_mode),
        portfolio_margin=s.get("portfolio_margin", settings.portfolio_margin),
        live_armed=s.get("live_armed", settings.live_armed),
    )


@router.get("/preflight", response_model=PreflightResponse)
async def engine_preflight(
    refresh: bool = False,
    user=Depends(get_current_user),
    engine: EngineService = Depends(get_engine),
):
    """
    Report exactly what the execution gate checked and what is still blocking it.

    This is the endpoint to read before enabling real money: it names the
    blocking conditions instead of leaving them implicit in a 4xx from the
    exchange.
    """
    settings = get_settings()
    gate = engine.gate
    if gate is None:
        return PreflightResponse(
            passed=False,
            blocking=["no trading gate attached to the exchange adapter"],
            trading_env=settings.trading_env,
            live_armed=settings.live_armed,
            kill_switch=settings.kill_switch,
            ai_gate_mode=settings.ai_gate_mode,
        )
    report = await gate.preflight(force=refresh)
    checks = dict(report["checks"])
    # Never echo key material; permissions only.
    checks.pop("api_key_permissions", None)
    perms = report["checks"].get("api_key_permissions") or {}
    checks["api_key_can_trade"] = perms.get("can_trade")
    checks["api_key_can_withdraw"] = perms.get("can_withdraw")
    return PreflightResponse(
        passed=report["passed"],
        blocking=report["blocking"],
        trading_env=settings.trading_env,
        live_armed=settings.live_armed,
        kill_switch=settings.kill_switch,
        ai_gate_mode=settings.ai_gate_mode,
        checks=checks,
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
