from __future__ import annotations

import logging
from typing import List
from decimal import Decimal
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models import Trade, Order
from app.exchange.interface import ExchangeAdapter
from app.execution.execution_engine import generate_client_order_id

logger = logging.getLogger(__name__)

class OrderCleaner:
    """
    After position close, cancel only bot-owned residual orders identified by client IDs and trade ownership.
    Never mass-cancel all symbol orders by default.
    """

    def __init__(self, adapter: ExchangeAdapter, db: Session):
        self.adapter = adapter
        self.db = db

    async def cleanup_after_close(self, trade: Trade) -> dict:
        """
        Trigger only after exchange confirms position quantity is zero or closed.
        Cancel bot-owned residual orders for that trade/symbol.
        """
        symbol = trade.symbol
        # Generate expected client IDs for this trade
        expected_cids = {
            generate_client_order_id(trade.id, "TP"),
            generate_client_order_id(trade.id, "SL"),
        }
        # Also check DB orders for this trade
        db_orders = self.db.query(Order).filter(Order.trade_id == trade.id, Order.status.in_(["NEW", "PARTIALLY_FILLED"])).all()
        for o in db_orders:
            expected_cids.add(o.client_order_id)

        # Fetch open orders for symbol from exchange
        try:
            open_orders = await self.adapter.get_open_orders(symbol=symbol)
        except Exception as e:
            logger.error(f"Cleaner failed to fetch open orders {trade.id}: {e}")
            return {"cleaned": 0, "error": str(e), "remaining": []}

        to_cancel = [o for o in open_orders if o.client_order_id in expected_cids]
        if not to_cancel:
            logger.info(f"Cleaner: no residual bot orders for {trade.id}")
            return {"cleaned": 0, "remaining": []}

        cleaned = 0
        remaining = []
        for o in to_cancel:
            try:
                await self.adapter.cancel_order(symbol=symbol, client_order_id=o.client_order_id)
                cleaned += 1
                # Update DB order status
                db_o = self.db.query(Order).filter(Order.client_order_id == o.client_order_id).first()
                if db_o:
                    db_o.status = "CANCELED"
                logger.info(f"Cleaner canceled {o.client_order_id} for {trade.id}")
            except Exception as e:
                logger.warning(f"Cleaner failed to cancel {o.client_order_id}: {e}")
                remaining.append(o.client_order_id)

        self.db.commit()
        result = {"cleaned": cleaned, "remaining": remaining}
        logger.info(f"Cleaner result for {trade.id}: {result}")
        return result

    async def cleanup_orphaned(self, symbol: str) -> dict:
        """
        Cleanup any orphaned bot orders where trade is already closed.
        """
        closed_trades = self.db.query(Trade).filter(Trade.symbol == symbol, Trade.status.in_(["CLOSED", "EMERGENCY_CLOSED"])).all()
        closed_ids = {t.id for t in closed_trades}
        orphan_orders = self.db.query(Order).filter(Order.symbol == symbol, Order.status.in_(["NEW", "PARTIALLY_FILLED"])).all()
        # Filter those whose trade is closed
        to_check = [o for o in orphan_orders if o.trade_id in closed_ids]
        if not to_check:
            return {"cleaned": 0}
        try:
            open_orders = await self.adapter.get_open_orders(symbol=symbol)
            open_cids = {o.client_order_id for o in open_orders}
            cleaned = 0
            for o in to_check:
                if o.client_order_id in open_cids:
                    try:
                        await self.adapter.cancel_order(symbol=symbol, client_order_id=o.client_order_id)
                        o.status = "CANCELED"
                        cleaned += 1
                    except Exception as e:
                        logger.warning(f"Orphan cleanup failed {o.client_order_id}: {e}")
            self.db.commit()
            return {"cleaned": cleaned}
        except Exception as e:
            logger.error(f"Orphan cleanup error {symbol}: {e}")
            return {"cleaned": 0, "error": str(e)}
