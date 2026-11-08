from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import logging
from typing import Literal, Optional
import uuid

from app.core.config import Settings
from app.market.price_history import PriceHistory
from app.utils.decimal import calc_change_pct

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
        self.event_key = f"{symbol}:{direction}:{int(detected_at.timestamp() // 30)}"


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

    def evaluate(
        self,
        symbol: str,
        now_wall: datetime | None = None,
        trigger_percentage: Decimal | None = None,
        window_seconds: int | None = None,
    ) -> Optional[TriggerResult]:
        if now_wall is None:
            now_wall = datetime.now(timezone.utc)
        elif now_wall.tzinfo is None:
            now_wall = now_wall.replace(tzinfo=timezone.utc)

        last_sample = self.history.get_last_price(symbol)
        if not last_sample:
            return None
        if self.history.is_out_of_order(symbol):
            logger.debug("Out-of-order tick for %s, blocking trigger", symbol)
            return None
        if self.history.is_stale(symbol, now_wall, stale_threshold_seconds=60):
            logger.debug("Stale feed %s, blocking trigger", symbol)
            return None
        staleness = now_wall - last_sample.exchange_time
        if staleness > timedelta(seconds=30):
            logger.debug("Last price too stale for %s: %s", symbol, staleness)
            return None

        if last_sample.price <= Decimal("0"):
            logger.warning("Invalid price for %s: %s", symbol, last_sample.price)
            return None

        window = window_seconds if window_seconds is not None else self.settings.trigger_window_seconds
        ref_sample = self.history.get_reference_price(symbol, window, now_wall)
        if not ref_sample:
            return None
        if ref_sample.price <= Decimal("0"):
            logger.warning("Invalid reference price %s: %s", symbol, ref_sample.price)
            return None

        try:
            change_pct = calc_change_pct(last_sample.price, ref_sample.price)
        except (InvalidOperation, ValueError, ZeroDivisionError) as e:
            logger.error("calc error %s: %s", symbol, e)
            return None

        threshold = trigger_percentage if trigger_percentage is not None else self.settings.trigger_percentage
        direction: Optional[Direction] = None
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
        logger.info(
            "Trigger %s %s %.4f%% now=%s ref=%s",
            symbol,
            direction,
            change_pct,
            last_sample.price,
            ref_sample.price,
        )
        return result
