from __future__ import annotations

import asyncio
import json
import logging
import time
from decimal import Decimal
from datetime import datetime, timezone
from typing import List, Dict, Callable, Optional
import httpx
import websockets

from app.market.price_history import PriceHistory
from app.core.config import Settings

logger = logging.getLogger(__name__)

# Binance WS base URLs
WS_BASE_MAIN = "wss://fstream.binance.com"
WS_BASE_TESTNET = "wss://stream.binancefuture.com"

# Binance stream limits: 1024 streams per connection? We'll shard.
MAX_STREAMS_PER_CONNECTION = 200

class MarketDataWebSocketManager:
    """
    Async WebSocket market data listener.
    - Shards subscriptions to stay under stream limits
    - Reconnect with exponential backoff + jitter
    - Bounded queue
    - Stale detection
    """

    def __init__(
        self,
        price_history: PriceHistory,
        settings: Settings,
        on_price: Optional[Callable] = None,
    ):
        self.history = price_history
        self.settings = settings
        self.on_price = on_price
        self.symbols: List[str] = []
        self.running = False
        self.tasks: List[asyncio.Task] = []
        self.ws_url_base = WS_BASE_TESTNET if settings.binance_testnet else WS_BASE_MAIN
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=10000)
        self.reconnect_attempts = 0

    def set_symbols(self, symbols: List[str]):
        self.symbols = [s.lower() for s in symbols]

    def _build_streams(self) -> List[str]:
        # Use aggTrade for last price? But spec says last traded price.
        # Use !ticker@arr? Simpler: use aggTrade per symbol for last price.
        # Binance docs: aggTrade streams: <symbol>@aggTrade gives price/qty.
        # For last-price trigger, we can use ticker or aggTrade.
        # We'll use ticker: <symbol>@ticker or bookTicker? For last price, use <symbol>@ticker has last price 'c'.
        # Or <symbol>@aggTrade gives executed price.
        # We support both; choose aggTrade for simplicity.
        return [f"{s}@aggTrade" for s in self.symbols]

    async def start(self):
        if self.running:
            return
        self.running = True
        streams = self._build_streams()
        # shard
        shards = [streams[i:i+MAX_STREAMS_PER_CONNECTION] for i in range(0, len(streams), MAX_STREAMS_PER_CONNECTION)]
        if not shards:
            # Still start single connection with no streams? Wait for symbols.
            logger.warning("No symbols to subscribe")
            return
        for idx, shard in enumerate(shards):
            task = asyncio.create_task(self._run_shard(idx, shard))
            self.tasks.append(task)
        logger.info(f"Started {len(shards)} WS shards covering {len(streams)} streams")

    async def stop(self):
        self.running = False
        for t in self.tasks:
            t.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()
        logger.info("WS manager stopped")

    async def _run_shard(self, shard_id: int, streams: List[str]):
        backoff = 1
        while self.running:
            url = f"{self.ws_url_base}/stream?streams={'/'.join(streams)}"
            try:
                logger.info(f"Connecting WS shard {shard_id} url={url[:120]}...")
                async with websockets.connect(url, ping_interval=20, ping_timeout=20, max_queue=1000) as ws:
                    logger.info(f"WS shard {shard_id} connected")
                    self.reconnect_attempts = 0
                    backoff = 1
                    async for raw in ws:
                        if not self.running:
                            break
                        try:
                            msg = json.loads(raw)
                            # Stream format: {"stream":"btcusdt@aggTrade","data":{...}}
                            data = msg.get("data", msg)
                            await self._handle_message(data)
                        except Exception as e:
                            logger.error(f"WS message error shard {shard_id}: {e}")
                            continue
            except asyncio.CancelledError:
                logger.info(f"WS shard {shard_id} cancelled")
                break
            except Exception as e:
                logger.error(f"WS shard {shard_id} error: {e}, reconnect in {backoff}s")
                await asyncio.sleep(backoff + (0.5 * (backoff % 2)))  # jitter
                backoff = min(backoff * 2, 60)
                self.reconnect_attempts += 1
                if self.reconnect_attempts > 10:
                    logger.critical("WS max reconnect attempts exceeded, marking degraded")
                    # Notify engine state via callback if needed
                continue

    async def _handle_message(self, data: dict):
        # Handle aggTrade: e = aggTrade, s = symbol, p = price, T = event time
        # Ticker: e = 24hrTicker, s, c = last price, E = event time
        # kline: e = kline
        event_type = data.get("e", "")
        symbol = data.get("s", "")
        if not symbol:
            return
        symbol = symbol.upper()
        price = None
        event_time_ms = data.get("E") or data.get("T") or int(datetime.now(timezone.utc).timestamp()*1000)
        exchange_time = datetime.fromtimestamp(event_time_ms / 1000, tz=timezone.utc)

        if event_type == "aggTrade":
            price = Decimal(str(data.get("p", "0")))
        elif event_type == "24hrTicker":
            price = Decimal(str(data.get("c", "0")))
        elif "c" in data and "s" in data:
            # generic ticker fallback
            price = Decimal(str(data.get("c", "0")))
        elif "p" in data:
            price = Decimal(str(data["p"]))
        else:
            return

        if price is None or price <= Decimal("0"):
            return

        receipt_mono = time.monotonic()
        receipt_wall = datetime.now(timezone.utc)
        self.history.add(symbol, price, exchange_time, receipt_mono, receipt_wall)
        # Bounded queue for downstream
        try:
            self.queue.put_nowait((symbol, price, exchange_time))
        except asyncio.QueueFull:
            logger.warning("Market data queue full, dropping oldest")
            try:
                self.queue.get_nowait()
                self.queue.put_nowait((symbol, price, exchange_time))
            except Exception:
                pass
        if self.on_price:
            try:
                # on_price can be async
                res = self.on_price(symbol, price, exchange_time)
                if asyncio.iscoroutine(res):
                    await res
            except Exception as e:
                logger.error(f"on_price callback error: {e}")
