from __future__ import annotations

import logging
from sqlalchemy.orm import Session

from app.db.models import SETTLED_TRADE_STATUSES, Order, Trade
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
        symbol = trade.symbol
        sl_prefix = generate_client_order_id(trade.id, "SL")[:25]
        tp_prefix = generate_client_order_id(trade.id, "TP")[:25]
        expected_cids = {
            generate_client_order_id(trade.id, "TP"),
            generate_client_order_id(trade.id, "SL"),
        }
        db_orders = (
            self.db.query(Order)
            .filter(Order.trade_id == trade.id, Order.status.in_(["NEW", "PARTIALLY_FILLED"]))
            .all()
        )
        for o in db_orders:
            expected_cids.add(o.client_order_id)

        try:
            open_orders = await self.adapter.get_open_orders(symbol=symbol)
        except Exception as e:
            logger.error("Cleaner failed to fetch open orders %s: %s", trade.id, e)
            return {"cleaned": 0, "error": str(e), "remaining": []}

        to_cancel = [
            o
            for o in open_orders
            if o.client_order_id in expected_cids
            or o.client_order_id.startswith(sl_prefix)
            or o.client_order_id.startswith(tp_prefix)
        ]
        if not to_cancel:
            logger.info("Cleaner: no residual bot orders for %s", trade.id)
            return {"cleaned": 0, "remaining": []}

        cleaned = 0
        remaining = []
        for o in to_cancel:
            try:
                await self.adapter.cancel_order(symbol=symbol, client_order_id=o.client_order_id)
                cleaned += 1
                db_o = self.db.query(Order).filter(Order.client_order_id == o.client_order_id).first()
                if db_o:
                    db_o.status = "CANCELED"
                logger.info("Cleaner canceled %s for %s", o.client_order_id, trade.id)
            except Exception as e:
                logger.warning("Cleaner failed to cancel %s: %s", o.client_order_id, e)
                remaining.append(o.client_order_id)

        self.db.commit()
        result = {"cleaned": cleaned, "remaining": remaining}
        logger.info("Cleaner result for %s: %s", trade.id, result)
        return result

    async def cleanup_orphaned(self, symbol: str) -> dict:
        closed_trades = (
            self.db.query(Trade)
            .filter(Trade.symbol == symbol, Trade.status.in_(SETTLED_TRADE_STATUSES))
            .all()
        )
        closed_ids = {t.id for t in closed_trades}
        orphan_orders = (
            self.db.query(Order)
            .filter(Order.symbol == symbol, Order.status.in_(["NEW", "PARTIALLY_FILLED"]))
            .all()
        )
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
                        logger.warning("Orphan cleanup failed %s: %s", o.client_order_id, e)
            self.db.commit()
            return {"cleaned": cleaned}
        except Exception as e:
            logger.error("Orphan cleanup error %s: %s", symbol, e)
            return {"cleaned": 0, "error": str(e)}
