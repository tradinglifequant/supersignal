from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import logging
from pathlib import Path
import sqlite3
from unittest.mock import AsyncMock

from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi.testclient import TestClient
import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.ai.schemas import AgentResponse, MarketSnapshot
from app.ai.threerouter_client import AIOrchestrator, ThreeRouterClient
from app.core.config import Settings, get_settings
from app.core.logging import RedactingFilter, redact_str
from app.db.base import Base
from app.db.models import EquitySnapshot, MarginScalingEvent, Order, SignalCandidate, SymbolMetadata, Trade
from app.exchange.interface import OrderResultDTO, PositionDTO, SymbolMetadataDTO
from app.exchange.mock_adapter import MockBinanceAdapter
from app.execution.execution_engine import ExecutionEngine, generate_client_order_id
from app.main import app
from app.market.candidate_lifecycle import CandidateManager
from app.market.price_history import PriceHistory
from app.market.symbol_universe import SymbolUniverseService
from app.market.trigger_engine import TriggerEngine, TriggerResult
from app.monitor.position_monitor import PositionMonitor
from app.risk.risk_engine import RiskEngine
from app.api.routes.auth import _login_attempts
from app.security.encryption import decrypt_value, encrypt_value, reset_encryption_cache


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    s = Session()
    try:
        yield s
    finally:
        s.close()


def test_redacting_filter_handles_dict_args_and_exchange_secrets():
    filt = RedactingFilter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Payload %(sig)s header %(hdr)s",
        args={"sig": "signature=abcdef0123456789", "hdr": "X-MBX-APIKEY: mySecretKey12345"},
        exc_info=None,
    )
    assert filt.filter(record) is True
    formatted = record.getMessage()
    assert "abcdef0123456789" not in formatted
    assert "mySecretKey12345" not in formatted
    assert "REDACTED" in formatted
    assert "secretListenKey999" not in redact_str("listenKey=secretListenKey999")


def test_encryption_dev_ephemeral_cache_and_prod_fail_closed(monkeypatch):
    reset_encryption_cache()
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", "")
    get_settings.cache_clear()

    ciphertext = encrypt_value("my-binance-secret")
    # Previously failed because each call generated a brand-new random key
    assert decrypt_value(ciphertext) == "my-binance-secret"

    reset_encryption_cache()
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", "")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="CREDENTIALS_ENCRYPTION_KEY"):
        encrypt_value("prod-secret")

    monkeypatch.setenv("APP_ENV", "development")
    get_settings.cache_clear()
    reset_encryption_cache()


def test_sqlite_utc_datetime_and_candidate_expiry(db_session):
    settings = Settings()
    mgr = CandidateManager(db_session, settings)
    now = datetime.now(timezone.utc)
    trig = TriggerResult(
        symbol="BTCUSDT",
        direction="LONG",
        price_now=Decimal("66000"),
        price_ref=Decimal("65000"),
        change_pct=Decimal("1.538"),
        window_seconds=180,
        exchange_event_time=now,
        detected_at=now,
    )
    cand = mgr.create_candidate(trig, ttl_seconds=30)
    assert cand is not None
    db_session.expire_all()
    reloaded = db_session.query(SignalCandidate).filter_by(id=cand.id).one()
    assert reloaded.expires_at.tzinfo == timezone.utc
    assert mgr.check_expiry(reloaded) is False


def test_out_of_order_tick_blocks_trigger_until_fresh_ordered_tick():
    settings = Settings()
    ph = PriceHistory()
    te = TriggerEngine(ph, settings)
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    ph.add("BTCUSDT", Decimal("100"), base, receipt_wall=base)
    t_now = base + timedelta(seconds=180)
    ph.add("BTCUSDT", Decimal("102"), t_now, receipt_wall=t_now)
    # Out-of-order late arrival
    ph.add("BTCUSDT", Decimal("103"), t_now - timedelta(seconds=5), receipt_wall=t_now)
    assert ph.is_out_of_order("BTCUSDT") is True
    assert te.evaluate("BTCUSDT", now_wall=t_now) is None

    # Next monotonic tick clears out-of-order state
    t_next = t_now + timedelta(seconds=1)
    ph.add("BTCUSDT", Decimal("102"), t_next, receipt_wall=t_next)
    assert ph.is_out_of_order("BTCUSDT") is False
    res = te.evaluate("BTCUSDT", now_wall=t_next)
    assert res is not None and res.direction == "LONG"


@pytest.mark.asyncio
async def test_symbol_universe_marks_removed_symbols_ineligible(db_session):
    adapter = MockBinanceAdapter()
    svc = SymbolUniverseService(adapter, db_session)
    await svc.refresh()
    assert db_session.query(SymbolMetadata).filter_by(symbol="SOLUSDT").one().is_eligible is True

    # Remove SOLUSDT from exchange eligible list
    adapter.symbols = [s for s in adapter.symbols if s.symbol != "SOLUSDT"]
    await svc.refresh()
    sol = db_session.query(SymbolMetadata).filter_by(symbol="SOLUSDT").one()
    assert sol.is_eligible is False
    assert svc.get_cached("SOLUSDT") is None


def test_risk_post_rounding_stop_check_and_consecutive_losses():
    settings = Settings(max_consecutive_losses=3)
    risk = RiskEngine(settings)
    # Stop 99.95 on tick 0.1 rounds UP for LONG to 100.0 == entry_price -> MUST be rejected!
    ok, reason, rounded = risk.validate_stop("LONG", Decimal("100.0"), Decimal("99.95"), Decimal("0.1"))
    assert ok is False
    assert rounded == Decimal("100.0")
    assert reason is not None

    ok_short, reason_short, rounded_short = risk.validate_stop("SHORT", Decimal("100.0"), Decimal("100.05"), Decimal("0.1"))
    assert ok_short is False
    assert rounded_short == Decimal("100.0")
    assert reason_short is not None

    ok_lim, blocks = risk.check_global_limits(
        daily_realized_pnl=Decimal("0"),
        drawdown_pct=Decimal("0"),
        consecutive_losses=3,
        open_positions_count=0,
    )
    assert ok_lim is False
    assert any("Consecutive loss limit hit" in b for b in blocks)


@pytest.mark.asyncio
async def test_agent6_deterministic_fail_closed_and_symbol_mismatch():
    now = datetime.now(timezone.utc)
    snap = MarketSnapshot(
        snapshot_id="ev-1",
        symbol="BTCUSDT",
        direction="LONG",
        trigger_price_now="66000",
        trigger_price_ref="65000",
        trigger_change_pct="1.54",
        window_seconds=180,
        detected_at=now,
        exchange_event_time=now,
        last_price="66000",
    )
    client = ThreeRouterClient(api_key="configured-key")
    # Even if Agent 6 LLM would say YES, mandatory Agent 5 = NO must force deterministic NO without calling LLM
    client._post = AsyncMock(side_effect=AssertionError("Agent 6 LLM must not override mandatory NO"))
    orch = AIOrchestrator(client=client)
    prior = {}
    for idx in range(1, 6):
        ag = f"agent-{idx}"
        prior[ag] = {
            "status": "success",
            "latency_ms": 12,
            "response": AgentResponse(
                agent_name=ag,
                schema_version="1.0",
                symbol="BTCUSDT",
                direction="LONG",
                decision="NO" if idx == 5 else "YES",
                confidence=0.8,
                rationale="test",
                created_at=now,
            ),
        }
    final = await orch.run_agent_6(snap, prior)
    assert final.decision == "NO"

    # Symbol mismatch from untrusted LLM must raise ValueError
    mismatched_client = ThreeRouterClient(api_key="configured-key")
    mismatched_client._post = AsyncMock(
        return_value={
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "agent_name": "agent-1",
                                "schema_version": "1.0",
                                "symbol": "ETHUSDT",
                                "direction": "LONG",
                                "decision": "YES",
                                "confidence": 0.9,
                                "rationale": "wrong symbol",
                                "created_at": now.isoformat(),
                            }
                        )
                    }
                }
            ]
        }
    )
    with pytest.raises(ValueError, match="symbol mismatch"):
        await mismatched_client.call_agent("agent-1", snap)
    await client.close()
    await mismatched_client.close()


class AmbiguousTimeoutAdapter(MockBinanceAdapter):
    def __init__(self):
        super().__init__()
        self.create_calls = 0

    async def create_order(self, *args, **kwargs):
        self.create_calls += 1
        raise httpx.ReadTimeout("Submit timed out")

    async def query_order(self, *args, **kwargs):
        raise httpx.ConnectError("Query also unreachable")


@pytest.mark.asyncio
async def test_execution_never_retries_when_query_order_is_ambiguous(db_session):
    settings = Settings()
    risk = RiskEngine(settings)
    adapter = AmbiguousTimeoutAdapter()
    exec_engine = ExecutionEngine(adapter, risk, db_session, settings)
    now = datetime.now(timezone.utc)
    cand = SignalCandidate(
        id="cand-ambig",
        event_key="BTCUSDT:LONG:ambig",
        symbol="BTCUSDT",
        direction="LONG",
        current_price=Decimal("65000"),
        reference_price=Decimal("64000"),
        change_pct=Decimal("1.56"),
        window_seconds=180,
        detected_at=now,
        exchange_event_time=now,
        expires_at=now + timedelta(seconds=30),
        status="APPROVED",
    )
    db_session.add(cand)
    db_session.commit()
    meta = SymbolMetadataDTO(
        symbol="BTCUSDT",
        status="TRADING",
        contract_type="PERPETUAL",
        margin_asset="USDT",
        price_tick=Decimal("0.1"),
        qty_step=Decimal("0.001"),
        min_qty=Decimal("0.001"),
        max_qty=Decimal("100"),
        min_notional=Decimal("5"),
        price_precision=1,
        quantity_precision=3,
    )
    plan = risk.plan_position(
        "BTCUSDT", "LONG", Decimal("65000"), Decimal("64500"), Decimal("66000"), meta, Decimal("100"), leverage=10
    )
    trade = await exec_engine.execute_entry(cand, plan, "BTCUSDT", "LONG")
    assert trade is None
    # CRITICAL: must NOT retry create_order when query_order itself timed out / failed ambiguously
    assert adapter.create_calls == 1
    failed_row = db_session.query(Trade).filter_by(candidate_id="cand-ambig").one()
    assert failed_row.status == "FAILED"
    assert failed_row.close_reason == "ambiguous_order_state"


class FlakySLAdapter(MockBinanceAdapter):
    def __init__(self):
        super().__init__()
        self.sl_attempts = 0

    async def create_order(self, symbol, side, order_type, quantity, **kwargs):
        if order_type == "STOP_MARKET":
            self.sl_attempts += 1
            if self.sl_attempts == 1:
                raise RuntimeError("Transient SL placement failure")
        return await super().create_order(symbol, side, order_type, quantity, **kwargs)


@pytest.mark.asyncio
async def test_protection_repair_and_close_reconciliation_cleanup(db_session):
    settings = Settings(protection_deadline_seconds=1)
    risk = RiskEngine(settings)
    adapter = FlakySLAdapter()
    exec_engine = ExecutionEngine(adapter, risk, db_session, settings)
    monitor = PositionMonitor(adapter, db_session, exec_engine)

    now = datetime.now(timezone.utc)
    cand = SignalCandidate(
        id="cand-repair",
        event_key="BTCUSDT:LONG:repair",
        symbol="BTCUSDT",
        direction="LONG",
        current_price=Decimal("65000"),
        reference_price=Decimal("64000"),
        change_pct=Decimal("1.56"),
        window_seconds=180,
        detected_at=now,
        exchange_event_time=now,
        expires_at=now + timedelta(seconds=30),
        status="APPROVED",
    )
    db_session.add(cand)
    db_session.commit()
    meta = adapter.symbols[0]
    plan = risk.plan_position(
        "BTCUSDT", "LONG", Decimal("65000"), Decimal("64500"), Decimal("66000"), meta, Decimal("100"), leverage=10
    )

    trade = await exec_engine.execute_entry(cand, plan, "BTCUSDT", "LONG")
    assert trade is not None
    # Initial SL failed, repair_attempt=1 succeeded -> PROTECTED without emergency flatten!
    assert adapter.sl_attempts == 2
    assert trade.status == "PROTECTED"

    # Simulate position closing on exchange (e.g., TP filled) while residual SL remains open
    adapter.positions = [
        PositionDTO(
            symbol="BTCUSDT",
            position_amt=Decimal("0"),
            entry_price=Decimal("65000"),
            mark_price=Decimal("66000"),
            unrealized_profit=Decimal("0"),
            leverage=10,
            margin_type="cross",
        )
    ]
    trade.realized_pnl = Decimal("8.0")
    db_session.commit()

    await monitor.reconcile_all()
    assert trade.status == "CLOSED"
    # Residual bot SL/TP orders must be canceled by OrderCleaner
    open_after = await adapter.get_open_orders("BTCUSDT")
    assert len(open_after) == 0
    # EquitySnapshot and MarginScalingEvent recorded
    assert db_session.query(EquitySnapshot).count() >= 1
    ev = db_session.query(MarginScalingEvent).filter_by(closed_trade_id=trade.id).one()
    assert ev.next_margin == Decimal("5.00")


def test_logout_revokes_token_and_signals_alias_works():
    _login_attempts.clear()
    client = TestClient(app)
    login = client.post("/api/auth/login", json={"username": "admin", "password": "test-password"})
    assert login.status_code == 200
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Verify /api/signals alias, /api/audit-logs, and /api/config extended validation
    assert client.get("/api/signals", headers=headers).status_code == 200
    assert client.get("/api/audit-logs", headers=headers).status_code == 200
    bad_cfg = client.put("/api/config", headers=headers, json={"daily_loss_limit": "-5"})
    assert bad_cfg.status_code == 400

    # Logout revokes JTI immediately
    out = client.post("/api/auth/logout", headers=headers)
    assert out.status_code == 200
    after = client.get("/api/engine/status", headers=headers)
    assert after.status_code == 401


def test_alembic_upgrade_downgrade_roundtrip(tmp_path: Path, monkeypatch):
    orig_db_url = get_settings().database_url
    nested_db = tmp_path / "subdir" / "migrations.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{nested_db.as_posix()}")
    get_settings.cache_clear()
    try:
        backend_dir = Path(__file__).resolve().parents[1]
        cfg = AlembicConfig(str(backend_dir / "alembic.ini"))
        cfg.set_main_option("script_location", str(backend_dir / "alembic"))

        command.upgrade(cfg, "head")
        with sqlite3.connect(nested_db) as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "trades" in tables and "app_config" in tables and "orders" in tables

        command.downgrade(cfg, "base")
        with sqlite3.connect(nested_db) as conn:
            tables_after = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "trades" not in tables_after

        command.upgrade(cfg, "head")
    finally:
        monkeypatch.setenv("DATABASE_URL", orig_db_url)
        get_settings.cache_clear()
