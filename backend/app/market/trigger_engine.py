from __future__ import annotations

from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone, timedelta
from typing import Optional, Literal
import uuid
import logging

from app.market.price_history import PriceHistory
from app.utils.decimal import calc_change_pct
from app.core.config import Settings
from app.db.models import SignalCandidate

logger = logging.getLogger(__name__)

Direction = Literal["LONG", "SHORT"]

class TriggerResult:
    def __init__(
        self,
        symbol: str,
        direction: Direction,
        price_now: Decimal,
        price_ref: Decimal,
        change_pct: Decimal,
        window_seconds: int,
        exchange_event_time: datetime,
        detected_at: datetime,
    ):
        self.symbol = symbol
        self.direction = direction
        self.price_now = price_now
        self.price_ref = price_ref
        self.change_pct = change_pct
        self.window_seconds = window_seconds
        self.exchange_event_time = exchange_event_time
        self.detected_at = detected_at
        self.event_id = str(uuid.uuid4())
        self.event_key = f"{symbol}:{direction}:{int(detected_at.timestamp() // 30)}"  # 30s bucket for dedup

class TriggerEngine:
    """
    Implements FR-02 price movement trigger.
    change_pct = ((last_price_now - last_price_180s_ago) / last_price_180s_ago) * 100
    LONG if >= +threshold, SHORT if <= -threshold
    Uses Decimal.
    Must handle zero/invalid, stale, out-of-order, boundary exact threshold.
    """

    def __init__(self, price_history: PriceHistory, settings: Settings):
        self.history = price_history
        self.settings = settings

    def evaluate(self, symbol: str, now_wall: datetime | None = None) -> Optional[TriggerResult]:
        if now_wall is None:
            now_wall = datetime.now(timezone.utc)
        last_sample = self.history.get_last_price(symbol)
        if not last_sample:
            return None
        # freshness guard: exchange event time not too old, receipt staleness
        if self.history.is_stale(symbol, now_wall, stale_threshold_seconds=60):
            logger.debug(f"Stale feed {symbol}, blocking trigger")
            return None
        staleness = now_wall - last_sample.exchange_time
        if staleness > timedelta(seconds=30):
            logger.debug(f"Last price too stale for {symbol}: {staleness}")
            return None

        # Validate price positive
        if last_sample.price <= Decimal("0"):
            logger.warning(f"Invalid price for {symbol}: {last_sample.price}")
            return None

        window = self.settings.trigger_window_seconds
        ref_sample = self.history.get_reference_price(symbol, window, now_wall)
        if not ref_sample:
            return None
        if ref_sample.price <= Decimal("0"):
            logger.warning(f"Invalid reference price {symbol}: {ref_sample.price}")
            return None

        try:
            change_pct = calc_change_pct(last_sample.price, ref_sample.price)
        except (InvalidOperation, ValueError, ZeroDivisionError) as e:
            logger.error(f"calc error {symbol}: {e}")
            return None

        threshold = self.settings.trigger_percentage
        direction: Optional[Direction] = None
        # Exact threshold boundary: >= and <=
        if change_pct >= threshold:
            direction = "LONG"
        elif change_pct <= -threshold:
            direction = "SHORT"
        else:
            return None

        result = TriggerResult(
            symbol=symbol,
            direction=direction,
            price_now=last_sample.price,
            price_ref=ref_sample.price,
            change_pct=change_pct,
            window_seconds=window,
            exchange_event_time=last_sample.exchange_time,
            detected_at=now_wall,
        )
        logger.info(f"Trigger {symbol} {direction} {change_pct:.4f}% now={last_sample.price} ref={ref_sample.price}")
        return result
