from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from app.db.session import get_db
from app.db.models import SymbolMetadata, SignalCandidate
from app.schemas import SymbolInfo, SignalCandidateResponse
from app.security.auth import get_current_user_optional
from app.engine.service import EngineService
from app.api.routes.engine import get_engine

router = APIRouter(prefix="/market", tags=["market"])

@router.get("/symbols", response_model=List[SymbolInfo])
async def list_symbols(db: Session = Depends(get_db), user=Depends(get_current_user_optional)):
    rows = db.query(SymbolMetadata).all()
    result = []
    for r in rows:
        result.append(SymbolInfo(
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
        ))
    return result

@router.get("/signals", response_model=List[SignalCandidateResponse])
async def list_signals(
    status: Optional[str] = Query(None),
    symbol: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user=Depends(get_current_user_optional),
):
    q = db.query(SignalCandidate).order_by(SignalCandidate.detected_at.desc())
    if status:
        q = q.filter(SignalCandidate.status == status)
    if symbol:
        q = q.filter(SignalCandidate.symbol == symbol)
    rows = q.limit(limit).all()
    return [
        SignalCandidateResponse(
            id=r.id, event_key=r.event_key, symbol=r.symbol, direction=r.direction,
            current_price=str(r.current_price), reference_price=str(r.reference_price),
            change_pct=str(r.change_pct), window_seconds=r.window_seconds,
            detected_at=r.detected_at, exchange_event_time=r.exchange_event_time,
            expires_at=r.expires_at, status=r.status, rejection_reason=r.rejection_reason,
        ) for r in rows
    ]

@router.get("/scanner")
async def scanner(db: Session = Depends(get_db), engine: EngineService = Depends(get_engine), user=Depends(get_current_user_optional)):
    # Live scanner view: combine symbol metadata + last price + trigger pending
    rows = db.query(SymbolMetadata).filter(SymbolMetadata.is_eligible == True).all()  # noqa: E712
    scanner_data = []
    for r in rows:
        last = engine.price_history.get_last_price(r.symbol) if hasattr(engine, "price_history") else None
        scanner_data.append({
            "symbol": r.symbol,
            "status": r.status,
            "last_price": str(last.price) if last else None,
            "change_pct": None,  # compute on fly via trigger engine evaluate
            "is_eligible": r.is_eligible,
            "fresh": not engine.price_history.is_stale(r.symbol, __import__("datetime").datetime.now(__import__("datetime").timezone.utc)) if hasattr(engine, "price_history") else False,
        })
    return scanner_data
