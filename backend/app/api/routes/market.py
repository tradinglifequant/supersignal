from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.routes.engine import get_engine
from app.db.models import AppConfig, SignalCandidate, SymbolMetadata
from app.db.session import get_db
from app.engine.service import EngineService
from app.schemas import SignalCandidateResponse, SymbolInfo
from app.security.auth import get_current_user

router = APIRouter(prefix="/market", tags=["market"])
signals_alias_router = APIRouter(tags=["market"])


def _query_signals(
    db: Session,
    status: Optional[str],
    symbol: Optional[str],
    direction: Optional[str],
    limit: int,
) -> List[SignalCandidateResponse]:
    q = db.query(SignalCandidate).order_by(SignalCandidate.detected_at.desc())
    if status:
        q = q.filter(SignalCandidate.status == status.upper())
    if symbol:
        q = q.filter(SignalCandidate.symbol == symbol.upper())
    if direction:
        q = q.filter(SignalCandidate.direction == direction.upper())
    rows = q.limit(limit).all()
    return [
        SignalCandidateResponse(
            id=r.id,
            event_key=r.event_key,
            symbol=r.symbol,
            direction=r.direction,
            current_price=str(r.current_price),
            reference_price=str(r.reference_price),
            change_pct=str(r.change_pct),
            window_seconds=r.window_seconds,
            detected_at=r.detected_at,
            exchange_event_time=r.exchange_event_time,
            expires_at=r.expires_at,
            status=r.status,
            rejection_reason=r.rejection_reason,
        )
        for r in rows
    ]


@router.get("/symbols", response_model=List[SymbolInfo])
async def list_symbols(
    db: Session = Depends(get_db),
    engine: EngineService = Depends(get_engine),
    user=Depends(get_current_user),
):
    rows = db.query(SymbolMetadata).order_by(SymbolMetadata.symbol.asc()).all()
    cfg = db.query(AppConfig).first()
    window = cfg.trigger_window_seconds if cfg else engine.settings.trigger_window_seconds
    now = datetime.now(timezone.utc)
    result = []
    for r in rows:
        last = engine.price_history.get_last_price(r.symbol)
        chg = engine.price_history.get_change_pct(r.symbol, window, now)
        result.append(
            SymbolInfo(
                symbol=r.symbol,
                status=r.status,
                contract_type=r.contract_type,
                margin_asset=r.margin_asset,
                price_tick=str(r.price_tick),
                qty_step=str(r.qty_step),
                min_qty=str(r.min_qty),
                min_notional=str(r.min_notional),
                is_eligible=r.is_eligible,
                ineligibility_reason=r.ineligibility_reason,
                last_price=str(last.price) if last else None,
                change_pct_180s=f"{chg:.4f}" if chg is not None else None,
            )
        )
    return result


@router.get("/signals", response_model=List[SignalCandidateResponse])
async def list_signals(
    status: Optional[str] = Query(None),
    symbol: Optional[str] = Query(None),
    direction: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return _query_signals(db, status, symbol, direction, limit)


@signals_alias_router.get("/signals", response_model=List[SignalCandidateResponse])
async def list_signals_root_alias(
    status: Optional[str] = Query(None),
    symbol: Optional[str] = Query(None),
    direction: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return _query_signals(db, status, symbol, direction, limit)


@router.get("/scanner")
async def scanner(
    db: Session = Depends(get_db),
    engine: EngineService = Depends(get_engine),
    user=Depends(get_current_user),
):
    rows = db.query(SymbolMetadata).filter(SymbolMetadata.is_eligible == True).order_by(SymbolMetadata.symbol.asc()).all()  # noqa: E712
    cfg = db.query(AppConfig).first()
    window = cfg.trigger_window_seconds if cfg else engine.settings.trigger_window_seconds
    now = datetime.now(timezone.utc)
    scanner_data = []
    for r in rows:
        last = engine.price_history.get_last_price(r.symbol)
        chg = engine.price_history.get_change_pct(r.symbol, window, now)
        scanner_data.append(
            {
                "symbol": r.symbol,
                "status": r.status,
                "last_price": str(last.price) if last else None,
                "change_pct": f"{chg:.4f}" if chg is not None else None,
                "is_eligible": r.is_eligible,
                "fresh": not engine.price_history.is_stale(r.symbol, now),
            }
        )
    return scanner_data
