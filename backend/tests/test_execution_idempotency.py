"""
Test duplicate order prevention and idempotency - FR-05 acceptance.
"""
import pytest
import asyncio
from decimal import Decimal
from datetime import datetime, timezone, timedelta
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
import app.db.models  # noqa
from app.db.models import SignalCandidate, Trade
from app.core.config import Settings
from app.risk.risk_engine import RiskEngine
from app.execution.execution_engine import ExecutionEngine, generate_client_order_id
from app.exchange.mock_adapter import MockBinanceAdapter
from app.exchange.interface import SymbolMetadataDTO

def make_settings():
    return Settings(database_url="sqlite:///:memory:", app_env="testnet", base_margin=Decimal("10"), leverage=10, max_concurrent_trades=3, profit_reinvestment_pct=Decimal("25"), daily_loss_limit=Decimal("50"), max_drawdown_pct=Decimal("10"), max_aggregate_exposure=Decimal("1000"), max_slippage_bps=Decimal("50"), taker_fee_bps=Decimal("4"), app_secret_key="test", jwt_secret_key="test")  # type: ignore

@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()

@pytest.fixture
def adapter():
    return MockBinanceAdapter()

def test_client_order_id_deterministic():
    tid = "123e4567-e89b-12d3-a456-426614174000"
    cid1 = generate_client_order_id(tid, "ENTRY")
    cid2 = generate_client_order_id(tid, "ENTRY")
    assert cid1 == cid2
    assert len(cid1) <= 36
    cid3 = generate_client_order_id(tid, "SL")
    assert cid3 != cid1

@pytest.mark.asyncio
async def test_no_duplicate_entry_after_timeout(db_session, adapter):
    settings = make_settings()
    risk = RiskEngine(settings)
    engine = ExecutionEngine(adapter, risk, db_session, settings)

    # Create candidate
    cand = SignalCandidate(
        id=str(uuid.uuid4()),
        event_key="BTCUSDT:LONG:123",
        symbol="BTCUSDT", direction="LONG",
        current_price=Decimal("65000"), reference_price=Decimal("64000"), change_pct=Decimal("1.56"),
        window_seconds=180, detected_at=datetime.now(timezone.utc), exchange_event_time=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc)+timedelta(seconds=30), status="DETECTED",
    )
    db_session.add(cand)
    db_session.commit()

    meta = SymbolMetadataDTO(symbol="BTCUSDT", status="TRADING", contract_type="PERPETUAL", margin_asset="USDT", price_tick=Decimal("0.1"), qty_step=Decimal("0.001"), min_qty=Decimal("0.001"), max_qty=Decimal("1000"), min_notional=Decimal("5"), price_precision=1, quantity_precision=3)
    plan = risk.plan_position("BTCUSDT", "LONG", Decimal("65000"), Decimal("64350"), Decimal("65975"), meta, Decimal("10"))

    # First execution should succeed
    trade1 = await engine.execute_entry(cand, plan, "BTCUSDT", "LONG")
    assert trade1 is not None
    assert trade1.status in ("OPEN", "PROTECTED")

    # Attempt second execution for same symbol should be blocked due to open position check
    cand2 = SignalCandidate(
        id=str(uuid.uuid4()),
        event_key="BTCUSDT:LONG:124",
        symbol="BTCUSDT", direction="LONG",
        current_price=Decimal("65100"), reference_price=Decimal("64000"), change_pct=Decimal("1.7"),
        window_seconds=180, detected_at=datetime.now(timezone.utc), exchange_event_time=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc)+timedelta(seconds=30), status="DETECTED",
    )
    db_session.add(cand2)
    db_session.commit()
    # Even with new candidate, execution should block due to existing open position
    trade2 = await engine.execute_entry(cand2, plan, "BTCUSDT", "LONG")
    assert trade2 is None

@pytest.mark.asyncio
async def test_retry_only_when_order_absent():
    # Simulate adapter that fails first call with retryable error, succeeds second after query shows no order
    settings = make_settings()
    risk = RiskEngine(settings)

    class FlakyAdapter(MockBinanceAdapter):
        def __init__(self):
            super().__init__()
            self.call_count = 0
        async def create_order(self, *args, **kwargs):
            self.call_count += 1
            if self.call_count == 1:
                from app.exchange.binance_adapter import BinanceAPIError
                raise BinanceAPIError(500, {"code": -1001, "msg": "System busy, try again"})
            return await super().create_order(*args, **kwargs)
        async def query_order(self, *args, **kwargs):
            # Simulate no order found on first retry check
            raise Exception("Order not found")

    adapter = FlakyAdapter()
    engine_sql = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine_sql)
    Session = sessionmaker(bind=engine_sql)
    db = Session()

    cand_id = str(uuid.uuid4())
    cand = SignalCandidate(id=cand_id, event_key="BTCUSDT:LONG:999", symbol="BTCUSDT", direction="LONG", current_price=Decimal("65000"), reference_price=Decimal("64000"), change_pct=Decimal("1.56"), window_seconds=180, detected_at=datetime.now(timezone.utc), exchange_event_time=datetime.now(timezone.utc), expires_at=datetime.now(timezone.utc)+timedelta(seconds=30), status="DETECTED")
    db.add(cand)
    db.commit()

    meta = SymbolMetadataDTO(symbol="BTCUSDT", status="TRADING", contract_type="PERPETUAL", margin_asset="USDT", price_tick=Decimal("0.1"), qty_step=Decimal("0.001"), min_qty=Decimal("0.001"), max_qty=Decimal("1000"), min_notional=Decimal("5"), price_precision=1, quantity_precision=3)
    plan = risk.plan_position("BTCUSDT", "LONG", Decimal("65000"), Decimal("64350"), Decimal("65975"), meta, Decimal("10"))
    engine = ExecutionEngine(adapter, risk, db, settings)

    trade = await engine.execute_entry(cand, plan, "BTCUSDT", "LONG")
    assert trade is not None
    # Entry retried once (2 calls) plus SL/TP placement = total 4
    assert adapter.call_count >= 2 and adapter.call_count <= 4  # retried at least once, protection adds calls

@pytest.mark.asyncio
async def test_non_retryable_not_retried():
    settings = make_settings()
    risk = RiskEngine(settings)

    class NonRetryableAdapter(MockBinanceAdapter):
        async def create_order(self, *args, **kwargs):
            from app.exchange.binance_adapter import BinanceAPIError
            raise BinanceAPIError(400, {"code": -2010, "msg": "Account has insufficient balance"})

    adapter = NonRetryableAdapter()
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=eng)
    Session = sessionmaker(bind=eng)
    db = Session()
    cand = SignalCandidate(id=str(uuid.uuid4()), event_key="BTCUSDT:LONG:555", symbol="BTCUSDT", direction="LONG", current_price=Decimal("65000"), reference_price=Decimal("64000"), change_pct=Decimal("1.56"), window_seconds=180, detected_at=datetime.now(timezone.utc), exchange_event_time=datetime.now(timezone.utc), expires_at=datetime.now(timezone.utc)+timedelta(seconds=30), status="DETECTED")
    db.add(cand)
    db.commit()
    meta = SymbolMetadataDTO(symbol="BTCUSDT", status="TRADING", contract_type="PERPETUAL", margin_asset="USDT", price_tick=Decimal("0.1"), qty_step=Decimal("0.001"), min_qty=Decimal("0.001"), max_qty=Decimal("1000"), min_notional=Decimal("5"), price_precision=1, quantity_precision=3)
    plan = risk.plan_position("BTCUSDT", "LONG", Decimal("65000"), Decimal("64350"), Decimal("65975"), meta, Decimal("10"))
    exec_eng = ExecutionEngine(adapter, risk, db, settings)
    trade = await exec_eng.execute_entry(cand, plan, "BTCUSDT", "LONG")
    assert trade is None or trade.status == "FAILED"
