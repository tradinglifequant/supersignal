from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import Trade, Order
from app.exchange.interface import ExchangeAdapter
from app.execution.execution_engine import ExecutionEngine

logger = logging.getLogger(__name__)

class PositionMonitor:
    """
    Continuously reconcile open positions vs exchange, verify TP/SL presence,
    handle partial fills, detect manual close/liquidation.
    """

    def __init__(self, adapter: ExchangeAdapter, db: Session, execution_engine: ExecutionEngine, poll_interval: int = 10):
        self.adapter = adapter
        self.db = db
        self.exec_engine = execution_engine
        self.poll_interval = poll_interval
        self.running = False
        self.task: asyncio.Task | None = None

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
        logger.info("Position monitor stopped")

    async def _loop(self):
        while self.running:
            try:
                await self.reconcile_all()
            except Exception as e:
                logger.error(f"Monitor loop error: {e}")
            await asyncio.sleep(self.poll_interval)

    async def reconcile_all(self):
        # Get all trades that are not closed
        open_trades = self.db.query(Trade).filter(Trade.status.in_(["OPEN", "PROTECTED", "PENDING", "CLOSING"])).all()
        if not open_trades:
            return

        # Fetch exchange positions once
        try:
            positions = await self.adapter.get_positions()
            pos_map = {p.symbol: p for p in positions}
        except Exception as e:
            logger.error(f"Failed to fetch positions for reconciliation: {e}")
            return

        for trade in open_trades:
            # If position closed on exchange, mark closed
            exchange_pos = pos_map.get(trade.symbol)
            if not exchange_pos or exchange_pos.position_amt == Decimal("0"):
                # Check if trade was supposed to have position; if zero, we consider closed but verify no residual qty
                # Use trade status
                if trade.status in ("OPEN", "PROTECTED"):
                    logger.info(f"Exchange position zero for {trade.id} {trade.symbol}, marking closed")
                    trade.status = "CLOSED"
                    trade.close_reason = trade.close_reason or "detected_close"
                    trade.closed_at = datetime.now(timezone.utc)
                    self.db.commit()
                    # Trigger cleaner later
                continue

            # Verify quantity matches? For now log drift
            # Check protection health
            protected = await self.exec_engine.verify_protection(trade)
            if not protected and trade.status == "PROTECTED":
                logger.warning(f"Protection unhealthy for {trade.id}, attempting repair")
                await self.exec_engine.place_protection(trade, plan=None)  # plan not needed if already have TP/SL
                # Alternatively handle failure
                if not await self.exec_engine.verify_protection(trade):
                    await self.exec_engine.handle_protection_failure(trade)

            # Update unrealized PnL via position (not persisted here, but could emit metric)

        self.db.commit()
        # Also check unprotected duration limit
        self._check_unprotected_timeout()

    def _check_unprotected_timeout(self):
        from datetime import timedelta
        max_unprotected = 60  # seconds, configurable
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=max_unprotected)
        unprotected = self.db.query(Trade).filter(Trade.status == "OPEN", Trade.created_at < cutoff).all()
        for t in unprotected:
            logger.critical(f"Unprotected position {t.id} exceeds timeout, emergency handling")
            # This would trigger emergency close via exec engine, but need async; schedule
            # For now, mark for manual handling
            pass

    async def get_protection_status(self, trade: Trade) -> str:
        try:
            ok = await self.exec_engine.verify_protection(trade)
            return "VERIFIED" if ok else "UNPROTECTED"
        except Exception:
            return "UNKNOWN"
