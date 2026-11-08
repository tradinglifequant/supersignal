from __future__ import annotations

import time
from collections import deque, defaultdict
from decimal import Decimal
from typing import Dict, Deque, Optional, Tuple
from datetime import datetime, timezone, timedelta
import logging

logger = logging.getLogger(__name__)

class PriceSample:
    __slots__ = ("price", "exchange_time", "receipt_time_mono", "receipt_time_wall")
    def __init__(self, price: Decimal, exchange_time: datetime, receipt_mono: float, receipt_wall: datetime):
        self.price = price
        self.exchange_time = exchange_time
        self.receipt_time_mono = receipt_mono
        self.receipt_time_wall = receipt_wall

class PriceHistory:
    """
    Per-symbol ring buffer for rolling window.
    Stores timestamped last-price samples.
    Uses receipt monotonic time to guard against stale local clock, and exchange event time for trigger.
    History kept for window + grace (e.g., 300s).
    """

    def __init__(self, max_age_seconds: int = 300):
        self.max_age = max_age_seconds
        # symbol -> deque[PriceSample]
        self.buffers: Dict[str, Deque[PriceSample]] = defaultdict(lambda: deque(maxlen=5000))
        # staleness tracking
        self.last_update_wall: Dict[str, datetime] = {}
        self.last_update_mono: Dict[str, float] = {}

    def add(self, symbol: str, price: Decimal, exchange_time: datetime, receipt_mono: float | None = None, receipt_wall: datetime | None = None):
        if receipt_mono is None:
            receipt_mono = time.monotonic()
        if receipt_wall is None:
            receipt_wall = datetime.now(timezone.utc)
        if exchange_time.tzinfo is None:
            exchange_time = exchange_time.replace(tzinfo=timezone.utc)
        sample = PriceSample(price=price, exchange_time=exchange_time, receipt_mono=receipt_mono, receipt_wall=receipt_wall)
        buf = self.buffers[symbol]
        # out-of-order detection: if last sample has later exchange_time, log and still append but keep sorted?
        if buf and buf[-1].exchange_time > exchange_time:
            logger.warning(f"Out-of-order tick {symbol}: last={buf[-1].exchange_time} new={exchange_time} price={price}")
            # Insert in order? Simpler to append and let lookup handle nearest; but we keep chronological by exchange_time.
            # For simplicity, append anyway; lookup will search for correct window sample.
            pass
        buf.append(sample)
        self.last_update_wall[symbol] = receipt_wall
        self.last_update_mono[symbol] = receipt_mono
        # Evict old by receipt wall time beyond max_age
        self._evict_old(symbol, receipt_wall)

    def _evict_old(self, symbol: str, now_wall: datetime):
        buf = self.buffers[symbol]
        cutoff = now_wall - timedelta(seconds=self.max_age)
        while buf and buf[0].receipt_time_wall < cutoff:
            buf.popleft()

    def get_last_price(self, symbol: str) -> Optional[PriceSample]:
        buf = self.buffers.get(symbol)
        if not buf:
            return None
        return buf[-1]

    def get_reference_price(self, symbol: str, window_seconds: int, now_wall: datetime) -> Optional[PriceSample]:
        """
        Find valid sample at or before (now - window). Require sample within tolerance.
        Tolerance: window boundary +- 5 seconds, but must not be stale >60s.
        """
        buf = self.buffers.get(symbol)
        if not buf:
            return None
        target_time = now_wall - timedelta(seconds=window_seconds)
        # Find latest sample with exchange_time <= target_time and not too old relative to target
        # Allow interpolation/nearest-sample: pick closest sample within 10s before target.
        best: Optional[PriceSample] = None
        best_delta = None
        tolerance = timedelta(seconds=10)

        for sample in reversed(buf):
            if sample.exchange_time <= target_time:
                delta = target_time - sample.exchange_time
                if delta <= tolerance:
                    return sample
                # If too old, break (since reversed, older will be even further)
                # but we continue to find any within tolerance; if none, return None
                if best is None or delta < best_delta:  # type: ignore
                    best = sample
                    best_delta = delta
                break

        # If best beyond tolerance, we consider missing (per FR-02)
        if best and best_delta and best_delta <= timedelta(seconds=30):
            # Allow slightly larger tolerance for sparse data but log warning
            logger.debug(f"Reference sample for {symbol} is {best_delta} before window - accepting with warning")
            return best
        return None

    def is_stale(self, symbol: str, now_wall: datetime, stale_threshold_seconds: int = 60) -> bool:
        lut = self.last_update_wall.get(symbol)
        if not lut:
            return True
        return (now_wall - lut) > timedelta(seconds=stale_threshold_seconds)

    def coverage(self) -> int:
        return len([s for s, buf in self.buffers.items() if buf])
