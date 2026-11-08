from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.ai.schemas import MarketSnapshot
from app.core.config import Settings
from app.db.models import SignalCandidate, SymbolMetadata
from app.exchange.interface import ExchangeAdapter
from app.market.price_history import PriceHistory

logger = logging.getLogger(__name__)

# Feeds that used to be hard-coded into ``missing_data``. They are now fetched
# concurrently with a bounded timeout, so the AI gate decides on real context
# and an unreachable feed degrades the snapshot instead of failing the candidate.
FEED_TIMEOUT_SECONDS = 4.0


async def _gather_feed(coro, name: str) -> tuple[str, object]:
    """Run one optional feed; any failure becomes a recorded gap, never a raise."""
    try:
        value = await asyncio.wait_for(coro, timeout=FEED_TIMEOUT_SECONDS)
        return name, value
    except asyncio.TimeoutError:
        logger.debug("feed %s timed out", name)
        return name, None
    except Exception as e:  # noqa: BLE001 - a degraded feed must not kill a candidate
        logger.debug("feed %s failed: %s", name, type(e).__name__)
        return name, None


async def build_market_snapshot(
    candidate: SignalCandidate,
    price_history: PriceHistory,
    adapter: ExchangeAdapter,
    settings: Settings,
    db: Optional[Session] = None,
) -> MarketSnapshot:
    """
    Build an immutable snapshot per candidate with provenance and missing-data flags.

    Every field that could not be retrieved is listed in ``missing_data`` so the
    AI agents and the audit trail can see exactly what the decision rested on.
    """
    now = datetime.now(timezone.utc)
    missing: list[str] = []
    symbol_status = "TRADING"
    price_precision = None
    qty_precision = None

    # --- symbol filters -------------------------------------------------
    # Accept a caller-supplied session; opening one here would block the event
    # loop when no session was passed in.
    if db is not None:
        try:
            meta = db.query(SymbolMetadata).filter(SymbolMetadata.symbol == candidate.symbol).first()
            if meta:
                symbol_status = meta.status
                price_precision = meta.price_precision
                qty_precision = meta.quantity_precision
        except Exception:
            missing.append("symbol_metadata")
    else:
        missing.append("symbol_metadata")

    # --- price freshness -------------------------------------------------
    last_sample = price_history.get_last_price(candidate.symbol)
    freshness = None
    if last_sample:
        freshness = (now - last_sample.receipt_time_wall).total_seconds()
    else:
        missing.append("last_price")

    # --- market context feeds (concurrent, bounded) ----------------------
    results = dict(
        await asyncio.gather(
            _gather_feed(
                adapter.get_klines(candidate.symbol, "1m", 60), "candles_1m"
            ),
            _gather_feed(adapter.get_depth(candidate.symbol, 20), "orderbook"),
            _gather_feed(adapter.get_funding_rate(candidate.symbol), "funding_rate"),
            _gather_feed(adapter.get_open_interest(candidate.symbol), "open_interest"),
            _gather_feed(adapter.get_ticker_24h(candidate.symbol), "volume_24h"),
        )
    )

    candles_1m = results.get("candles_1m")
    orderbook = results.get("orderbook")
    funding_raw = results.get("funding_rate")
    oi_raw = results.get("open_interest")
    ticker_raw = results.get("volume_24h")

    funding_rate = funding_raw.get("last_funding_rate") if isinstance(funding_raw, dict) else None
    open_interest = oi_raw.get("open_interest") if isinstance(oi_raw, dict) else None
    volume_24h = ticker_raw.get("quote_volume") if isinstance(ticker_raw, dict) else None

    for field, value in (
        ("candles_1m", candles_1m),
        ("orderbook", orderbook),
        ("funding_rate", funding_rate),
        ("open_interest", open_interest),
        ("volume_24h", volume_24h),
    ):
        if not value:
            missing.append(field)

    provenance = {
        "candidate_id": candidate.id,
        "event_key": candidate.event_key,
        "exchange_event_time": candidate.exchange_event_time.isoformat()
        if candidate.exchange_event_time
        else None,
        "detected_at": candidate.detected_at.isoformat(),
        "snapshot_created_at": now.isoformat(),
        "feed_timeout_seconds": FEED_TIMEOUT_SECONDS,
        "mark_price": funding_raw.get("mark_price") if isinstance(funding_raw, dict) else None,
    }

    return MarketSnapshot(
        snapshot_id=str(uuid.uuid4()),
        symbol=candidate.symbol,
        direction=candidate.direction,
        trigger_price_now=str(candidate.current_price),
        trigger_price_ref=str(candidate.reference_price),
        trigger_change_pct=str(candidate.change_pct),
        window_seconds=candidate.window_seconds,
        detected_at=candidate.detected_at,
        exchange_event_time=candidate.exchange_event_time or now,
        last_price=str(candidate.current_price),
        symbol_status=symbol_status,
        price_precision=price_precision,
        qty_precision=qty_precision,
        candles_1m=candles_1m,
        volume_24h=volume_24h,
        funding_rate=funding_rate,
        open_interest=open_interest,
        orderbook_snapshot=orderbook,
        recent_trades=None,
        missing_data=missing,
        data_freshness_seconds=freshness,
        provenance=provenance,
    )
