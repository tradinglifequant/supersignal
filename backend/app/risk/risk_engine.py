from __future__ import annotations

from decimal import Decimal
import logging
from typing import Optional, Tuple

from app.core.config import Settings
from app.exchange.interface import BalanceDTO, SymbolMetadataDTO
from app.utils.decimal import calc_gross_loss, calc_modeled_loss, quantize_down, quantize_price

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
    Validates: quantity step, min notional, tick, stop placement after rounding,
    modeled loss <= allocated margin, account headroom, and global limits.
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
        if entry_price <= Decimal("0"):
            raise ValueError("entry_price must be >0")
        if allocated_margin <= Decimal("0"):
            raise ValueError("allocated_margin must be >0")
        if leverage <= 0:
            raise ValueError("leverage must be >0")
        raw_qty = (allocated_margin * Decimal(leverage)) / entry_price
        qty = quantize_down(raw_qty, symbol_meta.qty_step)
        if qty < symbol_meta.min_qty:
            raise ValueError(f"Quantity {qty} below min_qty {symbol_meta.min_qty} after rounding")
        if symbol_meta.max_qty and qty > symbol_meta.max_qty:
            qty = quantize_down(symbol_meta.max_qty, symbol_meta.qty_step)
        notional = qty * entry_price
        if notional < symbol_meta.min_notional:
            raise ValueError(f"Notional {notional} below min_notional {symbol_meta.min_notional}")
        return qty, notional

    def estimate_fees(self, notional: Decimal, taker_bps: Decimal | None = None) -> Decimal:
        bps = taker_bps if taker_bps is not None else self.settings.taker_fee_bps
        return notional * bps / Decimal("10000")

    def estimate_slippage(self, notional: Decimal, slippage_bps: Decimal | None = None) -> Decimal:
        bps = slippage_bps if slippage_bps is not None else self.settings.max_slippage_bps
        return notional * bps / Decimal("10000")

    def validate_stop(
        self,
        direction: str,
        entry_price: Decimal,
        stop_price: Decimal,
        tick: Decimal,
    ) -> Tuple[bool, str | None, Decimal]:
        """
        Validate direction and distance, round to tick on the safe side, and re-verify after rounding.
        """
        if stop_price <= Decimal("0") or entry_price <= Decimal("0"):
            return False, "Prices must be positive", stop_price
        if direction == "LONG":
            if stop_price >= entry_price:
                return False, "LONG stop must be below entry", stop_price
            rounded = quantize_price(stop_price, tick, direction="up")
            if rounded >= entry_price:
                return False, "LONG stop rounded to or above entry price", rounded
            return True, None, rounded
        else:
            if stop_price <= entry_price:
                return False, "SHORT stop must be above entry", stop_price
            rounded = quantize_price(stop_price, tick, direction="down")
            if rounded <= entry_price:
                return False, "SHORT stop rounded to or below entry price", rounded
            return True, None, rounded

    def check_portfolio_margin_headroom(
        self,
        allocated_margin: Decimal,
        balances: list[BalanceDTO],
        open_positions_notional: Decimal,
        max_aggregate: Decimal | None = None,
        leverage: int | None = None,
    ) -> Tuple[bool, str | None]:
        max_agg = max_aggregate if max_aggregate is not None else self.settings.max_aggregate_exposure
        lev = leverage if leverage is not None else self.settings.leverage
        usdt_bal = next((b for b in balances if b.asset == "USDT"), None)
        if not usdt_bal:
            return False, "No USDT balance found"
        if usdt_bal.available < allocated_margin:
            return False, f"Insufficient available balance {usdt_bal.available} < allocated {allocated_margin}"
        if (open_positions_notional + allocated_margin * Decimal(lev)) > max_agg:
            return False, f"Aggregate exposure would exceed {max_agg}"
        return True, None

    def check_global_limits(
        self,
        daily_realized_pnl: Decimal,
        drawdown_pct: Decimal,
        consecutive_losses: int,
        open_positions_count: int,
        daily_loss_limit: Decimal | None = None,
        max_drawdown_pct: Decimal | None = None,
        max_concurrent_trades: int | None = None,
        max_consecutive_losses: int | None = None,
    ) -> Tuple[bool, list[str]]:
        blocks = []
        d_limit = daily_loss_limit if daily_loss_limit is not None else self.settings.daily_loss_limit
        dd_limit = max_drawdown_pct if max_drawdown_pct is not None else self.settings.max_drawdown_pct
        conc_limit = max_concurrent_trades if max_concurrent_trades is not None else self.settings.max_concurrent_trades
        loss_streak_limit = (
            max_consecutive_losses if max_consecutive_losses is not None else self.settings.max_consecutive_losses
        )

        if daily_realized_pnl <= -d_limit:
            blocks.append(f"Daily loss limit hit: {daily_realized_pnl} <= -{d_limit}")
        if drawdown_pct >= dd_limit:
            blocks.append(f"Drawdown limit hit: {drawdown_pct} >= {dd_limit}")
        if loss_streak_limit > 0 and consecutive_losses >= loss_streak_limit:
            blocks.append(f"Consecutive loss limit hit: {consecutive_losses} >= {loss_streak_limit}")
        if open_positions_count >= conc_limit:
            blocks.append(f"Max concurrent trades {conc_limit} reached")
        if self.settings.require_hard_limits:
            ok, missing = self.settings.check_hard_limits_configured()
            if not ok:
                blocks.extend(missing)
        return (len(blocks) == 0, blocks)

    def plan_position(
        self,
        symbol: str,
        direction: str,
        entry_price: Decimal,
        stop_price: Decimal,
        take_profit_price: Optional[Decimal],
        symbol_meta: SymbolMetadataDTO,
        allocated_margin: Decimal,
        balances: Optional[list[BalanceDTO]] = None,
        open_positions_notional: Decimal = Decimal("0"),
        leverage: int | None = None,
        taker_fee_bps: Decimal | None = None,
        slippage_bps: Decimal | None = None,
        max_aggregate_exposure: Decimal | None = None,
    ) -> PositionPlan:
        leverage = leverage or self.settings.leverage
        ok, reason, rounded_sl = self.validate_stop(direction, entry_price, stop_price, symbol_meta.price_tick)
        if not ok:
            return PositionPlan(
                quantity=Decimal("0"),
                notional=Decimal("0"),
                entry_price=entry_price,
                take_profit=None,
                stop_loss=stop_price,
                gross_loss=Decimal("0"),
                entry_fee=Decimal("0"),
                exit_fee=Decimal("0"),
                slippage_allowance=Decimal("0"),
                modeled_loss=Decimal("0"),
                leverage=leverage,
                allocated_margin=allocated_margin,
                approved=False,
                reason=reason,
            )
        stop_price = rounded_sl

        try:
            qty, notional = self.calculate_quantity(allocated_margin, leverage, entry_price, symbol_meta)
        except ValueError as e:
            return PositionPlan(
                quantity=Decimal("0"),
                notional=Decimal("0"),
                entry_price=entry_price,
                take_profit=None,
                stop_loss=stop_price,
                gross_loss=Decimal("0"),
                entry_fee=Decimal("0"),
                exit_fee=Decimal("0"),
                slippage_allowance=Decimal("0"),
                modeled_loss=Decimal("0"),
                leverage=leverage,
                allocated_margin=allocated_margin,
                approved=False,
                reason=str(e),
            )

        tp_rounded = None
        if take_profit_price is not None:
            if direction == "LONG":
                tp_rounded = quantize_price(take_profit_price, symbol_meta.price_tick, direction="down")
                if tp_rounded <= entry_price:
                    return PositionPlan(
                        qty, notional, entry_price, None, stop_price,
                        Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"),
                        leverage, allocated_margin, False, "TP must be above entry for LONG",
                    )
            else:
                tp_rounded = quantize_price(take_profit_price, symbol_meta.price_tick, direction="up")
                if tp_rounded >= entry_price:
                    return PositionPlan(
                        qty, notional, entry_price, None, stop_price,
                        Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"),
                        leverage, allocated_margin, False, "TP must be below entry for SHORT",
                    )

        gross_loss = calc_gross_loss(entry_price, stop_price, qty)
        entry_fee = self.estimate_fees(notional, taker_bps=taker_fee_bps)
        exit_fee = self.estimate_fees(qty * stop_price, taker_bps=taker_fee_bps)
        slippage = self.estimate_slippage(notional, slippage_bps=slippage_bps) + self.estimate_slippage(
            qty * stop_price, slippage_bps=slippage_bps
        )
        modeled = calc_modeled_loss(gross_loss, entry_fee, exit_fee, slippage)

        if modeled > allocated_margin:
            return PositionPlan(
                qty, notional, entry_price, tp_rounded, stop_price,
                gross_loss, entry_fee, exit_fee, slippage, modeled,
                leverage, allocated_margin, False,
                f"Modeled loss {modeled} exceeds allocated margin {allocated_margin}",
            )

        if balances is not None:
            ok_pm, reason_pm = self.check_portfolio_margin_headroom(
                allocated_margin,
                balances,
                open_positions_notional,
                max_aggregate=max_aggregate_exposure,
                leverage=leverage,
            )
            if not ok_pm:
                return PositionPlan(
                    qty, notional, entry_price, tp_rounded, stop_price,
                    gross_loss, entry_fee, exit_fee, slippage, modeled,
                    leverage, allocated_margin, False, reason_pm,
                )

        return PositionPlan(
            qty, notional, entry_price, tp_rounded, stop_price,
            gross_loss, entry_fee, exit_fee, slippage, modeled,
            leverage, allocated_margin, True, None,
        )

    def calculate_next_margin(
        self,
        base_margin: Decimal,
        realized_net_profit: Decimal,
        reinvest_pct: Decimal | None = None,
        max_allocation: Decimal | None = None,
    ) -> Decimal:
        if realized_net_profit > Decimal("0"):
            pct = reinvest_pct if reinvest_pct is not None else self.settings.profit_reinvestment_pct
            cap = max_allocation if max_allocation is not None else self.settings.max_trade_allocation
            nxt = base_margin + (realized_net_profit * pct / Decimal("100"))
            if nxt > cap:
                nxt = cap
            return nxt
        return base_margin
