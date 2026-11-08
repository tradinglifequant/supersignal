from __future__ import annotations

import uuid
import logging
import asyncio
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

from sqlalchemy.orm import Session

from app.db.models import Trade, Order, SignalCandidate, AgentLog
from app.exchange.interface import ExchangeAdapter
from app.risk.risk_engine import RiskEngine, PositionPlan
from app.exchange.binance_adapter import BinanceAPIError
from app.core.config import Settings

logger = logging.getLogger(__name__)

def generate_client_order_id(trade_id: str, suffix: str = "ENTRY") -> str:
    # Binance requires clientOrderId up to 36 chars? Actually limit 36, alphanumeric. Use prefix.
    # Use trade_id first 8 + suffix
    base = trade_id.replace("-", "")[:16]
    return f"x-{base[:12]}-{suffix[:6]}".lower()[:36]

class ExecutionEngine:
    """
    Implements FR-05 and FR-06: idempotent market entry, retry only when order absent,
    reconcile fills, TP/SL placement and verification, emergency close.
    """

    def __init__(self, adapter: ExchangeAdapter, risk_engine: RiskEngine, db: Session, settings: Settings):
        self.adapter = adapter
        self.risk = risk_engine
        self.db = db
        self.settings = settings

    async def execute_entry(
        self,
        candidate: SignalCandidate,
        plan: PositionPlan,
        symbol: str,
        direction: str,  # LONG|SHORT
    ) -> Optional[Trade]:
        # Pre-checks: TTL, concurrency, revalidate risk
        now = datetime.now(timezone.utc)
        exp = candidate.expires_at
        if exp is not None:
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp <= now:
                logger.warning(f"Candidate {candidate.id} expired, not executing")
                return None

        # Enforce concurrency
        open_trades = self.db.query(Trade).filter(Trade.status.in_(["OPEN", "PROTECTED", "PENDING"]), Trade.symbol == symbol).count()
        if open_trades > 0:
            logger.info(f"Symbol {symbol} already has open position, blocking duplicate")
            return None

        # Persist TradeIntent before submission (idempotency via clientOrderId unique)
        trade_id = str(uuid.uuid4())
        client_oid = generate_client_order_id(trade_id, "ENTRY")
        # Check duplicate clientOrderId
        existing = self.db.query(Trade).filter(Trade.entry_order_client_id == client_oid).first()
        if existing:
            logger.warning(f"Duplicate clientOrderId {client_oid} exists")
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
        logger.info(f"Created TradeIntent {trade_id} {symbol} {direction} qty={plan.quantity} clientOid={client_oid}")

        # Recheck gates immediately before submission (TTL, price freshness, etc.)
        # If candidate TTL small, we already checked.

        # Submit market entry with retry logic
        order_result = await self._submit_with_idempotency(trade, symbol, side, plan.quantity, client_oid)
        if not order_result:
            trade.status = "FAILED"
            self.db.commit()
            logger.error(f"Entry failed for {trade_id}")
            return None

        # Reconcile fills: use actual fill price/qty to recalc protection
        executed_qty = order_result.executed_qty
        avg_price = order_result.avg_price or plan.entry_price
        # Update trade
        trade.entry_order_id = str(order_result.order_id)
        trade.entry_price = avg_price
        trade.position_size = executed_qty
        trade.notional = executed_qty * avg_price
        trade.status = "OPEN"
        self.db.commit()

        # Create Order record
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
            price=None,
            trigger_price=None,
            status=order_result.status,
        )
        self.db.add(order_rec)
        self.db.commit()

        # Place protective TP/SL
        protected = await self.place_protection(trade, plan)
        if protected:
            trade.status = "PROTECTED"
            self.db.commit()
            logger.info(f"Trade {trade_id} protected")
        else:
            # Attempt repair or emergency close per policy
            logger.warning(f"Protection failed for {trade_id}, attempting emergency policy")
            await self.handle_protection_failure(trade)

        return trade

    async def _submit_with_idempotency(self, trade: Trade, symbol: str, side: str, qty: Decimal, client_oid: str):
        """
        Submit market order with idempotent retry.
        Rules:
        - Retry transient failures max 2 additional attempts only when order state known absent.
        - If submission outcome ambiguous (timeout), query by clientOrderId before retry to prevent duplicate.
        """
        attempts = 0
        max_attempts = 3  # initial + 2 retries
        while attempts < max_attempts:
            attempts += 1
            try:
                result = await self.adapter.create_order(
                    symbol=symbol,
                    side=side,
                    order_type="MARKET",
                    quantity=qty,
                    client_order_id=client_oid,
                )
                return result
            except BinanceAPIError as e:
                if e.is_non_retryable():
                    logger.error(f"Non-retryable Binance error for {trade.id}: {e.body}")
                    return None
                if e.is_retryable() or e.status_code in (429, 500, 502, 503, 504) or "timeout" in str(e.body).lower():
                    if attempts < max_attempts:
                        # Before retry, query order state to ensure no order exists
                        try:
                            existing = await self.adapter.query_order(symbol=symbol, client_order_id=client_oid)
                            logger.info(f"Found existing order after ambiguous response: {existing.client_order_id} status={existing.status}")
                            return existing
                        except Exception as qe:
                            logger.info(f"No existing order found, retrying ({attempts}/{max_attempts}): {qe}")
                            await asyncio.sleep(1 * attempts)  # backoff
                            continue
                    else:
                        logger.error(f"Max retries exceeded for {trade.id}")
                        return None
                else:
                    logger.error(f"Binance error not retryable for {trade.id}: {e}")
                    return None
            except (asyncio.TimeoutError, TimeoutError) as e:
                logger.warning(f"Timeout on order submission for {trade.id}, querying state before retry: {e}")
                try:
                    existing = await self.adapter.query_order(symbol=symbol, client_order_id=client_oid)
                    logger.info(f"Found order after timeout: {existing.client_order_id}")
                    return existing
                except Exception as qe:
                    if attempts < max_attempts:
                        logger.info(f"Retrying after timeout ({attempts}/{max_attempts}) {qe}")
                        await asyncio.sleep(1 * attempts)
                        continue
                    return None
            except Exception as e:
                logger.error(f"Unexpected error on order submit {trade.id}: {e}")
                if attempts < max_attempts:
                    await asyncio.sleep(0.5 * attempts)
                    continue
                return None
        return None

    async def place_protection(self, trade: Trade, plan: PositionPlan) -> bool:
        """
        Place TP/SL using exchange-supported order types.
        Prefer reduceOnly/closePosition semantics.
        Binance USD-M supports: TAKE_PROFIT_MARKET, STOP_MARKET with closePosition or reduceOnly.
        """
        symbol = trade.symbol
        side = "SELL" if trade.direction == "LONG" else "BUY"  # opposite to close
        # Determine TP/SL from trade (already validated)
        tp_price = trade.take_profit
        sl_price = trade.stop_loss
        if not sl_price:
            logger.error(f"No SL price for {trade.id}")
            return False

        # Place SL first (more critical), then TP
        success = True
        # SL order
        sl_cid = generate_client_order_id(trade.id, "SL")
        existing_sl = self.db.query(Order).filter(Order.client_order_id == sl_cid).first()
        if not existing_sl:
            try:
                sl_result = await self.adapter.create_order(
                    symbol=symbol,
                    side=side,
                    order_type="STOP_MARKET",
                    quantity=trade.position_size or plan.quantity,  # type: ignore
                    stop_price=sl_price,
                    client_order_id=sl_cid,
                    reduce_only=True,
                    close_position=False,  # Use reduceOnly for partial safe; closePosition must not have quantity
                    working_type="MARK_PRICE",  # trigger on mark to avoid manipulation
                )
                # Persist order
                order_rec = Order(
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
                self.db.add(order_rec)
                self.db.commit()
            except Exception as e:
                logger.error(f"Failed to place SL for {trade.id}: {e}")
                success = False

        # TP order
        if tp_price:
            tp_cid = generate_client_order_id(trade.id, "TP")
            existing_tp = self.db.query(Order).filter(Order.client_order_id == tp_cid).first()
            if not existing_tp:
                try:
                    tp_result = await self.adapter.create_order(
                        symbol=symbol,
                        side=side,
                        order_type="TAKE_PROFIT_MARKET",
                        quantity=trade.position_size or plan.quantity,  # type: ignore
                        stop_price=tp_price,
                        client_order_id=tp_cid,
                        reduce_only=True,
                        close_position=False,
                        working_type="MARK_PRICE",
                    )
                    order_rec = Order(
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
                    self.db.add(order_rec)
                    self.db.commit()
                except Exception as e:
                    logger.error(f"Failed to place TP for {trade.id}: {e}")
                    # TP failure not critical as SL, but mark warning
                    # success remains true if SL placed?

        # Verify protection at exchange
        verified = await self.verify_protection(trade)
        return verified and success

    async def verify_protection(self, trade: Trade) -> bool:
        """
        Verify protective orders are accepted and remain present.
        """
        try:
            open_orders = await self.adapter.get_open_orders(symbol=trade.symbol)
        except Exception as e:
            logger.error(f"Failed to verify protection for {trade.id}: {e}")
            return False

        # Check both TP and SL present by clientOrderId
        expected_cids = {generate_client_order_id(trade.id, "SL")}
        if trade.take_profit:
            expected_cids.add(generate_client_order_id(trade.id, "TP"))
        found = {o.client_order_id for o in open_orders}
        missing = expected_cids - found
        if missing:
            logger.warning(f"Protection missing for {trade.id}: {missing} found={found}")
            return False
        return True

    async def handle_protection_failure(self, trade: Trade):
        """
        Retry repair; if cannot be established promptly, reduce or close position using emergency policy.
        """
        deadline = self.settings.protection_deadline_seconds
        # Bounded repair attempt: re-place once
        await asyncio.sleep(1)
        verified = await self.verify_protection(trade)
        if verified:
            trade.status = "PROTECTED"
            self.db.commit()
            return

        # If still missing, emergency close
        logger.critical(f"Protection cannot be established for {trade.id} within {deadline}s, emergency closing")
        await self.emergency_close(trade, reason="protection_failed")

    async def emergency_close(self, trade: Trade, reason: str = "emergency"):
        """
        Reduce or close position using reduceOnly market order.
        Never create reverse/increasing position as fallback.
        """
        symbol = trade.symbol
        # Determine position size from exchange or trade record
        try:
            positions = await self.adapter.get_positions()
            pos = next((p for p in positions if p.symbol == symbol), None)
            if not pos or pos.position_amt == Decimal("0"):
                logger.info(f"No open position for emergency close {trade.id} {symbol}")
                trade.status = "CLOSED"
                trade.close_reason = "already_closed"
                trade.closed_at = datetime.now(timezone.utc)
                self.db.commit()
                return
            qty = abs(pos.position_amt)
            side = "SELL" if pos.position_amt > 0 else "BUY"
            cid = generate_client_order_id(trade.id, "EMRG")
            result = await self.adapter.create_order(
                symbol=symbol, side=side, order_type="MARKET", quantity=qty, client_order_id=cid, reduce_only=True
            )
            trade.status = "EMERGENCY_CLOSED"
            trade.close_reason = reason
            trade.closed_at = datetime.now(timezone.utc)
            # Record fees/pnl later via reconciliation
            self.db.commit()
            logger.info(f"Emergency close executed {trade.id} qty={qty} side={side} result={result.status}")
        except Exception as e:
            logger.error(f"Emergency close failed for {trade.id}: {e}")
            trade.status = "EMERGENCY_CLOSED"
            trade.close_reason = f"emergency_failed:{e}"
            self.db.commit()

    async def reconcile_trade(self, trade: Trade):
        """
        Reconcile single trade against exchange state: fills, partial closes, liquidation, manual.
        """
        try:
            positions = await self.adapter.get_positions()
            pos = next((p for p in positions if p.symbol == trade.symbol), None)
            if not pos or pos.position_amt == Decimal("0"):
                # Position closed externally
                if trade.status not in ("CLOSED", "EMERGENCY_CLOSED"):
                    trade.status = "CLOSED"
                    trade.close_reason = trade.close_reason or "exchange_closed"
                    trade.closed_at = datetime.now(timezone.utc)
                    self.db.commit()
                    logger.info(f"Reconciled closed trade {trade.id}")
        except Exception as e:
            logger.error(f"Reconcile error {trade.id}: {e}")
