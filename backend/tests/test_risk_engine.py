"""
Risk engine tests - FR-04 acceptance: property-based, exchange precision, fee/slippage, leverage brackets, loss cap.
"""
import pytest
from decimal import Decimal

from app.core.config import Settings
from app.risk.risk_engine import RiskEngine
from app.exchange.interface import SymbolMetadataDTO

def make_settings(**overrides):
    defaults = dict(
        trigger_percentage=Decimal("1.5"),
        trigger_window_seconds=180,
        base_margin=Decimal("3"),
        leverage=10,
        max_concurrent_trades=3,
        profit_reinvestment_pct=Decimal("25"),
        max_trade_allocation=Decimal("100"),
        daily_loss_limit=Decimal("50"),
        max_drawdown_pct=Decimal("10"),
        max_aggregate_exposure=Decimal("1000"),
        max_slippage_bps=Decimal("50"),
        taker_fee_bps=Decimal("4"),
        database_url="sqlite:///:memory:",
        app_env="testnet",
    )
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore

def make_meta(**overrides):
    defaults = dict(
        symbol="BTCUSDT", status="TRADING", contract_type="PERPETUAL", margin_asset="USDT",
        price_tick=Decimal("0.1"), qty_step=Decimal("0.001"), min_qty=Decimal("0.001"),
        max_qty=Decimal("1000"), min_notional=Decimal("5"), price_precision=1, quantity_precision=3,
    )
    defaults.update(overrides)
    return SymbolMetadataDTO(**defaults)  # type: ignore

def test_risk_approved_when_within_margin():
    settings = make_settings()
    engine = RiskEngine(settings)
    meta = make_meta()
    plan = engine.plan_position(
        symbol="BTCUSDT", direction="LONG",
        entry_price=Decimal("65000"), stop_price=Decimal("64350"),  # 650 stop distance
        take_profit_price=Decimal("65975"), symbol_meta=meta,
        allocated_margin=Decimal("10"),
    )
    assert plan.approved, f"Expected approved but got {plan.reason}"
    assert plan.modeled_loss <= Decimal("10")

def test_risk_rejected_when_modeled_exceeds_margin():
    settings = make_settings(base_margin=Decimal("10"))
    engine = RiskEngine(settings)
    # Use low-price symbol so quantity passes min checks but loss still exceeds margin
    meta = make_meta(price_tick=Decimal("0.01"), qty_step=Decimal("0.01"), min_qty=Decimal("0.01"), min_notional=Decimal("5"))
    # entry 100, stop 90 => 10 distance, qty = (10*10)/100=1.0 => notional 100 => gross loss 10*1=10, fees/slippage ~0.08 => modeled ~10.08 > allocated 10 => reject
    plan = engine.plan_position(
        symbol="BTCUSDT", direction="LONG",
        entry_price=Decimal("100"), stop_price=Decimal("90"),
        take_profit_price=None, symbol_meta=meta,
        allocated_margin=Decimal("10"),
    )
    assert not plan.approved
    assert "exceeds allocated margin" in plan.reason.lower()

def test_quantity_rounding_down_to_step():
    settings = make_settings()
    engine = RiskEngine(settings)
    meta = make_meta(qty_step=Decimal("0.001"), min_qty=Decimal("0.001"))
    # Compute: margin 3*10 /65000 = 0.0004615 => rounds down to 0.000 => fails min_qty?
    # But we set margin 10 => 0.0015 => rounds to 0.001
    plan = engine.plan_position(
        symbol="BTCUSDT", direction="LONG",
        entry_price=Decimal("65000"), stop_price=Decimal("64350"),
        take_profit_price=None, symbol_meta=meta, allocated_margin=Decimal("10")
    )
    # Should have quantity step-aligned
    assert plan.quantity % Decimal("0.001") == Decimal("0")

def test_min_notional_rejected():
    settings = make_settings()
    engine = RiskEngine(settings)
    meta = make_meta(min_notional=Decimal("1000"))  # High notional requirement
    plan = engine.plan_position(
        symbol="BTCUSDT", direction="LONG",
        entry_price=Decimal("65000"), stop_price=Decimal("64350"),
        take_profit_price=None, symbol_meta=meta, allocated_margin=Decimal("3")
    )
    assert not plan.approved
    assert "notional" in plan.reason.lower() or "min_notional" in plan.reason.lower() or "below" in plan.reason.lower()

def test_stop_direction_validation_long():
    settings = make_settings()
    engine = RiskEngine(settings)
    meta = make_meta()
    plan = engine.plan_position(
        symbol="BTCUSDT", direction="LONG",
        entry_price=Decimal("65000"), stop_price=Decimal("66000"),  # Invalid: stop above entry for LONG
        take_profit_price=None, symbol_meta=meta, allocated_margin=Decimal("10")
    )
    assert not plan.approved
    assert "stop must be below entry" in plan.reason.lower()

def test_stop_direction_validation_short():
    settings = make_settings()
    engine = RiskEngine(settings)
    meta = make_meta()
    plan = engine.plan_position(
        symbol="BTCUSDT", direction="SHORT",
        entry_price=Decimal("65000"), stop_price=Decimal("64000"),
        take_profit_price=None, symbol_meta=meta, allocated_margin=Decimal("10")
    )
    assert not plan.approved
    assert "stop must be above entry" in plan.reason.lower()

def test_fee_and_slippage_included():
    settings = make_settings(taker_fee_bps=Decimal("10"), max_slippage_bps=Decimal("10"))
    engine = RiskEngine(settings)
    meta = make_meta()
    plan = engine.plan_position(
        symbol="BTCUSDT", direction="LONG",
        entry_price=Decimal("50000"), stop_price=Decimal("49900"),
        take_profit_price=None, symbol_meta=meta, allocated_margin=Decimal("50")
    )
    assert plan.approved
    # modeled loss = gross + fees + slippage > gross
    assert plan.modeled_loss > plan.gross_loss
    assert plan.entry_fee > Decimal("0")
    assert plan.exit_fee > Decimal("0")
    assert plan.slippage_allowance > Decimal("0")

def test_next_margin_after_win():
    settings = make_settings(base_margin=Decimal("3"), profit_reinvestment_pct=Decimal("25"), max_trade_allocation=Decimal("100"))
    engine = RiskEngine(settings)
    nxt = engine.calculate_next_margin(Decimal("3"), Decimal("10"))
    assert nxt == Decimal("5.5")  # 3 + 10*0.25
    # Clamp
    nxt2 = engine.calculate_next_margin(Decimal("90"), Decimal("100"))
    assert nxt2 == Decimal("100")  # clamped to max

def test_next_margin_after_loss():
    settings = make_settings()
    engine = RiskEngine(settings)
    nxt = engine.calculate_next_margin(Decimal("3"), Decimal("-5"))
    assert nxt == Decimal("3")

def test_portfolio_margin_insufficient_balance():
    settings = make_settings(max_aggregate_exposure=Decimal("100"))
    engine = RiskEngine(settings)
    from app.exchange.interface import BalanceDTO
    balances = [BalanceDTO(asset="USDT", balance=Decimal("10"), available=Decimal("2"), cross_unrealized=Decimal("0"))]
    ok, reason = engine.check_portfolio_margin_headroom(Decimal("5"), balances, Decimal("0"))
    assert not ok
    assert "insufficient" in reason.lower()

def test_global_limits_blocks():
    settings = make_settings(daily_loss_limit=Decimal("50"), max_drawdown_pct=Decimal("10"), max_concurrent_trades=3)
    engine = RiskEngine(settings)
    ok, blocks = engine.check_global_limits(Decimal("-60"), Decimal("5"), 0, 0)
    assert not ok
    assert any("daily loss" in b.lower() for b in blocks)

def test_tick_rounding_safe_direction_long_sl():
    settings = make_settings()
    engine = RiskEngine(settings)
    meta = make_meta(price_tick=Decimal("0.1"))
    ok, reason, rounded = engine.validate_stop("LONG", Decimal("65000"), Decimal("64990.04"), Decimal("0.1"))
    assert ok
    # LONG SL ceil => 64990.1
    assert rounded == Decimal("64990.1")

def test_tick_rounding_safe_direction_short_sl():
    settings = make_settings()
    engine = RiskEngine(settings)
    ok, reason, rounded = engine.validate_stop("SHORT", Decimal("65000"), Decimal("65009.96"), Decimal("0.1"))
    assert ok
    # SHORT SL floor => 65009.9
    assert rounded == Decimal("65009.9")
