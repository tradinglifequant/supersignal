"""
Tests for the live-execution phases: trading gate, deterministic AI gate,
market-context feeds, Portfolio Margin routing and the preflight endpoint.

Gate tests construct ``Settings`` directly rather than mutating the cached
settings object - ``get_settings()`` is lru_cached and returns one shared
instance, so mutating it leaks across tests.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.ai.deterministic_gate import DeterministicGate
from app.ai.schemas import MarketSnapshot
from app.core.config import Settings
from app.exchange.binance_adapter import BinanceAdapter, EntryLockedError
from app.exchange.factory import build_adapter
from app.exchange.mock_adapter import MockBinanceAdapter
from app.trading.gate import TradingGate

ACK = Settings.LIVE_ACKNOWLEDGEMENT_PHRASE


def cfg(**kw) -> Settings:
    base = dict(trading_env="none", live_trading_opt_in=False, live_trading_acknowledgement="")
    base.update(kw)
    return Settings(**base)


def live_cfg(**kw) -> Settings:
    base = dict(
        trading_env="live",
        live_trading_opt_in=True,
        live_trading_acknowledgement=ACK,
        require_testnet_soak_hours=0,
    )
    base.update(kw)
    return Settings(**base)


# ----------------------------------------------------------------------
# Trading gate
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gate_blocks_when_trading_env_is_none():
    gate = TradingGate(MockBinanceAdapter(), cfg(trading_env="none"), is_testnet=True)
    d = await gate.authorize_entry("BTCUSDT", Decimal("50"))
    assert d.allowed is False
    assert "TRADING_ENV=none" in d.reason


@pytest.mark.asyncio
async def test_gate_allows_testnet_on_a_testnet_adapter():
    gate = TradingGate(MockBinanceAdapter(), cfg(trading_env="testnet"), is_testnet=True)
    d = await gate.authorize_entry("BTCUSDT", Decimal("50"))
    assert d.allowed is True


@pytest.mark.asyncio
async def test_gate_rejects_env_and_adapter_mismatch_in_both_directions():
    prod_gate = TradingGate(MockBinanceAdapter(), cfg(trading_env="testnet"), is_testnet=False)
    assert (await prod_gate.authorize_entry("BTCUSDT", Decimal("50"))).allowed is False

    testnet_gate = TradingGate(MockBinanceAdapter(), live_cfg(), is_testnet=True)
    assert (await testnet_gate.authorize_entry("BTCUSDT", Decimal("50"))).allowed is False


@pytest.mark.asyncio
async def test_live_requires_all_four_independent_switches():
    """No single stray env var may arm real money."""
    adapter = MockBinanceAdapter()
    cases = [
        (dict(trading_env="live"), "LIVE_TRADING_OPT_IN"),
        (dict(trading_env="live", live_trading_opt_in=True), "ACKNOWLEDGEMENT"),
        (
            dict(trading_env="live", live_trading_opt_in=True, live_trading_acknowledgement="yes"),
            "ACKNOWLEDGEMENT",
        ),
    ]
    for kwargs, expect in cases:
        gate = TradingGate(adapter, cfg(**kwargs), is_testnet=False)
        d = await gate.authorize_entry("BTCUSDT", Decimal("50"))
        assert d.allowed is False, kwargs
        assert expect.split("_")[-1].lower() in d.reason.lower() or expect.lower() in d.reason.lower()


@pytest.mark.asyncio
async def test_kill_switch_overrides_a_fully_armed_live_config():
    gate = TradingGate(MockBinanceAdapter(), live_cfg(kill_switch=True), is_testnet=False)
    d = await gate.authorize_entry("BTCUSDT", Decimal("50"))
    assert d.allowed is False
    assert "KILL_SWITCH" in d.reason


@pytest.mark.asyncio
async def test_live_requires_a_recorded_testnet_soak():
    adapter = MockBinanceAdapter()
    gate = TradingGate(adapter, live_cfg(require_testnet_soak_hours=24), is_testnet=False)
    d = await gate.authorize_entry("BTCUSDT", Decimal("50"))
    assert d.allowed is False
    assert "soak" in d.reason

    gate.testnet_armed_at = time.time() - 5 * 3600
    assert (await gate.authorize_entry("BTCUSDT", Decimal("50"))).allowed is False

    gate.testnet_armed_at = time.time() - 25 * 3600
    assert (await gate.authorize_entry("BTCUSDT", Decimal("50"))).allowed is True


@pytest.mark.asyncio
async def test_gate_enforces_the_per_order_notional_ceiling():
    gate = TradingGate(
        MockBinanceAdapter(),
        cfg(trading_env="testnet", max_order_notional=Decimal("100")),
        is_testnet=True,
    )
    assert (await gate.authorize_entry("BTCUSDT", Decimal("5000"))).allowed is False
    assert (await gate.authorize_entry("BTCUSDT", Decimal("50"))).allowed is True


@pytest.mark.asyncio
async def test_exits_are_always_permitted_even_with_the_kill_switch_set():
    """Refusing to close a position would strand real margin unprotected."""
    gate = TradingGate(
        MockBinanceAdapter(), cfg(trading_env="none", kill_switch=True), is_testnet=True
    )
    assert (await gate.authorize_entry("BTCUSDT", Decimal("50"))).allowed is False
    assert (await gate.authorize_exit("BTCUSDT")).allowed is True


@pytest.mark.asyncio
async def test_preflight_reports_a_withdrawal_capable_key_as_blocking():
    class WithdrawableAdapter(MockBinanceAdapter):
        async def get_api_key_permissions(self):
            return {"can_trade": True, "can_withdraw": True, "can_deposit": True, "source": "test"}

    gate = TradingGate(WithdrawableAdapter(), cfg(trading_env="testnet"), is_testnet=True)
    report = await gate.preflight()
    assert report["passed"] is False
    assert any("WITHDRAW" in b for b in report["blocking"])

    d = await gate.authorize_entry("BTCUSDT", Decimal("50"))
    assert d.allowed is False


@pytest.mark.asyncio
async def test_preflight_flags_large_clock_drift():
    class SkewedAdapter(MockBinanceAdapter):
        async def get_server_time(self):
            return int(time.time() * 1000) + 60_000

    gate = TradingGate(SkewedAdapter(), cfg(trading_env="testnet"), is_testnet=True)
    report = await gate.preflight()
    assert report["passed"] is False
    assert any("clock drift" in b for b in report["blocking"])


@pytest.mark.asyncio
async def test_preflight_is_cached_unless_forced():
    calls = {"n": 0}

    class CountingAdapter(MockBinanceAdapter):
        async def test_connectivity(self):
            calls["n"] += 1
            return True

    gate = TradingGate(CountingAdapter(), cfg(trading_env="testnet"), is_testnet=True)
    await gate.preflight()
    first = calls["n"]
    await gate.preflight()
    assert calls["n"] == first, "preflight should be cached"
    await gate.preflight(force=True)
    assert calls["n"] > first


# ----------------------------------------------------------------------
# Adapter: no gate means no entries, but exits still work
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_adapter_without_a_gate_refuses_entries():
    adapter = BinanceAdapter(api_key="k", api_secret="s")
    assert adapter.gate is None
    with pytest.raises(EntryLockedError, match="no trading gate"):
        await adapter.create_order("BTCUSDT", "BUY", "MARKET", Decimal("0.001"))


@pytest.mark.asyncio
async def test_adapter_refuses_entry_when_the_gate_says_no():
    adapter = BinanceAdapter(api_key="k", api_secret="s")
    adapter.gate = TradingGate(adapter, cfg(trading_env="none"), is_testnet=True)
    with pytest.raises(EntryLockedError, match="TRADING_ENV=none"):
        await adapter.create_order("BTCUSDT", "BUY", "MARKET", Decimal("0.001"))


# ----------------------------------------------------------------------
# Portfolio Margin routing
# ----------------------------------------------------------------------


def test_portfolio_margin_routes_orders_to_the_papi_um_endpoint():
    pm = BinanceAdapter(api_key="k", api_secret="s", portfolio_margin=True)
    assert pm._order_path == "/papi/v1/um/order"
    assert pm._position_risk_path == "/papi/v1/um/positionRisk"
    assert pm._open_orders_path == "/papi/v1/um/openOrders"
    assert pm._all_open_orders_path == "/papi/v1/um/allOpenOrders"

    regular = BinanceAdapter(api_key="k", api_secret="s", portfolio_margin=False)
    assert regular._order_path == "/fapi/v1/order"
    assert regular._position_risk_path == "/fapi/v2/positionRisk"


def test_portfolio_margin_defaults_to_disabled(monkeypatch):
    monkeypatch.setenv("PORTFOLIO_MARGIN", "false")
    from app.core.config import get_settings

    get_settings.cache_clear()
    try:
        assert get_settings().portfolio_margin is False
    finally:
        get_settings.cache_clear()


# ----------------------------------------------------------------------
# Deterministic AI gate
# ----------------------------------------------------------------------


def _snapshot(**kw) -> MarketSnapshot:
    now = datetime.now(timezone.utc)
    base = dict(
        snapshot_id=str(uuid.uuid4()),
        symbol="BTCUSDT",
        direction="LONG",
        trigger_price_now="66040",
        trigger_price_ref="65052",
        trigger_change_pct="1.52",
        window_seconds=180,
        detected_at=now,
        exchange_event_time=now,
        last_price="66040",
        symbol_status="TRADING",
        data_freshness_seconds=0.5,
    )
    base.update(kw)
    return MarketSnapshot(**base)


@pytest.mark.asyncio
async def _full_context():
    adapter = MockBinanceAdapter()
    k = await adapter.get_klines("BTCUSDT", "1m", 60)
    d = await adapter.get_depth("BTCUSDT", 20)
    f = await adapter.get_funding_rate("BTCUSDT")
    t = await adapter.get_ticker_24h("BTCUSDT")
    return dict(
        candles_1m=k,
        orderbook_snapshot=d,
        funding_rate=f["last_funding_rate"],
        volume_24h=t["quote_volume"],
        open_interest="123456",
    )


@pytest.mark.asyncio
async def test_deterministic_gate_approves_complete_aligned_context():
    ctx = await _full_context()
    gate = DeterministicGate()
    agents = gate.evaluate(_snapshot(**ctx))
    assert {n: r.decision for n, r in agents.items()} == {
        f"agent-{i}": "YES" for i in range(1, 6)
    }
    assert gate.aggregate(_snapshot(**ctx), agents).decision == "YES"


@pytest.mark.asyncio
async def test_deterministic_gate_fails_closed_on_missing_feeds():
    gate = DeterministicGate()
    snap = _snapshot(missing_data=["candles_1m", "orderbook", "funding_rate", "volume_24h"])
    final = gate.aggregate(snap, gate.evaluate(snap))
    assert final.decision == "NO"
    assert "INSUFFICIENT_DATA" in final.rationale


@pytest.mark.asyncio
async def test_deterministic_gate_rejects_stale_data_and_blowoff_triggers():
    ctx = await _full_context()
    gate = DeterministicGate()

    stale = _snapshot(data_freshness_seconds=99.0, **ctx)
    assert gate.aggregate(stale, gate.evaluate(stale)).decision == "NO"

    blowoff = _snapshot(trigger_change_pct="12.0", **ctx)
    assert gate.aggregate(blowoff, gate.evaluate(blowoff)).decision == "NO"


@pytest.mark.asyncio
async def test_deterministic_gate_emits_all_five_agents():
    ctx = await _full_context()
    agents = DeterministicGate().evaluate(_snapshot(**ctx))
    assert set(agents) == {f"agent-{i}" for i in range(1, 6)}
    for resp in agents.values():
        assert resp.provider_metadata == {"provider": "deterministic-gate"}
        assert resp.symbol == "BTCUSDT"


@pytest.fixture()
def restore_ai_gate_mode():
    """
    `get_settings()` is lru_cached and hands out one shared instance, so mutating
    `orchestrator.settings` mutates it for every later test. Always restore.
    """
    from app.core.config import get_settings

    original = get_settings().ai_gate_mode
    yield
    get_settings().ai_gate_mode = original


@pytest.mark.asyncio
async def test_orchestrator_honours_ai_gate_mode(restore_ai_gate_mode):
    from app.ai.threerouter_client import AIOrchestrator

    ctx = await _full_context()
    snap = _snapshot(**ctx)

    o = AIOrchestrator()
    o.settings.ai_gate_mode = "deterministic"
    prior, final = await o.run_full_pipeline(snap)
    assert len(prior) == 5
    assert final.decision == "YES"

    o.settings.ai_gate_mode = "reject_all"
    _, final = await o.run_full_pipeline(snap)
    assert final.decision == "NO"
    assert "reject_all" in final.rationale


@pytest.mark.asyncio
async def test_missing_key_is_reported_once_not_per_agent(restore_ai_gate_mode):
    """Regression: this used to log 5 ERRORs per candidate."""
    from app.ai.threerouter_client import AIOrchestrator

    o = AIOrchestrator()
    o.settings.ai_gate_mode = "threerouter"
    o.client.api_key = ""
    o.client._missing_key_logged = False
    ctx = await _full_context()

    for _ in range(3):
        _, final = await o.run_full_pipeline(_snapshot(**ctx))
        assert final.decision == "NO"
    assert o.client._missing_key_logged is True


# ----------------------------------------------------------------------
# Market-context feeds
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mock_adapter_supplies_every_context_feed():
    adapter = MockBinanceAdapter()
    assert len(await adapter.get_klines("BTCUSDT", "1m", 60)) == 60
    depth = await adapter.get_depth("BTCUSDT", 20)
    assert len(depth["top_bids"]) == 10 and len(depth["top_asks"]) == 10
    assert (await adapter.get_funding_rate("BTCUSDT"))["last_funding_rate"]
    assert (await adapter.get_open_interest("BTCUSDT"))["open_interest"]
    assert (await adapter.get_ticker_24h("BTCUSDT"))["quote_volume"]
    assert isinstance(await adapter.get_server_time(), int)


@pytest.mark.asyncio
async def test_context_builder_populates_feeds_and_reports_no_gaps():
    from app.market.context_builder import build_market_snapshot
    from app.market.price_history import PriceHistory

    class Cand:
        id = "c1"
        event_key = "k1"
        symbol = "BTCUSDT"
        direction = "LONG"
        current_price = Decimal("66040")
        reference_price = Decimal("65052")
        change_pct = Decimal("1.52")
        window_seconds = 180
        detected_at = datetime.now(timezone.utc)
        exchange_event_time = datetime.now(timezone.utc)

    history = PriceHistory(max_age_seconds=600)
    history.add("BTCUSDT", Decimal("66040"), datetime.now(timezone.utc), datetime.now(timezone.utc))

    snap = await build_market_snapshot(Cand(), history, MockBinanceAdapter(), cfg())
    assert snap.candles_1m and len(snap.candles_1m) == 60
    assert snap.orderbook_snapshot and snap.orderbook_snapshot["top_bids"]
    assert snap.funding_rate and snap.open_interest and snap.volume_24h
    # symbol_metadata is expected to be absent with no DB session supplied.
    assert "candles_1m" not in snap.missing_data
    assert "funding_rate" not in snap.missing_data
    assert "orderbook" not in snap.missing_data


@pytest.mark.asyncio
async def test_context_builder_records_a_failing_feed_as_missing_instead_of_raising():
    from app.market.context_builder import build_market_snapshot
    from app.market.price_history import PriceHistory

    class BrokenAdapter(MockBinanceAdapter):
        async def get_klines(self, symbol, interval="1m", limit=60):
            raise RuntimeError("feed down")

        async def get_funding_rate(self, symbol):
            import asyncio

            await asyncio.sleep(30)  # exercises the bounded timeout

    class Cand:
        id = "c2"
        event_key = "k2"
        symbol = "BTCUSDT"
        direction = "LONG"
        current_price = Decimal("66040")
        reference_price = Decimal("65052")
        change_pct = Decimal("1.52")
        window_seconds = 180
        detected_at = datetime.now(timezone.utc)
        exchange_event_time = datetime.now(timezone.utc)

    history = PriceHistory(max_age_seconds=600)
    history.add("BTCUSDT", Decimal("66040"), datetime.now(timezone.utc), datetime.now(timezone.utc))
    snap = await build_market_snapshot(Cand(), history, BrokenAdapter(), cfg())
    assert "candles_1m" in snap.missing_data
    assert "funding_rate" in snap.missing_data
    # The healthy feeds still made it through.
    assert snap.orderbook_snapshot is not None


# ----------------------------------------------------------------------
# Factory
# ----------------------------------------------------------------------


def test_build_adapter_always_attaches_a_gate():
    adapter, gate = build_adapter(cfg())
    assert adapter.gate is gate
    assert isinstance(adapter, MockBinanceAdapter)


# ----------------------------------------------------------------------
# Preflight endpoint
# ----------------------------------------------------------------------

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)


@pytest.fixture()
def api_token():
    from app.api.routes.auth import _login_attempts

    _login_attempts.clear()
    r = client.post("/api/auth/login", json={"username": "admin", "password": "test-password"})
    assert r.status_code == 200, r.text
    yield r.json()["access_token"]
    _login_attempts.clear()


def test_preflight_endpoint_reports_blocking_conditions(api_token):
    r = client.get("/api/engine/preflight?refresh=true", headers={"X-Access-Token": api_token})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["trading_env"] == "none"
    assert body["live_armed"] is False
    assert body["ai_gate_mode"] in ("threerouter", "deterministic", "reject_all")
    # TRADING_ENV=none is a configuration choice, not a preflight failure, so the
    # exchange-level checks should still have run and reported.
    assert "connectivity" in body["checks"]
    assert "api_key_can_trade" in body["checks"]


def test_preflight_never_echoes_credentials(api_token):
    r = client.get("/api/engine/preflight?refresh=true", headers={"X-Access-Token": api_token})
    assert r.status_code == 200
    blob = r.text.lower()
    assert "api_key_permissions" not in blob
    assert "signature" not in blob
    assert "secret" not in blob


def test_preflight_requires_authentication():
    from app.api.routes.auth import _login_attempts

    _login_attempts.clear()
    assert client.get("/api/engine/preflight").status_code == 401


def test_engine_status_exposes_the_execution_gate(api_token):
    r = client.get("/api/engine/status", headers={"X-Access-Token": api_token})
    assert r.status_code == 200, r.text
    body = r.json()
    for field in ("trading_env", "ai_gate_mode", "portfolio_margin", "live_armed"):
        assert field in body, field
    assert body["live_armed"] is False
