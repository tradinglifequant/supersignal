from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP, getcontext

# High precision for financial calcs
getcontext().prec = 28


def quantize_down(value: Decimal, step: Decimal) -> Decimal:
    """Round down to step size. Both must be Decimal, step >0."""
    if step == Decimal("0"):
        return value
    # number of steps
    steps = (value / step).to_integral_value(rounding=ROUND_DOWN)
    return steps * step


def quantize_price(value: Decimal, tick: Decimal, direction: str = "neutral") -> Decimal:
    """
    Round price to tick. For SL/TP we round in safe direction:
    - For LONG SL below entry: round up? Actually SL must be valid tick; rounding should not make risk larger.
      We'll round SL up (less distance) and TP down? But spec says "safe direction" - use HALF_UP then validate.
    Simpler: quantize down for buys, but caller decides.
    """
    if direction == "up":
        # ceil to tick
        from decimal import ROUND_CEILING
        # ceil via quantize: (value/tick).to_integral(ceil)*tick
        steps = (value / tick).to_integral_value(rounding=ROUND_DOWN)
        quantized = steps * tick
        if quantized < value:
            quantized += tick
        return quantized
    elif direction == "down":
        return quantize_down(value, tick)
    else:
        # half up
        return (value / tick).to_integral_value(rounding=ROUND_HALF_UP) * tick


def calc_change_pct(now: Decimal, ref: Decimal) -> Decimal:
    if ref == Decimal("0"):
        raise ValueError("reference price is zero")
    return ((now - ref) / ref * Decimal("100"))


def calc_gross_loss(entry: Decimal, stop: Decimal, qty: Decimal) -> Decimal:
    return abs(entry - stop) * qty


def calc_modeled_loss(
    gross_loss: Decimal,
    entry_fee: Decimal,
    exit_fee: Decimal,
    slippage_allowance: Decimal,
    funding_cost: Decimal = Decimal("0"),
) -> Decimal:
    return gross_loss + entry_fee + exit_fee + slippage_allowance + funding_cost


def calc_next_margin_after_win(base_margin: Decimal, realized_net_profit: Decimal, reinvest_pct: Decimal) -> Decimal:
    if realized_net_profit <= Decimal("0"):
        return base_margin
    return base_margin + (realized_net_profit * reinvest_pct / Decimal("100"))


def format_decimal(value: Decimal, places: int = 8) -> str:
    q = Decimal("1." + "0" * places) if places > 0 else Decimal("1")
    # Actually quantize formatting
    fmt = f"{{:.{places}f}}"
    return fmt.format(value)
