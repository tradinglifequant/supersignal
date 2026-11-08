from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from app.db.session import get_db
from app.db.models import Trade, Order, AgentLog, SystemLog
from app.schemas import TradeResponse, OrderResponse, AgentLogResponse, SystemLogResponse
from app.security.auth import get_current_user_optional

router = APIRouter(tags=["trading"])

@router.get("/positions", response_model=List[TradeResponse])
async def list_positions(status: Optional[str] = Query("OPEN"), db: Session = Depends(get_db), user=Depends(get_current_user_optional)):
    # Open positions = OPEN, PROTECTED
    if status == "OPEN":
        q = db.query(Trade).filter(Trade.status.in_(["OPEN", "PROTECTED", "PENDING"])).order_by(Trade.created_at.desc())
    elif status:
        q = db.query(Trade).filter(Trade.status == status).order_by(Trade.created_at.desc())
    else:
        q = db.query(Trade).order_by(Trade.created_at.desc())
    rows = q.all()
    return [_to_trade_resp(r) for r in rows]

@router.get("/trades", response_model=List[TradeResponse])
async def list_trades(
    symbol: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    user=Depends(get_current_user_optional),
):
    q = db.query(Trade).order_by(Trade.created_at.desc())
    if symbol:
        q = q.filter(Trade.symbol == symbol)
    if status:
        q = q.filter(Trade.status == status)
    rows = q.limit(limit).all()
    return [_to_trade_resp(r) for r in rows]

@router.get("/trades/{trade_id}", response_model=TradeResponse)
async def get_trade(trade_id: str, db: Session = Depends(get_db), user=Depends(get_current_user_optional)):
    t = db.query(Trade).filter(Trade.id == trade_id).first()
    if not t:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Trade not found")
    return _to_trade_resp(t)

@router.get("/trades/{trade_id}/orders", response_model=List[OrderResponse])
async def get_orders_for_trade(trade_id: str, db: Session = Depends(get_db), user=Depends(get_current_user_optional)):
    rows = db.query(Order).filter(Order.trade_id == trade_id).order_by(Order.submitted_at).all()
    return [_to_order_resp(r) for r in rows]

@router.get("/orders", response_model=List[OrderResponse])
async def list_orders(symbol: Optional[str] = Query(None), db: Session = Depends(get_db), user=Depends(get_current_user_optional)):
    q = db.query(Order).order_by(Order.submitted_at.desc())
    if symbol:
        q = q.filter(Order.symbol == symbol)
    return [_to_order_resp(r) for r in q.limit(100).all()]

@router.get("/logs", response_model=List[SystemLogResponse])
async def list_logs(level: Optional[str] = Query(None), limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db), user=Depends(get_current_user_optional)):
    q = db.query(SystemLog).order_by(SystemLog.created_at.desc())
    if level:
        q = q.filter(SystemLog.level == level)
    rows = q.limit(limit).all()
    return [SystemLogResponse(id=r.id, level=r.level, event_code=r.event_code, message_redacted=r.message_redacted, correlation_id=r.correlation_id, trade_id=r.trade_id, symbol=r.symbol, created_at=r.created_at) for r in rows]

@router.get("/agent-logs", response_model=List[AgentLogResponse])
async def list_agent_logs(candidate_id: Optional[str] = Query(None), limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db), user=Depends(get_current_user_optional)):
    q = db.query(AgentLog).order_by(AgentLog.created_at.desc())
    if candidate_id:
        q = q.filter(AgentLog.candidate_id == candidate_id)
    rows = q.limit(limit).all()
    return [AgentLogResponse(id=r.id, candidate_id=r.candidate_id, agent_name=r.agent_name, provider=r.provider, model_or_agent_id=r.model_or_agent_id, prompt_version=r.prompt_version, schema_version=r.schema_version, response_json=r.response_json, validation_status=r.validation_status, latency_ms=r.latency_ms, error_message=r.error_message, created_at=r.created_at) for r in rows]

def _to_trade_resp(t: Trade) -> TradeResponse:
    return TradeResponse(
        id=t.id, candidate_id=t.candidate_id, symbol=t.symbol, side=t.side, direction=t.direction,
        entry_order_client_id=t.entry_order_client_id, entry_order_id=t.entry_order_id,
        entry_price=str(t.entry_price) if t.entry_price is not None else None,
        exit_price=str(t.exit_price) if t.exit_price is not None else None,
        position_size=str(t.position_size) if t.position_size is not None else None,
        notional=str(t.notional) if t.notional is not None else None,
        margin_allocation=str(t.margin_allocation), leverage=t.leverage,
        take_profit=str(t.take_profit) if t.take_profit else None,
        stop_loss=str(t.stop_loss) if t.stop_loss else None,
        modeled_max_loss=str(t.modeled_max_loss) if t.modeled_max_loss else None,
        realized_pnl=str(t.realized_pnl) if t.realized_pnl is not None else None,
        fees=str(t.fees) if t.fees is not None else None,
        status=t.status, close_reason=t.close_reason,
        created_at=t.created_at, closed_at=t.closed_at,
    )

def _to_order_resp(o: Order) -> OrderResponse:
    return OrderResponse(
        id=o.id, trade_id=o.trade_id, client_order_id=o.client_order_id, exchange_order_id=o.exchange_order_id,
        symbol=o.symbol, order_type=o.order_type, side=o.side, reduce_only=o.reduce_only,
        quantity=str(o.quantity), price=str(o.price) if o.price else None, trigger_price=str(o.trigger_price) if o.trigger_price else None,
        status=o.status, submitted_at=o.submitted_at, updated_at=o.updated_at,
    )
