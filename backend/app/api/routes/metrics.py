from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import (
    ACTIVE_TRADE_STATUSES,
    SETTLED_TRADE_STATUSES,
    AppConfig,
    EquitySnapshot,
    Trade,
    ensure_utc,
    net_realized_pnl,
)
from app.db.session import get_db
from app.schemas import MetricsResponse
from app.security.auth import get_current_user

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("", response_model=MetricsResponse)
async def get_metrics(db: Session = Depends(get_db), user=Depends(get_current_user)):
    trades = db.query(Trade).all()
    closed = [t for t in trades if t.status in SETTLED_TRADE_STATUSES and t.realized_pnl is not None]
    open_pos = [t for t in trades if t.status in ACTIVE_TRADE_STATUSES]

    realized_pnl = sum((net_realized_pnl(t) for t in closed), Decimal("0"))
    winning = [t for t in closed if net_realized_pnl(t) > Decimal("0")]
    losing = [t for t in closed if net_realized_pnl(t) <= Decimal("0")]

    total = len(closed)
    win_rate = (Decimal(len(winning)) / Decimal(total) * Decimal("100")) if total else Decimal("0")

    first_snapshot = db.query(EquitySnapshot).order_by(EquitySnapshot.captured_at.asc()).first()
    latest_snapshot = db.query(EquitySnapshot).order_by(EquitySnapshot.captured_at.desc()).first()
    if latest_snapshot:
        starting_balance = first_snapshot.wallet_balance if first_snapshot else latest_snapshot.wallet_balance
        current_equity = latest_snapshot.account_equity
        unrealized = latest_snapshot.unrealized_pnl
    else:
        starting_balance = Decimal("1000")
        current_equity = starting_balance + realized_pnl
        unrealized = Decimal("0")

    current_drawdown = Decimal("0")
    if latest_snapshot:
        peak = db.query(EquitySnapshot).order_by(EquitySnapshot.account_equity.desc()).first()
        if peak and peak.account_equity > Decimal("0") and peak.account_equity > current_equity:
            current_drawdown = (peak.account_equity - current_equity) / peak.account_equity * Decimal("100")

    today = datetime.now(timezone.utc).date()
    daily_pnl = Decimal("0")
    for t in closed:
        closed_dt = ensure_utc(t.closed_at)
        if closed_dt and closed_dt.date() == today and t.realized_pnl is not None:
            daily_pnl += net_realized_pnl(t)

    cfg = db.query(AppConfig).first()
    settings = get_settings()
    max_conc = cfg.max_concurrent_trades if cfg else settings.max_concurrent_trades

    return MetricsResponse(
        starting_balance=str(starting_balance),
        current_equity=str(current_equity),
        realized_pnl=str(realized_pnl),
        unrealized_pnl=str(unrealized),
        win_rate=str(win_rate.quantize(Decimal("0.01"))),
        total_trades=total,
        winning_trades=len(winning),
        losing_trades=len(losing),
        open_positions=len(open_pos),
        max_concurrent=max_conc,
        current_drawdown=str(current_drawdown.quantize(Decimal("0.01"))),
        daily_pnl=str(daily_pnl),
    )


@router.get("/equity-curve")
async def equity_curve(
    db: Session = Depends(get_db),
    limit: int = Query(100, ge=1, le=2000),
    user=Depends(get_current_user),
):
    # Take the MOST RECENT `limit` snapshots, then return them oldest-first so the
    # chart shows the current tail of the curve. Ordering ascending before LIMIT
    # froze the chart on the first `limit` snapshots forever.
    snapshots = (
        db.query(EquitySnapshot)
        .order_by(EquitySnapshot.captured_at.desc())
        .limit(limit)
        .all()
    )
    snapshots.reverse()
    return [
        {
            "captured_at": s.captured_at.isoformat(),
            "wallet_balance": str(s.wallet_balance),
            "account_equity": str(s.account_equity),
            "unrealized_pnl": str(s.unrealized_pnl),
        }
        for s in snapshots
    ]


@router.get("/performance")
async def performance_by_symbol(db: Session = Depends(get_db), user=Depends(get_current_user)):
    trades = db.query(Trade).filter(Trade.status.in_(SETTLED_TRADE_STATUSES)).all()
    by_symbol = defaultdict(list)
    for t in trades:
        by_symbol[t.symbol].append(t)
    result = {}
    for sym, lst in by_symbol.items():
        # Net of fees and funding, matching /api/metrics win/loss accounting.
        pnls = [net_realized_pnl(t) for t in lst if t.realized_pnl is not None]
        wins = len([p for p in pnls if p > Decimal("0")])
        result[sym] = {
            "trades": len(lst),
            "pnl": str(sum(pnls, Decimal("0"))),
            "wins": wins,
            "losses": len(pnls) - wins,
        }
    return result
