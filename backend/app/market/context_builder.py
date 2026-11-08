from __future__ import annotations

import uuid
from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional

from app.ai.schemas import MarketSnapshot
from app.db.models import SignalCandidate
from app.market.price_history import PriceHistory
from app.exchange.interface import ExchangeAdapter
from app.core.config import Settings

async def build_market_snapshot(
    candidate: SignalCandidate,
    price_history: PriceHistory,
    adapter: ExchangeAdapter,
    settings: Settings,
) -> MarketSnapshot:
    """
    Build immutable snapshot per candidate with provenance and missing-data flags.
    """
    now = datetime.now(timezone.utc)
    # Try to fetch additional context - if fails, mark missing
    missing = []
    candles_1m = None
    volume_24h = None
    funding_rate = None
    open_interest = None
    orderbook = None
    recent_trades = None
    symbol_status = "TRADING"
    price_precision = None
    qty_precision = None

    # For MVP, we attempt to get symbol filters if available; if not, mark missing
    try:
        # Could call adapter.get_exchange_info filtered, but we have cache
        from app.db.session import get_sync_session_factory
        db = get_sync_session_factory()()
        from app.db.models import SymbolMetadata
        meta = db.query(SymbolMetadata).filter(SymbolMetadata.symbol == candidate.symbol).first()
        if meta:
            symbol_status = meta.status
            price_precision = meta.price_precision
            qty_precision = meta.quantity_precision
        db.close()
    except Exception:
        missing.append("symbol_metadata")

    # Determine freshness
    last_sample = price_history.get_last_price(candidate.symbol)
    freshness = None
    if last_sample:
        freshness = (now - last_sample.receipt_time_wall).total_seconds()
    else:
        missing.append("last_price")

    # Placeholder for additional data feeds (kline, orderbook) - attempt but not required
    # In production, fetch via REST: /fapi/v1/klines, /fapi/v1/depth, /fapi/v1/premiumIndex, etc.
    # For now mark missing if not configured
    missing.extend(["candles_1m", "funding_rate", "open_interest", "orderbook"])  # if not fetched, explicit

    # Determine provenance
    provenance = {
        "candidate_id": candidate.id,
        "event_key": candidate.event_key,
        "exchange_event_time": candidate.exchange_event_time.isoformat() if candidate.exchange_event_time else None,
        "detected_at": candidate.detected_at.isoformat(),
        "snapshot_created_at": now.isoformat(),
    }

    snapshot = MarketSnapshot(
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
        recent_trades=recent_trades,
        missing_data=missing,
        data_freshness_seconds=freshness,
        provenance=provenance,
    )
    return snapshot
