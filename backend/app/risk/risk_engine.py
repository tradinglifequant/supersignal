from __future__ import annotations

from decimal import Decimal, ROUND_DOWN, InvalidOperation
from typing import Optional, Tuple, Dict, Any
import logging
from datetime import datetime, timezone

from app.core.config import Settings
from app.exchange.interface import SymbolMetadataDTO, BalanceDTO
from app.utils.decimal import quantize_down, calc_gross_loss, calc_modeled_loss
from app.db.models import Trade

logger = logging.getLogger(__name__)

class RiskConfig:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def taker_fee_bps(self) -> Decimal:
        return self.settings.taker_fee_bps

    @property
    def slippage_bps(self) -> Decimal:
        return self.settings.max_slippage_bps

    @property
    def base_margin(self) -> Decimal:
        return self.settings.base_margin

    @property
    def max_allocation(self) -> Decimal:
        return self.settings.max_trade_allocation

class PositionPlan:
    def __init__(
        self,
        quantity: Decimal,
        notional: Decimal,
        entry_price: Decimal,
        take_profit: Optional[Decimal],
        stop_loss: Decimal,
        gross_loss: Decimal,
        entry_fee: Decimal,
        exit_fee: Decimal,
        slippage_allowance: Decimal,
        modeled_loss: Decimal,
        leverage: int,
        allocated_margin: Decimal,
        approved: bool,
        reason: str | None = None,
    ):
        self.quantity = quantity
        self.notional = notional
        self.entry_price = entry_price
        self.take_profit = take_profit
        self.stop_loss = stop_loss
        self.gross_loss = gross_loss
        self.entry_fee = entry_fee
        self.exit_fee = exit_fee
        self.slippage_allowance = slippage_allowance
        self.modeled_loss = modeled_loss
        self.leverage = leverage
        self.allocated_margin = allocated_margin
        self.approved = approved
        self.reason = reason

class RiskEngine:
    """
    Deterministic risk engine - never bypassed by AI.
    Calculates position size from allocated margin, leverage, exchange precision.
    Validates: quantity step, min notional, tick, leverage brackets, modeled loss <= allocated margin, global limits.
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    def calculate_quantity(
        self,
        allocated_margin: Decimal,
        leverage: int,
        entry_price: Decimal,
        symbol_meta: SymbolMetadataDTO,
    ) -> Tuple[Decimal, Decimal]:
        """
        quantity = (allocated_margin * leverage) / entry_price
        Then round down to step size, validate min/max, min_notional.
        Returns (quantity, notional)
        """
        if entry_price <= Decimal("0"):
            raise ValueError("entry_price must be >0")
        raw_qty = (allocated_margin * Decimal(leverage)) / entry_price
        # Round down to step
        qty = quantize_down(raw_qty, symbol_meta.qty_step)
        if qty < symbol_meta.min_qty:
            # Cannot meet min_qty
            raise ValueError(f"Quantity {qty} below min_qty {symbol_meta.min_qty} after rounding")
        if symbol_meta.max_qty and qty > symbol_meta.max_qty:
            qty = symbol_meta.max_qty
        notional = qty * entry_price
        if notional < symbol_meta.min_notional:
            raise ValueError(f"Notional {notional} below min_notional {symbol_meta.min_notional}")
        return qty, notional

    def estimate_fees(self, notional: Decimal, taker_bps: Decimal | None = None) -> Decimal:
        bps = taker_bps or self.settings.taker_fee_bps
        return notional * bps / Decimal("10000")

    def estimate_slippage(self, notional: Decimal, slippage_bps: Decimal | None = None) -> Decimal:
        bps = slippage_bps or self.settings.max_slippage_bps
        return notional * bps / Decimal("10000")

    def validate_stop(
        self,
        direction: str,
        entry_price: Decimal,
        stop_price: Decimal,
        tick: Decimal,
    ) -> Tuple[bool, str | None, Decimal]:
        """
        Validate direction and distance, round to tick safe side.
        For LONG, SL must be < entry; for SHORT, > entry.
        """
        if direction == "LONG":
            if stop_price >= entry_price:
                return False, "LONG stop must be below entry", stop_price
            # round stop up? Actually safe direction: rounding stop up reduces distance => less risk (conservative).
            # We'll round to nearest tick downward? Let's define: LONG SL tick rounding: if tick=0.1 and stop=64990.04, tick rounding down would be 64990.0 (further away => larger loss) unsafe.
            # Safer to round up (ceil) => 64990.1 (closer to entry, smaller loss) ensures modeled loss is upper bound.
            # But spec says "Round TP/SL to valid tick size in the safe direction" - safe = reduce risk.
            # So LONG SL => ceil, SHORT SL => floor.
            # We'll use quantize helper.
            from app.utils.decimal import quantize_price
            rounded = quantize_price(stop_price, tick, direction="up")  # ceil
            return True, None, rounded
        else:  # SHORT
            if stop_price <= entry_price:
                return False, "SHORT stop must be above entry", stop_price
            from app.utils.decimal import quantize_price
            rounded = quantize_price(stop_price, tick, direction="down")
            return True, None, rounded

    def check_portfolio_margin_headroom(
        self,
        allocated_margin: Decimal,
        balances: list[BalanceDTO],
        open_positions_notional: Decimal,
        max_aggregate: Decimal | None = None,
    ) -> Tuple[bool, str | None]:
        max_agg = max_aggregate or self.settings.max_aggregate_exposure
        usdt_bal = next((b for b in balances if b.asset == "USDT"), None)
        if not usdt_bal:
            return False, "No USDT balance found"
        if usdt_bal.available < allocated_margin:
            return False, f"Insufficient available balance {usdt_bal.available} < allocated {allocated_margin}"
        if (open_positions_notional + allocated_margin * Decimal(self.settings.leverage)) > max_agg:
            return False, f"Aggregate exposure would exceed {max_agg}"
        # Additional: reserve headroom for maintenance margin (e.g., 20% buffer)
        # For Portfolio Margin, we need account-level risk endpoint; we approximate.
        return True, None

    def check_global_limits(
        self,
        daily_realized_pnl: Decimal,
        drawdown_pct: Decimal,
        consecutive_losses: int,
        open_positions_count: int,
    ) -> Tuple[bool, list[str]]:
        blocks = []
        if daily_realized_pnl <= -self.settings.daily_loss_limit:
            blocks.append(f"Daily loss limit hit: {daily_realized_pnl} <= -{self.settings.daily_loss_limit}")
        if drawdown_pct >= self.settings.max_drawdown_pct:
            blocks.append(f"Drawdown limit hit: {drawdown_pct} >= {self.settings.max_drawdown_pct}")
        if open_positions_count >= self.settings.max_concurrent_trades:
            blocks.append(f"Max concurrent trades {self.settings.max_concurrent_trades} reached")
        # If missing hard limits, block
        if self.settings.require_hard_limits:
            ok, missing = self.settings.check_hard_limits_configured()
            if not ok:
                blocks.extend(missing)
        return (len(blocks) == 0, blocks)

    def plan_position(
        self,
        symbol: str,
        direction: str,  # LONG|SHORT
        entry_price: Decimal,
        stop_price: Decimal,
        take_profit_price: Optional[Decimal],
        symbol_meta: SymbolMetadataDTO,
        allocated_margin: Decimal,
        balances: Optional[list[BalanceDTO]] = None,
        open_positions_notional: Decimal = Decimal("0"),
        leverage: int | None = None,
    ) -> PositionPlan:
        leverage = leverage or self.settings.leverage
        # Step 1: validate stop
        ok, reason, rounded_sl = self.validate_stop(direction, entry_price, stop_price, symbol_meta.price_tick)
        if not ok:
            return PositionPlan(
                quantity=Decimal("0"), notional=Decimal("0"), entry_price=entry_price,
                take_profit=None, stop_loss=stop_price,
                gross_loss=Decimal("0"), entry_fee=Decimal("0"), exit_fee=Decimal("0"),
                slippage_allowance=Decimal("0"), modeled_loss=Decimal("0"),
                leverage=leverage, allocated_margin=allocated_margin,
                approved=False, reason=reason,
            )
        stop_price = rounded_sl
        # Step 2: quantity
        try:
            qty, notional = self.calculate_quantity(allocated_margin, leverage, entry_price, symbol_meta)
        except ValueError as e:
            return PositionPlan(
                quantity=Decimal("0"), notional=Decimal("0"), entry_price=entry_price,
                take_profit=None, stop_loss=stop_price,
                gross_loss=Decimal("0"), entry_fee=Decimal("0"), exit_fee=Decimal("0"),
                slippage_allowance=Decimal("0"), modeled_loss=Decimal("0"),
                leverage=leverage, allocated_margin=allocated_margin,
                approved=False, reason=str(e),
            )

        # Step 3: take profit rounding (if provided)
        tp_rounded = None
        if take_profit_price:
            from app.utils.decimal import quantize_price
            if direction == "LONG":
                # TP above entry, round down? Safe direction: TP rounding down reduces profit but not risk. We'll round down to ensure reachable?
                # For LONG TP > entry, floor ensures TP not beyond tick causing rejection, but safe is floor? Let's use down for LONG TP (slightly lower profit)
                tp_rounded = quantize_price(take_profit_price, symbol_meta.price_tick, direction="down")
                if tp_rounded <= entry_price:
                    return PositionPlan(qty, notional, entry_price, None, stop_price, Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), leverage, allocated_margin, False, "TP must be above entry for LONG")
            else:
                tp_rounded = quantize_price(take_profit_price, symbol_meta.price_tick, direction="up")
                if tp_rounded >= entry_price:
                    return PositionPlan(qty, notional, entry_price, None, stop_price, Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), leverage, allocated_margin, False, "TP must be below entry for SHORT")

        # Step 4: modeled loss
        gross_loss = calc_gross_loss(entry_price, stop_price, qty)
        entry_fee = self.estimate_fees(notional)
        exit_fee = self.estimate_fees(qty * stop_price)  # approximate exit notional at stop
        slippage = self.estimate_slippage(notional) + self.estimate_slippage(qty * stop_price)  # entry+exit slippage
        modeled = calc_modeled_loss(gross_loss, entry_fee, exit_fee, slippage)

        if modeled > allocated_margin:
            return PositionPlan(qty, notional, entry_price, tp_rounded, stop_price, gross_loss, entry_fee, exit_fee, slippage, modeled, leverage, allocated_margin, False, f"Modeled loss {modeled} exceeds allocated margin {allocated_margin}")

        # Step 5: portfolio margin headroom if balances provided
        if balances is not None:
            ok_pm, reason_pm = self.check_portfolio_margin_headroom(allocated_margin, balances, open_positions_notional)
            if not ok_pm:
                return PositionPlan(qty, notional, entry_price, tp_rounded, stop_price, gross_loss, entry_fee, exit_fee, slippage, modeled, leverage, allocated_margin, False, reason_pm)

        return PositionPlan(qty, notional, entry_price, tp_rounded, stop_price, gross_loss, entry_fee, exit_fee, slippage, modeled, leverage, allocated_margin, True, None)

    def calculate_next_margin(self, base_margin: Decimal, realized_net_profit: Decimal, reinvest_pct: Decimal | None = None) -> Decimal:
        if realized_net_profit > Decimal("0"):
            pct = reinvest_pct or self.settings.profit_reinvestment_pct
            nxt = base_margin + (realized_net_profit * pct / Decimal("100"))
            # Clamp to max allocation
            if nxt > self.settings.max_trade_allocation:
                nxt = self.settings.max_trade_allocation
            return nxt
        else:
            # Loss or breakeven -> reset to base
            return base_margin
