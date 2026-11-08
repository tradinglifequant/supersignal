from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import logging
from typing import Callable, Optional
import uuid

from sqlalchemy.orm import Session

from app.db.models import (
    ACTIVE_TRADE_STATUSES,
    AppConfig,
    EquitySnapshot,
    MarginScalingEvent,
    Trade,
    ensure_utc,
    net_realized_pnl,
)
from app.exchange.interface import ExchangeAdapter
from app.execution.execution_engine import ExecutionEngine
from app.monitor.cleaner import OrderCleaner

logger = logging.getLogger(__name__)


class PositionMonitor:
    """
    Continuously reconcile open positions vs exchange, verify TP/SL presence,
    repair or emergency-close unprotected positions, clean residual bot orders on close,
    and capture periodic equity snapshots.
    """

    def __init__(
        self,
        adapter: ExchangeAdapter,
        db: Session,
        execution_engine: ExecutionEngine,
        poll_interval: int = 10,
        session_factory: Optional[Callable[[], Session]] = None,
    ):
        self.adapter = adapter
        self.db = db
        self.exec_engine = execution_engine
        self.cleaner = OrderCleaner(adapter, db)
        self.poll_interval = poll_interval
        self.session_factory = session_factory
        self.running = False
        self.task: asyncio.Task | None = None

    def rebind(self, session: Session) -> None:
        """Point the monitor and its helpers at a shared session (no session factory)."""
        self.db = session
        self.exec_engine.db = session
        self.cleaner.db = session

    async def start(self):
        if self.running:
            return
        self.running = True
        self.task = asyncio.create_task(self._loop())
        logger.info("Position monitor started")

    async def stop(self):
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None
        logger.info("Position monitor stopped")

    async def _loop(self):
        while self.running:
            session: Session | None = None
            try:
                if self.session_factory is not None:
                    # Use helpers that are private to this iteration. Rebinding the
                    # shared EngineService ExecutionEngine here let a concurrent
                    # price tick swap self.exec_engine.db underneath an in-flight
                    # reconciliation, so protection-repair commits could be written
                    # to a session that did not own the loaded Trade objects.
                    session = self.session_factory()
                    exec_engine = ExecutionEngine(
                        self.adapter, self.exec_engine.risk, session, self.exec_engine.settings
                    )
                    cleaner = OrderCleaner(self.adapter, session)
                    await self.reconcile_all(db=session, exec_engine=exec_engine, cleaner=cleaner)
                else:
                    await self.reconcile_all()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Monitor loop error: %s", e)
            finally:
                if session is not None:
                    session.close()
            await asyncio.sleep(self.poll_interval)

    async def capture_equity_snapshot(self, db: Session | None = None):
        db = db if db is not None else self.db
        try:
            balances = await self.adapter.get_balances()
            usdt = next((b for b in balances if b.asset == "USDT"), None)
            if usdt:
                equity = usdt.balance + usdt.cross_unrealized
                snap = EquitySnapshot(
                    id=str(uuid.uuid4()),
                    wallet_balance=usdt.balance,
                    account_equity=equity,
                    available_balance=usdt.available,
                    unrealized_pnl=usdt.cross_unrealized,
                    captured_at=datetime.now(timezone.utc),
                )
                db.add(snap)
                db.commit()
        except Exception as e:
            logger.debug("Equity snapshot skipped: %s", e)

    def _record_margin_scaling_if_needed(self, trade: Trade, db: Session | None = None, exec_engine=None):
        db = db if db is not None else self.db
        exec_engine = exec_engine if exec_engine is not None else self.exec_engine
        if trade.realized_pnl is None:
            return
        existing = (
            db.query(MarginScalingEvent)
            .filter(MarginScalingEvent.closed_trade_id == trade.id)
            .first()
        )
        if existing:
            return
        cfg = db.query(AppConfig).first()
        base_margin = cfg.base_margin if cfg else exec_engine.settings.base_margin
        reinvest_pct = cfg.profit_reinvestment_pct if cfg else exec_engine.settings.profit_reinvestment_pct
        max_alloc = cfg.max_trade_allocation if cfg else exec_engine.settings.max_trade_allocation
        net_profit = net_realized_pnl(trade)
        next_margin = exec_engine.risk.calculate_next_margin(
            base_margin,
            net_profit,
            reinvest_pct=reinvest_pct,
            max_allocation=max_alloc,
        )
        db.add(
            MarginScalingEvent(
                id=str(uuid.uuid4()),
                closed_trade_id=trade.id,
                base_margin=base_margin,
                realized_net_profit=net_profit,
                reinvestment_pct=reinvest_pct,
                next_margin=next_margin,
                created_at=datetime.now(timezone.utc),
            )
        )
        db.commit()

    async def reconcile_all(
        self,
        db: Session | None = None,
        exec_engine: ExecutionEngine | None = None,
        cleaner: OrderCleaner | None = None,
    ):
        db = db if db is not None else self.db
        exec_engine = exec_engine if exec_engine is not None else self.exec_engine
        cleaner = cleaner if cleaner is not None else self.cleaner

        await self.capture_equity_snapshot(db=db)
        open_trades = db.query(Trade).filter(Trade.status.in_(ACTIVE_TRADE_STATUSES)).all()
        if not open_trades:
            return

        try:
            positions = await self.adapter.get_positions()
            pos_map = {p.symbol: p for p in positions}
        except Exception as e:
            logger.error("Failed to fetch positions for reconciliation: %s", e)
            return

        for trade in open_trades:
            exchange_pos = pos_map.get(trade.symbol)
            if not exchange_pos or exchange_pos.position_amt == Decimal("0"):
                if trade.status in ("OPEN", "PROTECTED", "CLOSING"):
                    logger.info("Exchange position zero for %s %s, marking closed and cleaning orders", trade.id, trade.symbol)
                    trade.status = "CLOSED"
                    trade.close_reason = trade.close_reason or "detected_close"
                    trade.closed_at = datetime.now(timezone.utc)
                    db.commit()
                    await cleaner.cleanup_after_close(trade)
                    self._record_margin_scaling_if_needed(trade, db=db, exec_engine=exec_engine)
                continue

            protected = await exec_engine.verify_protection(trade)
            if not protected and trade.status == "PROTECTED":
                logger.warning("Protection unhealthy for %s, attempting repair", trade.id)
                await exec_engine.handle_protection_failure(trade)

        db.commit()
        await self._check_unprotected_timeout(db=db, exec_engine=exec_engine)

    async def _check_unprotected_timeout(self, db: Session | None = None, exec_engine=None):
        db = db if db is not None else self.db
        exec_engine = exec_engine if exec_engine is not None else self.exec_engine
        cfg = db.query(AppConfig).first()
        deadline_secs = cfg.protection_deadline_seconds if cfg else exec_engine.settings.protection_deadline_seconds
        max_unprotected = max(deadline_secs, 10)
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=max_unprotected)
        open_unprotected = db.query(Trade).filter(Trade.status == "OPEN").all()
        for t in open_unprotected:
            created = ensure_utc(t.created_at)
            if created and created < cutoff:
                logger.critical("Unprotected position %s exceeds timeout (%ds); invoking emergency policy", t.id, max_unprotected)
                await exec_engine.handle_protection_failure(t)

    async def get_protection_status(self, trade: Trade) -> str:
        try:
            ok = await self.exec_engine.verify_protection(trade)
            return "VERIFIED" if ok else "UNPROTECTED"
        except Exception:
            return "UNKNOWN"
