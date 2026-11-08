"""Regression tests for the second full-code audit.

Each test here pins a defect that was found by reading the code end to end and
reproducing it against a running app, so the behaviour cannot silently regress.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import uuid

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.db.base import Base
from app.db.models import (
    ACTIVE_TRADE_STATUSES,
    EquitySnapshot,
    Trade,
    net_realized_pnl,
)
from app.db.session import get_sync_session_factory
from app.exchange.interface import PositionDTO
from app.exchange.mock_adapter import MockBinanceAdapter
from app.execution.execution_engine import ExecutionEngine
from app.main import app
from app.market.price_history import PriceHistory
from app.market.websocket_manager import MarketDataWebSocketManager
from app.monitor.position_monitor import PositionMonitor
from app.risk.risk_engine import RiskEngine

client = TestClient(app)


def _auth_headers() -> dict:
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "test-password"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _make_trade(**overrides) -> Trade:
    fields = dict(
        id=str(uuid.uuid4()),
        symbol="BTCUSDT",
        side="BUY",
        direction="LONG",
        entry_order_client_id=f"x-{uuid.uuid4().hex[:20]}-entry",
        margin_allocation=Decimal("3"),
        leverage=10,
        status="OPEN",
        created_at=datetime.now(timezone.utc),
    )
    fields.update(overrides)
    return Trade(**fields)


@pytest.fixture
def clean_trading_rows():
    """Remove trading rows so each test sees a deterministic dataset."""
    factory = get_sync_session_factory()
    s = factory()
    try:
        for model in (EquitySnapshot, Trade):
            for row in s.query(model).all():
                s.delete(row)
        s.commit()
    finally:
        s.close()
    yield
    s = factory()
    try:
        for model in (EquitySnapshot, Trade):
            for row in s.query(model).all():
                s.delete(row)
        s.commit()
    finally:
        s.close()


# --------------------------------------------------------------------------
# /api/metrics/equity-curve must return the newest points, not the oldest
# --------------------------------------------------------------------------


def test_equity_curve_returns_most_recent_points(clean_trading_rows):
    factory = get_sync_session_factory()
    s = factory()
    base = datetime.now(timezone.utc) - timedelta(hours=3)
    for i in range(150):
        s.add(
            EquitySnapshot(
                id=str(uuid.uuid4()),
                wallet_balance=Decimal("1000"),
                account_equity=Decimal(1000 + i),
                available_balance=Decimal("900"),
                unrealized_pnl=Decimal("0"),
                captured_at=base + timedelta(seconds=i * 10),
            )
        )
    s.commit()
    s.close()

    rows = client.get("/api/metrics/equity-curve", headers=_auth_headers()).json()
    assert len(rows) == 100
    # Oldest-first ordering for the chart, but the *tail* of the series.
    equities = [Decimal(r["account_equity"]) for r in rows]
    assert equities == sorted(equities)
    assert equities[-1] == Decimal("1149.00000000")
    assert equities[0] == Decimal("1050.00000000")


def test_equity_curve_limit_is_validated(clean_trading_rows):
    headers = _auth_headers()
    assert client.get("/api/metrics/equity-curve?limit=0", headers=headers).status_code == 422


# --------------------------------------------------------------------------
# Per-symbol performance must agree with the headline win/loss accounting
# --------------------------------------------------------------------------


def test_performance_matches_metrics_after_fees(clean_trading_rows):
    factory = get_sync_session_factory()
    s = factory()
    s.add(
        _make_trade(
            realized_pnl=Decimal("1.0"),
            fees=Decimal("2.0"),
            funding=Decimal("0"),
            status="CLOSED",
            closed_at=datetime.now(timezone.utc),
        )
    )
    s.commit()
    s.close()

    headers = _auth_headers()
    perf = client.get("/api/metrics/performance", headers=headers).json()["BTCUSDT"]
    metrics = client.get("/api/metrics", headers=headers).json()

    assert perf["wins"] == 0, "gross P&L is positive but the trade lost money after fees"
    assert perf["losses"] == 1
    assert Decimal(perf["pnl"]) == Decimal("-1.00000000")
    assert metrics["losing_trades"] == 1
    assert metrics["winning_trades"] == 0


def test_net_realized_pnl_helper():
    t = _make_trade(realized_pnl=Decimal("5"), fees=Decimal("1.5"), funding=Decimal("0.25"))
    assert net_realized_pnl(t) == Decimal("3.25")
    assert net_realized_pnl(_make_trade(realized_pnl=None)) == Decimal("0")


# --------------------------------------------------------------------------
# One definition of "open position" across the API, the engine and the monitor
# --------------------------------------------------------------------------


def test_active_statuses_are_shared_and_cover_in_flight_exposure():
    assert ACTIVE_TRADE_STATUSES == ("PENDING", "OPEN", "PROTECTED", "CLOSING")


def test_positions_and_engine_status_include_pending_and_closing(clean_trading_rows):
    factory = get_sync_session_factory()
    s = factory()
    pending = _make_trade(symbol="ETHUSDT", status="PENDING")
    closing = _make_trade(symbol="SOLUSDT", status="CLOSING")
    protected = _make_trade(symbol="BNBUSDT", status="PROTECTED")
    failed = _make_trade(symbol="XRPUSDT", status="FAILED")
    for t in (pending, closing, protected, failed):
        s.add(t)
    s.commit()
    s.close()

    headers = _auth_headers()
    listed = client.get("/api/positions?status=OPEN", headers=headers).json()
    listed_symbols = {row["symbol"] for row in listed}
    assert listed_symbols == {"ETHUSDT", "SOLUSDT", "BNBUSDT"}
    assert "XRPUSDT" not in listed_symbols

    status = client.get("/api/engine/status", headers=headers).json()
    assert status["open_positions"] == 3

    metrics = client.get("/api/metrics", headers=headers).json()
    assert metrics["open_positions"] == 3


def test_trade_response_exposes_funding(clean_trading_rows):
    factory = get_sync_session_factory()
    s = factory()
    trade = _make_trade(
        realized_pnl=Decimal("4"),
        fees=Decimal("1"),
        funding=Decimal("0.5"),
        status="CLOSED",
        closed_at=datetime.now(timezone.utc),
    )
    s.add(trade)
    s.commit()
    trade_id = trade.id
    s.close()

    row = client.get(f"/api/trades/{trade_id}", headers=_auth_headers()).json()
    assert row["funding"] == "0.50000000"


# --------------------------------------------------------------------------
# Market feed: bounded queue with a dedicated consumer, no per-tick log flood
# --------------------------------------------------------------------------


def _agg_trade(symbol: str, price: str, ts_ms: int) -> dict:
    return {"e": "aggTrade", "s": symbol, "p": price, "T": ts_ms}


@pytest.mark.asyncio
async def test_saturated_queue_drops_oldest_and_counts_without_raising():
    settings = get_settings()
    history = PriceHistory(max_age_seconds=600)
    received: list[tuple[str, Decimal]] = []

    async def on_price(symbol, price, _exchange_time):
        received.append((symbol, price))

    mgr = MarketDataWebSocketManager(history, settings, on_price=on_price, mock_mode=True)
    mgr.queue = asyncio.Queue(maxsize=2)

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    for i in range(50):
        await mgr._handle_message(_agg_trade("BTCUSDT", str(100 + i), now_ms + i))

    # 2 fit, the remaining 48 each evict the oldest pending tick.
    assert mgr.dropped_ticks == 48
    assert mgr.queue.qsize() == 2
    assert mgr.queue.get_nowait()[1] == Decimal("148")
    assert mgr.queue.get_nowait()[1] == Decimal("149")

    # Trigger data is never lost: price history still holds every sample.
    assert len(history.buffers["BTCUSDT"]) == 50
    assert received == []  # nothing dispatched until the consumer runs


@pytest.mark.asyncio
async def test_dispatch_loop_delivers_ticks_in_order():
    settings = get_settings()
    history = PriceHistory(max_age_seconds=600)
    received: list[Decimal] = []

    async def on_price(_symbol, price, _exchange_time):
        received.append(price)

    mgr = MarketDataWebSocketManager(history, settings, on_price=on_price, mock_mode=True)
    mgr.running = True
    task = asyncio.create_task(mgr._dispatch_loop())

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    for i in range(5):
        await mgr._handle_message(_agg_trade("ETHUSDT", str(2000 + i), now_ms + i))

    for _ in range(200):
        if len(received) == 5:
            break
        await asyncio.sleep(0.01)

    mgr.running = False
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert received == [Decimal(str(2000 + i)) for i in range(5)]


# --------------------------------------------------------------------------
# Position monitor must not rebind the shared ExecutionEngine session
# --------------------------------------------------------------------------


class _NoPositionAdapter(MockBinanceAdapter):
    async def get_positions(self) -> list[PositionDTO]:
        return []


@pytest.mark.asyncio
async def test_monitor_iteration_does_not_rebind_shared_execution_engine(tmp_path):
    """A poll iteration must own its session privately.

    Previously the loop assigned the shared EngineService ExecutionEngine's
    session, so a concurrent price tick could swap it mid-reconciliation and the
    protection-repair commit would land on a session that did not own the Trade.
    """
    url = f"sqlite:///{(tmp_path / 'monitor.sqlite').as_posix()}"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    shared = factory()
    iteration = factory()
    trade = _make_trade(status="PROTECTED")
    iteration.add(trade)
    iteration.commit()
    trade_id = trade.id

    adapter = _NoPositionAdapter()
    settings = get_settings()
    shared_exec = ExecutionEngine(adapter, RiskEngine(settings), shared, settings)
    monitor = PositionMonitor(adapter, shared, shared_exec, session_factory=factory)

    await monitor.reconcile_all(
        db=iteration,
        exec_engine=ExecutionEngine(adapter, RiskEngine(settings), iteration, settings),
    )

    refreshed = factory()
    row = refreshed.query(Trade).filter(Trade.id == trade_id).first()
    assert row.status == "CLOSED", "exchange-flat position must be reconciled to CLOSED"
    refreshed.close()

    # The shared execution engine still points at the session it was built with.
    assert shared_exec.db is shared
    assert monitor.exec_engine.db is shared
    assert monitor.db is shared

    iteration.close()
    shared.close()


@pytest.mark.asyncio
async def test_monitor_loop_iteration_uses_a_private_session(tmp_path):
    url = f"sqlite:///{(tmp_path / 'loop.sqlite').as_posix()}"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    shared = factory()
    writer = factory()
    trade = _make_trade(status="PROTECTED")
    writer.add(trade)
    writer.commit()
    trade_id = trade.id
    writer.close()

    adapter = _NoPositionAdapter()
    settings = get_settings()
    shared_exec = ExecutionEngine(adapter, RiskEngine(settings), shared, settings)
    monitor = PositionMonitor(
        adapter, shared, shared_exec, poll_interval=3600, session_factory=factory
    )

    await monitor.start()
    for _ in range(200):
        checker = factory()
        row = checker.query(Trade).filter(Trade.id == trade_id).first()
        done = row is not None and row.status == "CLOSED"
        checker.close()
        if done:
            break
        await asyncio.sleep(0.02)
    await monitor.stop()

    assert done, "monitor loop must reconcile the flat position using its own session"
    assert shared_exec.db is shared, "loop must not rebind the shared execution engine"
    shared.close()


# --------------------------------------------------------------------------
# Relative SQLite URLs must not depend on the process working directory
# --------------------------------------------------------------------------


def test_relative_sqlite_url_is_anchored_to_the_repository_root():
    from pathlib import Path

    from app.core.config import Settings

    repo_root = Path(__file__).resolve().parents[2]
    for raw in ("sqlite:///./data/supersignal.db", "sqlite:///data/supersignal.db"):
        resolved = Settings(database_url=raw).database_url
        assert resolved == f"sqlite:///{(repo_root / 'data' / 'supersignal.db').as_posix()}"

    # Absolute URLs and non-SQLite backends are untouched.
    untouched = [
        "sqlite:////var/lib/supersignal/app.db",
        "sqlite:///:memory:",
        "postgresql+psycopg://user:pw@host:5432/db",
    ]
    for url in untouched:
        assert Settings(database_url=url).database_url == url


# --------------------------------------------------------------------------
# A persisted RUNNING state must not survive a process restart
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "persisted",
    ["STARTING", "READY", "RUNNING", "STOPPING", "DEGRADED", "EMERGENCY"],
)
def test_stale_active_state_is_reset_on_restart(tmp_path, persisted):
    from app.core.config import get_settings as _get_settings
    from app.db.models import EngineStateRecord
    from app.engine.state_machine import RESTART_RESET_REASON, EngineStateMachine

    engine = create_engine(f"sqlite:///{(tmp_path / 'state.sqlite').as_posix()}")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()

    session.add(
        EngineStateRecord(
            id=str(uuid.uuid4()),
            state=persisted,
            environment="development",
            changed_at=datetime.now(timezone.utc),
            reason="persisted before restart",
        )
    )
    session.commit()

    machine = EngineStateMachine(session, _get_settings())
    assert machine.state == "STOPPED", f"{persisted} must not be restored as an active state"
    assert machine.get_history(limit=1)[0].reason == RESTART_RESET_REASON

    # The operator can start again instead of being told it is already running.
    assert machine.can_transition("STARTING")
    session.close()


@pytest.mark.parametrize("persisted", ["STOPPED", "HALTED_RISK", "ERROR"])
def test_terminal_and_halted_states_are_preserved_on_restart(tmp_path, persisted):
    from app.core.config import get_settings as _get_settings
    from app.db.models import EngineStateRecord
    from app.engine.state_machine import EngineStateMachine

    engine = create_engine(f"sqlite:///{(tmp_path / 'state2.sqlite').as_posix()}")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    session.add(
        EngineStateRecord(
            id=str(uuid.uuid4()),
            state=persisted,
            environment="development",
            changed_at=datetime.now(timezone.utc),
            reason="needs explicit operator recovery",
        )
    )
    session.commit()

    assert EngineStateMachine(session, _get_settings()).state == persisted
    session.close()
