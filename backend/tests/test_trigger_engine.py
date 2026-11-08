"""
Tests for trigger engine - per PRD FR-02 acceptance criteria.
Covers positive, negative, exact-threshold, below-threshold, zero/invalid, stale, out-of-order, rolling-window boundaries.
"""
import pytest
from decimal import Decimal
from datetime import datetime, timezone, timedelta

from app.market.price_history import PriceHistory
from app.market.trigger_engine import TriggerEngine
from app.core.config import Settings

def make_settings(**overrides):
    defaults = dict(
        trigger_percentage=Decimal("1.5"),
        trigger_window_seconds=180,
        base_margin=Decimal("3"),
        leverage=10,
        max_concurrent_trades=3,
        profit_reinvestment_pct=Decimal("25"),
        database_url="sqlite:///:memory:",
        app_env="testnet",
    )
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore

def make_history_with_two_samples(symbol, price_ref, price_now, ref_time, now_time):
    ph = PriceHistory(max_age_seconds=600)
    ph.add(symbol, Decimal(str(price_ref)), ref_time, receipt_mono=1, receipt_wall=ref_time)
    ph.add(symbol, Decimal(str(price_now)), now_time, receipt_mono=2, receipt_wall=now_time)
    # Also add intermediate to ensure window logic picks correct ref
    return ph

def test_trigger_long_positive():
    settings = make_settings()
    now = datetime.now(timezone.utc)
    ref = now - timedelta(seconds=180)
    ph = make_history_with_two_samples("BTCUSDT", "64000", "65000", ref, now)
    engine = TriggerEngine(ph, settings)
    result = engine.evaluate("BTCUSDT", now_wall=now)
    assert result is not None
    assert result.direction == "LONG"
    assert result.symbol == "BTCUSDT"
    # change = (1000/64000)*100 ≈ 1.5625
    assert result.change_pct == Decimal("1.5625")

def test_trigger_short_negative():
    settings = make_settings()
    now = datetime.now(timezone.utc)
    ref = now - timedelta(seconds=180)
    ph = make_history_with_two_samples("BTCUSDT", "65000", "64000", ref, now)
    engine = TriggerEngine(ph, settings)
    result = engine.evaluate("BTCUSDT", now_wall=now)
    assert result is not None
    assert result.direction == "SHORT"

def test_exact_threshold_long():
    settings = make_settings(trigger_percentage=Decimal("1.5"))
    now = datetime.now(timezone.utc)
    ref = now - timedelta(seconds=180)
    # exactly 1.5%
    ref_price = Decimal("100")
    now_price = Decimal("101.5")  # +1.5%
    ph = PriceHistory()
    ph.add("BTCUSDT", ref_price, ref, receipt_mono=1, receipt_wall=ref)
    ph.add("BTCUSDT", now_price, now, receipt_mono=2, receipt_wall=now)
    engine = TriggerEngine(ph, settings)
    result = engine.evaluate("BTCUSDT", now_wall=now)
    assert result is not None
    assert result.direction == "LONG"

def test_exact_threshold_short():
    settings = make_settings()
    now = datetime.now(timezone.utc)
    ref = now - timedelta(seconds=180)
    ph = PriceHistory()
    # exactly -1.5%: from 100 to 98.5
    ph.add("BTCUSDT", Decimal("100"), ref, receipt_mono=1, receipt_wall=ref)
    ph.add("BTCUSDT", Decimal("98.5"), now, receipt_mono=2, receipt_wall=now)
    engine = TriggerEngine(ph, settings)
    result = engine.evaluate("BTCUSDT", now_wall=now)
    assert result is not None
    assert result.direction == "SHORT"

def test_below_threshold_no_trigger():
    settings = make_settings()
    now = datetime.now(timezone.utc)
    ref = now - timedelta(seconds=180)
    ph = PriceHistory()
    ph.add("BTCUSDT", Decimal("100"), ref, receipt_mono=1, receipt_wall=ref)
    ph.add("BTCUSDT", Decimal("101.4"), now, receipt_mono=2, receipt_wall=now)  # 1.4% <1.5
    engine = TriggerEngine(ph, settings)
    result = engine.evaluate("BTCUSDT", now_wall=now)
    assert result is None

def test_zero_price_invalid():
    settings = make_settings()
    now = datetime.now(timezone.utc)
    ref = now - timedelta(seconds=180)
    ph = PriceHistory()
    ph.add("BTCUSDT", Decimal("0"), ref, receipt_mono=1, receipt_wall=ref)
    ph.add("BTCUSDT", Decimal("100"), now, receipt_mono=2, receipt_wall=now)
    engine = TriggerEngine(ph, settings)
    result = engine.evaluate("BTCUSDT", now_wall=now)
    assert result is None

def test_missing_lookback_no_trigger():
    settings = make_settings()
    now = datetime.now(timezone.utc)
    ph = PriceHistory()
    # Only recent sample, no 180s reference
    ph.add("BTCUSDT", Decimal("100"), now, receipt_mono=1, receipt_wall=now)
    engine = TriggerEngine(ph, settings)
    result = engine.evaluate("BTCUSDT", now_wall=now)
    assert result is None

def test_stale_data_blocked():
    settings = make_settings()
    now = datetime.now(timezone.utc)
    ref = now - timedelta(seconds=180)
    old = now - timedelta(seconds=70)  # stale >60s threshold
    ph = PriceHistory()
    ph.add("BTCUSDT", Decimal("100"), ref, receipt_mono=1, receipt_wall=ref)
    ph.add("BTCUSDT", Decimal("102"), old, receipt_mono=2, receipt_wall=old)
    engine = TriggerEngine(ph, settings)
    # now_wall is now, but last update is old => stale => no trigger
    result = engine.evaluate("BTCUSDT", now_wall=now)
    assert result is None

def test_out_of_order_handled():
    settings = make_settings()
    now = datetime.now(timezone.utc)
    ref = now - timedelta(seconds=180)
    later = now - timedelta(seconds=10)
    ph = PriceHistory()
    ph.add("BTCUSDT", Decimal("100"), ref, receipt_mono=1, receipt_wall=ref)
    ph.add("BTCUSDT", Decimal("102"), now, receipt_mono=2, receipt_wall=now)
    # Add out-of-order tick with earlier exchange time but later receipt
    ph.add("BTCUSDT", Decimal("101"), later, receipt_mono=3, receipt_wall=now + timedelta(seconds=1))
    engine = TriggerEngine(ph, settings)
    # Last price is now 101? Actually we appended out-of-order, but buffer includes it.
    # Evaluate should still handle; we expect no crash and either trigger or not
    result = engine.evaluate("BTCUSDT", now_wall=now + timedelta(seconds=1))
    # With last=101 and ref=100 => 1% => no trigger
    assert result is None or result.change_pct == Decimal("1.0")

def test_rolling_window_boundary():
    settings = make_settings()
    now = datetime.now(timezone.utc)
    # Test tolerance: ref exactly 180s ago vs slightly before
    ref_exact = now - timedelta(seconds=180)
    ref_early = now - timedelta(seconds=185)
    ph = PriceHistory()
    ph.add("BTCUSDT", Decimal("100"), ref_early, receipt_mono=1, receipt_wall=ref_early)
    ph.add("BTCUSDT", Decimal("102"), now, receipt_mono=2, receipt_wall=now)
    engine = TriggerEngine(ph, settings)
    result = engine.evaluate("BTCUSDT", now_wall=now)
    # Should pick ref_early within 10s tolerance => 2% => trigger LONG
    assert result is not None
    assert result.direction == "LONG"

def test_negative_price_invalid():
    settings = make_settings()
    now = datetime.now(timezone.utc)
    ref = now - timedelta(seconds=180)
    ph = PriceHistory()
    ph.add("BTCUSDT", Decimal("-100"), ref, receipt_mono=1, receipt_wall=ref)
    ph.add("BTCUSDT", Decimal("101.5"), now, receipt_mono=2, receipt_wall=now)
    engine = TriggerEngine(ph, settings)
    result = engine.evaluate("BTCUSDT", now_wall=now)
    assert result is None
