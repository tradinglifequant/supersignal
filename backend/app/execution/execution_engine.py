from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import logging
from typing import Optional
import uuid

import httpx
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import (
    ACTIVE_TRADE_STATUSES,
    SETTLED_TRADE_STATUSES,
    AppConfig,
    Order,
    SignalCandidate,
    Trade,
    ensure_utc,
)
from app.exchange.binance_adapter import BinanceAPIError
from app.exchange.interface import ExchangeAdapter
from app.exchange.mock_adapter import OrderNotFoundError
from app.risk.risk_engine import PositionPlan, RiskEngine

logger = logging.getLogger(__name__)


def generate_client_order_id(trade_id: str, suffix: str = "ENTRY") -> str:
    base = trade_id.replace("-", "")[:20]
    return f"x-{base}-{suffix[:8]}".lower()[:36]


def _is_order_absent_error(exc: Exception) -> bool:
    if isinstance(exc, BinanceAPIError):
        return exc.is_order_not_found()
    if isinstance(exc, OrderNotFoundError):
        return True
    if isinstance(exc, (httpx.RequestError, asyncio.TimeoutError, TimeoutError, ConnectionError)):
        return False
    msg = str(exc).lower()
    return "not found" in msg or "does not exist" in msg


class ExecutionEngine:
    """
    Implements FR-05 and FR-06: idempotent market entry, retry only when order is confirmed absent,
    reconcile fills, TP/SL placement and verification, bounded repair, and emergency close.
    """

    def __init__(self, adapter: ExchangeAdapter, risk_engine: RiskEngine, db: Session, settings: Settings):
        self.adapter = adapter
        self.risk = risk_engine
        self.db = db
        self.settings = settings

    def _max_concurrent_trades(self) -> int:
        cfg = self.db.query(AppConfig).first()
        return cfg.max_concurrent_trades if cfg else self.settings.max_concurrent_trades

    def _protection_deadline(self) -> int:
        cfg = self.db.query(AppConfig).first()
        return cfg.protection_deadline_seconds if cfg else self.settings.protection_deadline_seconds

    async def execute_entry(
        self,
        candidate: SignalCandidate,
        plan: PositionPlan,
        symbol: str,
        direction: str,
    ) -> Optional[Trade]:
        now = datetime.now(timezone.utc)
        exp = ensure_utc(candidate.expires_at)
        if exp is not None and exp <= now:
            logger.warning("Candidate %s expired, not executing", candidate.id)
            return None

        # Check local DB for existing active position on symbol
        local_active = (
            self.db.query(Trade)
            .filter(Trade.status.in_(ACTIVE_TRADE_STATUSES))
            .all()
        )
        if any(t.symbol == symbol for t in local_active):
            logger.info("Symbol %s already has open local position, blocking duplicate", symbol)
            return None

        # Authoritative exchange check before submission (fail closed on uncertainty)
        try:
            ex_positions = await self.adapter.get_positions()
        except Exception as e:
            logger.error("Cannot verify exchange positions before entry for %s: %s", symbol, e)
            return None

        ex_open_symbols = {p.symbol for p in ex_positions if p.position_amt != Decimal("0")}
        if symbol in ex_open_symbols:
            logger.info("Symbol %s already has open exchange position, blocking duplicate", symbol)
            return None

        combined_open_symbols = {t.symbol for t in local_active} | ex_open_symbols
        if len(combined_open_symbols) >= self._max_concurrent_trades():
            logger.info("Max concurrent positions reached (%d), blocking %s", len(combined_open_symbols), symbol)
            return None

        trade_id = str(uuid.uuid4())
        client_oid = generate_client_order_id(trade_id, "ENTRY")
        existing = self.db.query(Trade).filter(Trade.entry_order_client_id == client_oid).first()
        if existing:
            logger.warning("Duplicate clientOrderId %s exists", client_oid)
            return existing

        side = "BUY" if direction == "LONG" else "SELL"
        trade = Trade(
            id=trade_id,
            candidate_id=candidate.id,
            symbol=symbol,
            side=side,
            direction=direction,
            entry_order_client_id=client_oid,
            entry_price=plan.entry_price,
            position_size=plan.quantity,
            notional=plan.notional,
            margin_allocation=plan.allocated_margin,
            leverage=plan.leverage,
            take_profit=plan.take_profit,
            stop_loss=plan.stop_loss,
            modeled_max_loss=plan.modeled_loss,
            status="PENDING",
            created_at=now,
        )
        self.db.add(trade)
        self.db.commit()
        logger.info("Created TradeIntent %s %s %s qty=%s clientOid=%s", trade_id, symbol, direction, plan.quantity, client_oid)

        order_result = await self._submit_with_idempotency(trade, symbol, side, plan.quantity, client_oid)
        if not order_result:
            trade.status = "FAILED"
            trade.close_reason = trade.close_reason or "entry_submission_failed"
            self.db.commit()
            logger.error("Entry failed for %s", trade_id)
            return None

        # Reconcile fill status - never assume REST ack equals fill
        if order_result.status == "NEW" and order_result.executed_qty <= Decimal("0"):
            for _ in range(2):
                await asyncio.sleep(0.25)
                try:
                    order_result = await self.adapter.query_order(symbol=symbol, client_order_id=client_oid)
                    if order_result.executed_qty > Decimal("0") or order_result.status in ("FILLED", "CANCELED", "REJECTED", "EXPIRED"):
                        break
                except Exception as e:
                    logger.warning("Fill reconciliation query failed for %s: %s", trade_id, e)
                    break

        if order_result.executed_qty <= Decimal("0"):
            trade.status = "FAILED"
            trade.close_reason = f"entry_unfilled_{order_result.status.lower()}"
            self.db.commit()
            logger.error("Entry order %s ended without fill (status=%s)", client_oid, order_result.status)
            return None

        executed_qty = order_result.executed_qty
        avg_price = order_result.avg_price if (order_result.avg_price and order_result.avg_price > Decimal("0")) else plan.entry_price
        trade.entry_order_id = str(order_result.order_id)
        trade.entry_price = avg_price
        trade.position_size = executed_qty
        trade.notional = executed_qty * avg_price
        trade.status = "OPEN"
        self.db.commit()

        order_rec = Order(
            id=str(uuid.uuid4()),
            trade_id=trade.id,
            client_order_id=client_oid,
            exchange_order_id=str(order_result.order_id),
            symbol=symbol,
            order_type="MARKET",
            side=side,
            reduce_only=False,
            quantity=executed_qty,
            price=avg_price,
            trigger_price=None,
            status=order_result.status,
        )
        self.db.add(order_rec)
        self.db.commit()

        protected = await self.place_protection(trade, plan)
        if protected:
            trade.status = "PROTECTED"
            self.db.commit()
            logger.info("Trade %s protected", trade_id)
        else:
            logger.warning("Protection failed for %s, invoking repair/emergency policy", trade_id)
            await self.handle_protection_failure(trade)

        return trade

    async def _confirm_absent_or_recover(self, symbol: str, client_oid: str):
        """
        Query exchange order by clientOrderId after an ambiguous or retryable error.
        Returns:
          ("found", OrderResultDTO) if order exists on exchange
          ("absent", None) ONLY if exchange explicitly confirms order does not exist and no position opened
          ("ambiguous", None) if query itself failed or position state is uncertain (MUST NOT retry)
        """
        try:
            existing = await self.adapter.query_order(symbol=symbol, client_order_id=client_oid)
            logger.info("Recovered existing order %s status=%s", existing.client_order_id, existing.status)
            return "found", existing
        except Exception as qe:
            if not _is_order_absent_error(qe):
                logger.error("Ambiguous order state for %s (query failed: %s); blocking retry", client_oid, qe)
                return "ambiguous", None

        # Also check position state to ensure fill didn't occur under another state
        try:
            positions = await self.adapter.get_positions()
            if any(p.symbol == symbol and p.position_amt != Decimal("0") for p in positions):
                logger.warning("Position already present on %s after order-not-found; blocking retry", symbol)
                return "ambiguous", None
        except Exception as pe:
            logger.error("Cannot confirm position absence on %s (%s); blocking retry", symbol, pe)
            return "ambiguous", None

        return "absent", None

    async def _submit_with_idempotency(self, trade: Trade, symbol: str, side: str, qty: Decimal, client_oid: str):
        """
        Submit market order with idempotent retry:
        - Maximum 2 retries after initial attempt (3 total attempts).
        - Never retry non-retryable exchange rejections.
        - On timeout/network/transient failure, query by clientOrderId and confirm absence before retry.
        """
        attempts = 0
        max_attempts = 3
        while attempts < max_attempts:
            attempts += 1
            try:
                return await self.adapter.create_order(
                    symbol=symbol,
                    side=side,
                    order_type="MARKET",
                    quantity=qty,
                    client_order_id=client_oid,
                )
            except BinanceAPIError as e:
                if e.is_non_retryable():
                    logger.error("Non-retryable Binance error for %s: %s", trade.id, e.body)
                    trade.close_reason = "exchange_rejected"
                    return None
                if e.is_retryable() or e.status_code in (429, 500, 502, 503, 504) or "timeout" in str(e.body).lower():
                    state, recovered = await self._confirm_absent_or_recover(symbol, client_oid)
                    if state == "found":
                        return recovered
                    if state == "ambiguous" or attempts >= max_attempts:
                        trade.close_reason = "ambiguous_order_state" if state == "ambiguous" else "max_retries_exceeded"
                        return None
                    await asyncio.sleep(0.5 * attempts)
                    continue
                logger.error("Unhandled Binance API error for %s: %s", trade.id, e)
                return None
            except (httpx.TimeoutException, httpx.RequestError, asyncio.TimeoutError, TimeoutError) as e:
                logger.warning("Ambiguous network/timeout on order submit for %s (%s); querying before retry", trade.id, type(e).__name__)
                state, recovered = await self._confirm_absent_or_recover(symbol, client_oid)
                if state == "found":
                    return recovered
                if state == "ambiguous" or attempts >= max_attempts:
                    trade.close_reason = "ambiguous_order_state" if state == "ambiguous" else "max_retries_exceeded"
                    return None
                await asyncio.sleep(0.5 * attempts)
                continue
            except Exception as e:
                logger.error("Unexpected error on order submit %s: %s", trade.id, e)
                state, recovered = await self._confirm_absent_or_recover(symbol, client_oid)
                if state == "found":
                    return recovered
                trade.close_reason = "unexpected_submission_error"
                return None
        return None

    async def place_protection(
        self,
        trade: Trade,
        plan: Optional[PositionPlan] = None,
        repair_attempt: int = 0,
    ) -> bool:
        """
        Place missing TP/SL using exchange-supported reduce-only conditional market orders,
        then verify presence on the exchange.
        """
        symbol = trade.symbol
        side = "SELL" if trade.direction == "LONG" else "BUY"
        tp_price = trade.take_profit
        sl_price = trade.stop_loss
        qty = trade.position_size if (trade.position_size is not None and trade.position_size > Decimal("0")) else (
            plan.quantity if plan else Decimal("0")
        )
        if not sl_price or qty <= Decimal("0"):
            logger.error("Invalid SL (%s) or position quantity (%s) for %s", sl_price, qty, trade.id)
            return False

        try:
            open_orders = await self.adapter.get_open_orders(symbol=symbol)
        except Exception as e:
            logger.error("Cannot inspect open orders before placing protection for %s: %s", trade.id, e)
            open_orders = []

        sl_prefix = generate_client_order_id(trade.id, "SL")[:25]
        tp_prefix = generate_client_order_id(trade.id, "TP")[:25]
        has_live_sl = any(o.client_order_id.startswith(sl_prefix) for o in open_orders)
        has_live_tp = any(o.client_order_id.startswith(tp_prefix) for o in open_orders)

        sl_suffix = "SL" if repair_attempt == 0 else f"SLR{repair_attempt}"
        tp_suffix = "TP" if repair_attempt == 0 else f"TPR{repair_attempt}"

        success = True
        if not has_live_sl:
            sl_cid = generate_client_order_id(trade.id, sl_suffix)
            existing_sl = self.db.query(Order).filter(Order.client_order_id == sl_cid).first()
            if not existing_sl:
                try:
                    sl_result = await self.adapter.create_order(
                        symbol=symbol,
                        side=side,
                        order_type="STOP_MARKET",
                        quantity=qty,
                        stop_price=sl_price,
                        client_order_id=sl_cid,
                        reduce_only=True,
                        close_position=False,
                        working_type="MARK_PRICE",
                    )
                    self.db.add(
                        Order(
                            id=str(uuid.uuid4()),
                            trade_id=trade.id,
                            client_order_id=sl_cid,
                            exchange_order_id=str(sl_result.order_id),
                            symbol=symbol,
                            order_type="STOP_MARKET",
                            side=side,
                            reduce_only=True,
                            quantity=sl_result.orig_qty,
                            trigger_price=sl_price,
                            status=sl_result.status,
                        )
                    )
                    self.db.commit()
                except Exception as e:
                    logger.error("Failed to place SL for %s: %s", trade.id, e)
                    success = False

        if tp_price and not has_live_tp:
            tp_cid = generate_client_order_id(trade.id, tp_suffix)
            existing_tp = self.db.query(Order).filter(Order.client_order_id == tp_cid).first()
            if not existing_tp:
                try:
                    tp_result = await self.adapter.create_order(
                        symbol=symbol,
                        side=side,
                        order_type="TAKE_PROFIT_MARKET",
                        quantity=qty,
                        stop_price=tp_price,
                        client_order_id=tp_cid,
                        reduce_only=True,
                        close_position=False,
                        working_type="MARK_PRICE",
                    )
                    self.db.add(
                        Order(
                            id=str(uuid.uuid4()),
                            trade_id=trade.id,
                            client_order_id=tp_cid,
                            exchange_order_id=str(tp_result.order_id),
                            symbol=symbol,
                            order_type="TAKE_PROFIT_MARKET",
                            side=side,
                            reduce_only=True,
                            quantity=tp_result.orig_qty,
                            trigger_price=tp_price,
                            status=tp_result.status,
                        )
                    )
                    self.db.commit()
                except Exception as e:
                    logger.error("Failed to place TP for %s: %s", trade.id, e)
                    success = False

        verified = await self.verify_protection(trade)
        return verified and success

    async def verify_protection(self, trade: Trade) -> bool:
        """
        Verify required protective orders are accepted and currently open on the exchange.
        """
        try:
            open_orders = await self.adapter.get_open_orders(symbol=trade.symbol)
        except Exception as e:
            logger.error("Failed to verify protection for %s: %s", trade.id, e)
            return False

        sl_prefix = generate_client_order_id(trade.id, "SL")[:25]
        has_sl = any(
            o.client_order_id.startswith(sl_prefix) and o.status in ("NEW", "PARTIALLY_FILLED")
            for o in open_orders
        )
        if not has_sl:
            logger.warning("SL protection missing for %s", trade.id)
            return False

        if trade.take_profit:
            tp_prefix = generate_client_order_id(trade.id, "TP")[:25]
            has_tp = any(
                o.client_order_id.startswith(tp_prefix) and o.status in ("NEW", "PARTIALLY_FILLED")
                for o in open_orders
            )
            if not has_tp:
                logger.warning("TP protection missing for %s", trade.id)
                return False

        return True

    async def handle_protection_failure(self, trade: Trade):
        """
        Execute bounded repair attempt; if protection still cannot be verified within deadline,
        flatten position using reduce-only emergency close.
        """
        deadline = self._protection_deadline()
        await asyncio.sleep(min(1.0, max(0.1, deadline / 4)))
        repaired = await self.place_protection(trade, plan=None, repair_attempt=1)
        if repaired and await self.verify_protection(trade):
            trade.status = "PROTECTED"
            self.db.commit()
            logger.info("Protection repaired for %s", trade.id)
            return

        logger.critical("Protection cannot be established for %s within %ss; emergency closing", trade.id, deadline)
        await self.emergency_close(trade, reason="protection_failed")

    async def emergency_close(self, trade: Trade, reason: str = "emergency"):
        """
        Reduce or close position using reduceOnly market order.
        Never create reverse/increasing position as fallback.
        """
        symbol = trade.symbol
        try:
            positions = await self.adapter.get_positions()
            pos = next((p for p in positions if p.symbol == symbol), None)
            if not pos or pos.position_amt == Decimal("0"):
                logger.info("No open position for emergency close %s %s", trade.id, symbol)
                trade.status = "CLOSED"
                trade.close_reason = "already_closed"
                trade.closed_at = datetime.now(timezone.utc)
                self.db.commit()
                return
            qty = abs(pos.position_amt)
            side = "SELL" if pos.position_amt > 0 else "BUY"
            cid = generate_client_order_id(trade.id, "EMRG")
            result = await self.adapter.create_order(
                symbol=symbol,
                side=side,
                order_type="MARKET",
                quantity=qty,
                client_order_id=cid,
                reduce_only=True,
            )
            if result.avg_price and result.avg_price > Decimal("0"):
                trade.exit_price = result.avg_price
                if trade.entry_price:
                    pnl_sign = Decimal("1") if trade.direction == "LONG" else Decimal("-1")
                    trade.realized_pnl = (result.avg_price - trade.entry_price) * qty * pnl_sign - (trade.fees or Decimal("0"))
            trade.status = "EMERGENCY_CLOSED"
            trade.close_reason = reason
            trade.closed_at = datetime.now(timezone.utc)
            self.db.commit()
            logger.info("Emergency close executed %s qty=%s side=%s result=%s", trade.id, qty, side, result.status)
        except Exception as e:
            logger.error("Emergency close failed for %s: %s", trade.id, e)
            trade.close_reason = f"emergency_failed:{type(e).__name__}"
            self.db.commit()

    async def reconcile_trade(self, trade: Trade):
        try:
            positions = await self.adapter.get_positions()
            pos = next((p for p in positions if p.symbol == trade.symbol), None)
            if not pos or pos.position_amt == Decimal("0"):
                if trade.status not in (*SETTLED_TRADE_STATUSES, "FAILED"):
                    trade.status = "CLOSED"
                    trade.close_reason = trade.close_reason or "exchange_closed"
                    trade.closed_at = datetime.now(timezone.utc)
                    self.db.commit()
                    logger.info("Reconciled closed trade %s", trade.id)
        except Exception as e:
            logger.error("Reconcile error %s: %s", trade.id, e)
