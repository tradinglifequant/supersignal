"""
Adapter + trading-gate construction.

Keeping this in one place matters: the gate is what arms trading, and an adapter
built without one refuses every entry. Two call sites constructing adapters
independently is exactly how a gate gets forgotten.
"""
from __future__ import annotations

import logging

from app.core.config import Settings, get_settings
from app.exchange.binance_adapter import BinanceAdapter
from app.exchange.interface import ExchangeAdapter
from app.exchange.mock_adapter import MockBinanceAdapter
from app.trading.gate import TradingGate

logger = logging.getLogger(__name__)


def build_adapter(settings: Settings | None = None) -> tuple[ExchangeAdapter, TradingGate]:
    """
    Return an adapter that already has a trading gate attached.

    - With real Binance credentials: a BinanceAdapter for the configured
      environment, gated. Whether it may actually place entries is decided by
      ``TRADING_ENV`` / ``LIVE_TRADING_*`` inside the gate, not here.
    - Without credentials: the mock adapter, so local development works with no
      keys at all.
    """
    settings = settings or get_settings()

    if settings.binance_api_key and settings.binance_api_secret:
        adapter: ExchangeAdapter = BinanceAdapter()
        is_testnet = getattr(adapter, "testnet", True)
    else:
        adapter = MockBinanceAdapter()
        # The mock is never a testnet exchange; treat it as testnet-equivalent so
        # the gate evaluates configuration honestly rather than blocking dev.
        is_testnet = True
        logger.info("No Binance credentials configured; using MockBinanceAdapter")

    gate = TradingGate(adapter, settings, is_testnet=is_testnet)
    # Attach unconditionally. `hasattr` is the wrong test here: an adapter class
    # that never declared `gate` would silently skip this and then refuse every
    # entry with a misleading "no trading gate configured" message.
    adapter.gate = gate  # type: ignore[attr-defined]

    logger.info(
        "Trading gate: env=%s testnet=%s portfolio_margin=%s live_armed=%s ai_gate_mode=%s",
        settings.trading_env,
        is_testnet,
        settings.portfolio_margin,
        settings.live_armed,
        settings.ai_gate_mode,
    )
    return adapter, gate
