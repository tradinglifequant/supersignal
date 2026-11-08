from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import logging
import time
from typing import Callable, Dict, List, Optional
import websockets

from app.core.config import Settings
from app.market.price_history import PriceHistory

logger = logging.getLogger(__name__)

WS_BASE_MAIN = "wss://fstream.binance.com"
WS_BASE_TESTNET = "wss://stream.binancefuture.com"
MAX_STREAMS_PER_CONNECTION = 200

_MOCK_BASE_PRICES: Dict[str, Decimal] = {
    "BTCUSDT": Decimal("65000.0"),
    "ETHUSDT": Decimal("2500.00"),
    "SOLUSDT": Decimal("150.00"),
    "BNBUSDT": Decimal("600.00"),
}


class MarketDataWebSocketManager:
    """
    Async WebSocket market data listener.
    - Shards subscriptions to stay under stream limits
    - Reconnect with exponential backoff + jitter
    - Bounded queue
    - Stale detection
    - Supports local mock stream mode when running with MockBinanceAdapter
    """

    def __init__(
        self,
        price_history: PriceHistory,
        settings: Settings,
        on_price: Optional[Callable] = None,
        mock_mode: bool = False,
    ):
        self.history = price_history
        self.settings = settings
        self.on_price = on_price
        self.mock_mode = mock_mode
        self.symbols: List[str] = []
        self.running = False
        self.connected = False
        self.tasks: List[asyncio.Task] = []
        self.ws_url_base = WS_BASE_TESTNET if settings.binance_testnet else WS_BASE_MAIN
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=10000)
        self.reconnect_attempts = 0
        self.dropped_ticks = 0
        self._last_drop_log_mono = 0.0

    def set_symbols(self, symbols: List[str]):
        self.symbols = [s.lower() for s in symbols]

    def _build_streams(self) -> List[str]:
        return [f"{s}@aggTrade" for s in self.symbols]

    async def start(self):
        if self.running:
            return
        self.running = True
        if self.mock_mode:
            if not self.symbols:
                logger.warning("No symbols to subscribe in mock mode")
                return
            self.tasks.append(asyncio.create_task(self._dispatch_loop()))
            self.tasks.append(asyncio.create_task(self._run_mock_feed()))
            logger.info("Started mock market data feed for %d symbols", len(self.symbols))
            return

        streams = self._build_streams()
        shards = [streams[i : i + MAX_STREAMS_PER_CONNECTION] for i in range(0, len(streams), MAX_STREAMS_PER_CONNECTION)]
        if not shards:
            logger.warning("No symbols to subscribe")
            return
        # architecture.md: a dedicated consumer drains the bounded queue. Dispatching
        # inline from the socket read loop let one slow candidate pipeline stall price
        # ingestion for every symbol and could get the shard disconnected.
        self.tasks.append(asyncio.create_task(self._dispatch_loop()))
        for idx, shard in enumerate(shards):
            task = asyncio.create_task(self._run_shard(idx, shard))
            self.tasks.append(task)
        logger.info("Started %d WS shards covering %d streams", len(shards), len(streams))

    async def _dispatch_loop(self):
        """Single consumer for the bounded tick queue; preserves per-feed ordering."""
        while self.running:
            try:
                symbol, price, exchange_time = await asyncio.wait_for(self.queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            if self.on_price is None:
                continue
            try:
                res = self.on_price(symbol, price, exchange_time)
                if asyncio.iscoroutine(res):
                    await res
            except Exception as e:
                logger.error("on_price callback error: %s", e)

    async def stop(self):
        self.running = False
        self.connected = False
        for t in self.tasks:
            t.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()
        logger.info("WS manager stopped")

    async def _run_mock_feed(self):
        """Local deterministic mock feed for development without real exchange WebSocket."""
        self.connected = True
        upper_symbols = [s.upper() for s in self.symbols]
        now = datetime.now(timezone.utc)
        mono = time.monotonic()
        # Seed strictly monotonic historical samples every 2s across the lookback window
        for offset_sec in range(self.settings.trigger_window_seconds, -1, -2):
            ts = now - timedelta(seconds=offset_sec)
            m_ts = max(0.0, mono - float(offset_sec))
            for sym in upper_symbols:
                base = _MOCK_BASE_PRICES.get(sym, Decimal("100.00"))
                self.history.add(sym, base, ts, receipt_mono=m_ts, receipt_wall=ts)

        step = 0
        # Deterministic micro-oscillation bps per tick, with periodic 1.6% impulse for pipeline demonstration
        pattern_bps = [Decimal("8"), Decimal("-4"), Decimal("12"), Decimal("6"), Decimal("-5"), Decimal("10")]
        try:
            while self.running:
                await asyncio.sleep(2.0)
                if not self.running:
                    break
                step += 1
                tick_now = datetime.now(timezone.utc)
                for idx, sym in enumerate(upper_symbols):
                    base = _MOCK_BASE_PRICES.get(sym, Decimal("100.00"))
                    delta_bps = pattern_bps[(step + idx) % len(pattern_bps)] * Decimal((step % 5) + 1)
                    # Every 6th step (~12s), let the rotating symbol exhibit a +1.60% move to exercise candidate pipeline
                    if step % 6 == 0 and idx == ((step // 6) % len(upper_symbols)):
                        price = (base * Decimal("1.016")).quantize(Decimal("0.01"))
                    else:
                        price = (base * (Decimal("1") + delta_bps / Decimal("10000"))).quantize(Decimal("0.01"))
                    await self._handle_message(
                        {
                            "e": "aggTrade",
                            "s": sym,
                            "p": str(price),
                            "T": int(tick_now.timestamp() * 1000),
                        }
                    )
        except asyncio.CancelledError:
            pass
        finally:
            self.connected = False

    async def _run_shard(self, shard_id: int, streams: List[str]):
        backoff = 1
        while self.running:
            url = f"{self.ws_url_base}/stream?streams={'/'.join(streams)}"
            try:
                logger.info("Connecting WS shard %d url=%s...", shard_id, url[:120])
                async with websockets.connect(url, ping_interval=20, ping_timeout=20, max_queue=1000) as ws:
                    logger.info("WS shard %d connected", shard_id)
                    self.connected = True
                    self.reconnect_attempts = 0
                    backoff = 1
                    async for raw in ws:
                        if not self.running:
                            break
                        try:
                            msg = json.loads(raw)
                            data = msg.get("data", msg)
                            await self._handle_message(data)
                        except Exception as e:
                            logger.error("WS message error shard %d: %s", shard_id, e)
                            continue
            except asyncio.CancelledError:
                logger.info("WS shard %d cancelled", shard_id)
                break
            except Exception as e:
                self.connected = False
                logger.error("WS shard %d error: %s, reconnect in %ds", shard_id, e, backoff)
                await asyncio.sleep(backoff + (0.5 * (backoff % 2)))
                backoff = min(backoff * 2, 60)
                self.reconnect_attempts += 1
                if self.reconnect_attempts > 10:
                    logger.critical("WS max reconnect attempts exceeded, marking degraded")
                continue

    async def _handle_message(self, data: dict):
        event_type = data.get("e", "")
        symbol = data.get("s", "")
        if not symbol:
            return
        symbol = symbol.upper()
        price = None
        event_time_ms = data.get("E") or data.get("T") or int(datetime.now(timezone.utc).timestamp() * 1000)
        exchange_time = datetime.fromtimestamp(event_time_ms / 1000, tz=timezone.utc)

        if event_type == "aggTrade":
            price = Decimal(str(data.get("p", "0")))
        elif event_type == "24hrTicker":
            price = Decimal(str(data.get("c", "0")))
        elif "c" in data and "s" in data:
            price = Decimal(str(data.get("c", "0")))
        elif "p" in data:
            price = Decimal(str(data["p"]))
        else:
            return

        if price is None or price <= Decimal("0"):
            return

        receipt_mono = time.monotonic()
        receipt_wall = datetime.now(timezone.utc)
        # Price history is always updated, so a dropped dispatch never loses trigger data.
        self.history.add(symbol, price, exchange_time, receipt_mono, receipt_wall)
        try:
            self.queue.put_nowait((symbol, price, exchange_time))
        except asyncio.QueueFull:
            # Drop the OLDEST pending tick and keep the newest. Count the drops and log
            # at most once a minute: on a saturated feed the previous per-tick warning
            # flooded the log at thousands of lines per second.
            try:
                self.queue.get_nowait()
                self.queue.put_nowait((symbol, price, exchange_time))
            except Exception:
                pass
            self.dropped_ticks += 1
            if receipt_mono - self._last_drop_log_mono >= 60.0:
                self._last_drop_log_mono = receipt_mono
                logger.warning(
                    "Market data queue saturated; %d tick dispatch(es) dropped in the last interval",
                    self.dropped_ticks,
                )
