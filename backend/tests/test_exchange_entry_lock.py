"""Real exchange entries remain locked until the trading safety gates are implemented."""
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
import app.db.models  # register models
from app.engine.service import EngineService
from app.exchange.binance_adapter import BinanceAdapter, EntryLockedError


@pytest.mark.asyncio
@pytest.mark.parametrize("testnet", [True, False])
@pytest.mark.parametrize("order_type", ["MARKET", "LIMIT", "STOP_MARKET"])
async def test_real_adapter_blocks_new_exposure_before_network(testnet, order_type):
    adapter = BinanceAdapter(api_key="key", api_secret="secret", testnet=testnet)
    adapter._request = AsyncMock()
    try:
        with pytest.raises(EntryLockedError):
            await adapter.create_order("BTCUSDT", "BUY", order_type, Decimal("1"))
        adapter._request.assert_not_awaited()
    finally:
        await adapter.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("testnet", [True, False])
@pytest.mark.parametrize("flag", ["reduce_only", "close_position"])
async def test_protective_order_path_is_not_blocked(testnet, flag):
    adapter = BinanceAdapter(api_key="key", api_secret="secret", testnet=testnet)
    adapter._request = AsyncMock(return_value={"symbol": "BTCUSDT", "orderId": 1})
    try:
        await adapter.create_order("BTCUSDT", "SELL", "STOP_MARKET", Decimal("1"), **{flag: True})
        adapter._request.assert_awaited_once()
        params = adapter._request.call_args.kwargs["params"]
        assert params["reduceOnly" if flag == "reduce_only" else "closePosition"] == "true"
        if flag == "close_position":
            assert "quantity" not in params
    finally:
        await adapter.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("testnet", [True, False])
async def test_engine_readiness_and_start_block_real_adapter(testnet):
    db_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(db_engine)
    adapter = BinanceAdapter(api_key="key", api_secret="secret", testnet=testnet)
    adapter.test_connectivity = AsyncMock(side_effect=AssertionError("must not call network"))
    try:
        with Session(db_engine) as db:
            engine = EngineService(db, adapter)
            ready, issues = await engine.readiness_checks()
            assert not ready
            assert any("entries are locked" in issue for issue in issues)
            started, issues = await engine.start()
            assert not started
            assert engine.state_machine.state != "RUNNING"
            assert any("entries are locked" in issue for issue in issues)
            adapter.test_connectivity.assert_not_awaited()
            await engine.ai_orchestrator.client.close()
    finally:
        await adapter.close()
        db_engine.dispose()
