from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from decimal import Decimal
from datetime import datetime, timezone

from app.db.session import get_db
from app.db.models import Trade, EquitySnapshot
from app.schemas import MetricsResponse
from app.security.auth import get_current_user_optional
from app.core.config import get_settings

router = APIRouter(prefix="/metrics", tags=["metrics"])

@router.get("", response_model=MetricsResponse)
async def get_metrics(db: Session = Depends(get_db), user=Depends(get_current_user_optional)):
    # Compute KPIs from persisted trades
    trades = db.query(Trade).all()
    closed = [t for t in trades if t.status in ("CLOSED", "EMERGENCY_CLOSED") and t.realized_pnl is not None]
    open_pos = [t for t in trades if t.status in ("OPEN", "PROTECTED", "PENDING")]

    realized_pnl = sum((t.realized_pnl for t in closed), Decimal("0"))
    winning = [t for t in closed if t.realized_pnl and t.realized_pnl > Decimal("0")]
    losing = [t for t in closed if t.realized_pnl and t.realized_pnl <= Decimal("0")]

    total = len(closed)
    win_rate = (Decimal(len(winning)) / Decimal(total) * Decimal("100")) if total else Decimal("0")

    # Equity snapshots: latest
    latest_snapshot = db.query(EquitySnapshot).order_by(EquitySnapshot.captured_at.desc()).first()
    if latest_snapshot:
        current_equity = latest_snapshot.account_equity
        unrealized = latest_snapshot.unrealized_pnl
        wallet = latest_snapshot.wallet_balance
    else:
        # Mock starting balance 1000
        wallet = Decimal("1000")
        current_equity = wallet + realized_pnl
        unrealized = Decimal("0")

    # Drawdown simple: max decline from peak (not fully implemented)
    current_drawdown = Decimal("0")
    if latest_snapshot and latest_snapshot.wallet_balance != Decimal("0"):
        peak = db.query(EquitySnapshot).order_by(EquitySnapshot.account_equity.desc()).first()
        if peak and peak.account_equity > current_equity:
            current_drawdown = (peak.account_equity - current_equity) / peak.account_equity * Decimal("100")

    # Daily PnL: trades closed today
    today = datetime.now(timezone.utc).date()
    daily_pnl = sum((t.realized_pnl for t in closed if t.closed_at and t.closed_at.date() == today), Decimal("0"))

    settings = get_settings()
    return MetricsResponse(
        starting_balance=str(wallet),
        current_equity=str(current_equity),
        realized_pnl=str(realized_pnl),
        unrealized_pnl=str(unrealized),
        win_rate=str(win_rate.quantize(Decimal("0.01"))),
        total_trades=total,
        winning_trades=len(winning),
        losing_trades=len(losing),
        open_positions=len(open_pos),
        max_concurrent=settings.max_concurrent_trades,
        current_drawdown=str(current_drawdown),
        daily_pnl=str(daily_pnl),
    )

@router.get("/equity-curve")
async def equity_curve(db: Session = Depends(get_db), limit: int = 100, user=Depends(get_current_user_optional)):
    snapshots = db.query(EquitySnapshot).order_by(EquitySnapshot.captured_at.asc()).limit(limit).all()
    return [{"captured_at": s.captured_at.isoformat(), "wallet_balance": str(s.wallet_balance), "account_equity": str(s.account_equity), "unrealized_pnl": str(s.unrealized_pnl)} for s in snapshots]

@router.get("/performance")
async def performance_by_symbol(db: Session = Depends(get_db), user=Depends(get_current_user_optional)):
    from collections import defaultdict
    trades = db.query(Trade).filter(Trade.status.in_(["CLOSED", "EMERGENCY_CLOSED"])).all()
    by_symbol = defaultdict(list)
    for t in trades:
        by_symbol[t.symbol].append(t)
    result = {}
    for sym, lst in by_symbol.items():
        pnl = sum((t.realized_pnl for t in lst if t.realized_pnl), Decimal("0"))
        wins = len([t for t in lst if t.realized_pnl and t.realized_pnl > 0])
        result[sym] = {"trades": len(lst), "pnl": str(pnl), "wins": wins, "losses": len(lst)-wins}
    return result
