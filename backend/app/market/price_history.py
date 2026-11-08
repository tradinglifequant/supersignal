from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Deque, Dict, Optional

from app.utils.decimal import calc_change_pct

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
    """

    def __init__(self, max_age_seconds: int = 300):
        self.max_age = max_age_seconds
        self.buffers: Dict[str, Deque[PriceSample]] = defaultdict(lambda: deque(maxlen=5000))
        self.last_update_wall: Dict[str, datetime] = {}
        self.last_update_mono: Dict[str, float] = {}
        self.out_of_order: Dict[str, bool] = {}

    def add(
        self,
        symbol: str,
        price: Decimal,
        exchange_time: datetime,
        receipt_mono: float | None = None,
        receipt_wall: datetime | None = None,
    ):
        if receipt_mono is None:
            receipt_mono = time.monotonic()
        if receipt_wall is None:
            receipt_wall = datetime.now(timezone.utc)
        if exchange_time.tzinfo is None:
            exchange_time = exchange_time.replace(tzinfo=timezone.utc)
        if receipt_wall.tzinfo is None:
            receipt_wall = receipt_wall.replace(tzinfo=timezone.utc)
        sample = PriceSample(
            price=price,
            exchange_time=exchange_time,
            receipt_mono=receipt_mono,
            receipt_wall=receipt_wall,
        )
        buf = self.buffers[symbol]
        if buf and buf[-1].exchange_time > exchange_time:
            logger.warning(
                "Out-of-order tick %s: last=%s new=%s price=%s",
                symbol,
                buf[-1].exchange_time,
                exchange_time,
                price,
            )
            self.out_of_order[symbol] = True
        else:
            self.out_of_order[symbol] = False
        buf.append(sample)
        self.last_update_wall[symbol] = receipt_wall
        self.last_update_mono[symbol] = receipt_mono
        self._evict_old(symbol, receipt_wall)

    def _evict_old(self, symbol: str, now_wall: datetime):
        buf = self.buffers[symbol]
        cutoff = now_wall - timedelta(seconds=self.max_age)
        while buf and buf[0].receipt_time_wall < cutoff:
            buf.popleft()

    def is_out_of_order(self, symbol: str) -> bool:
        return self.out_of_order.get(symbol, False)

    def get_last_price(self, symbol: str) -> Optional[PriceSample]:
        buf = self.buffers.get(symbol)
        if not buf:
            return None
        return buf[-1]

    def get_reference_price(self, symbol: str, window_seconds: int, now_wall: datetime) -> Optional[PriceSample]:
        """
        Find valid sample at or before (now - window) within tolerance.
        """
        buf = self.buffers.get(symbol)
        if not buf:
            return None
        if now_wall.tzinfo is None:
            now_wall = now_wall.replace(tzinfo=timezone.utc)
        target_time = now_wall - timedelta(seconds=window_seconds)
        best: Optional[PriceSample] = None
        best_delta = None
        tolerance = timedelta(seconds=10)

        for sample in reversed(buf):
            if sample.exchange_time <= target_time:
                delta = target_time - sample.exchange_time
                if delta <= tolerance:
                    return sample
                if best is None or delta < best_delta:  # type: ignore
                    best = sample
                    best_delta = delta
                break

        if best and best_delta and best_delta <= timedelta(seconds=30):
            logger.debug("Reference sample for %s is %s before window - accepting with warning", symbol, best_delta)
            return best
        return None

    def get_change_pct(self, symbol: str, window_seconds: int, now_wall: datetime | None = None) -> Optional[Decimal]:
        if now_wall is None:
            now_wall = datetime.now(timezone.utc)
        last_sample = self.get_last_price(symbol)
        if not last_sample or last_sample.price <= Decimal("0"):
            return None
        if self.is_stale(symbol, now_wall) or self.is_out_of_order(symbol):
            return None
        ref_sample = self.get_reference_price(symbol, window_seconds, now_wall)
        if not ref_sample or ref_sample.price <= Decimal("0"):
            return None
        try:
            return calc_change_pct(last_sample.price, ref_sample.price)
        except Exception:
            return None

    def is_stale(self, symbol: str, now_wall: datetime, stale_threshold_seconds: int = 60) -> bool:
        lut = self.last_update_wall.get(symbol)
        if not lut:
            return True
        if now_wall.tzinfo is None:
            now_wall = now_wall.replace(tzinfo=timezone.utc)
        return (now_wall - lut) > timedelta(seconds=stale_threshold_seconds)

    def coverage(self) -> int:
        return len([s for s, buf in self.buffers.items() if buf])
