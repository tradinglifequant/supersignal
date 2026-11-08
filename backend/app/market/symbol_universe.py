from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.db.models import SymbolMetadata
from app.exchange.interface import ExchangeAdapter, SymbolMetadataDTO

logger = logging.getLogger(__name__)


class SymbolUniverseService:
    def __init__(self, adapter: ExchangeAdapter, db: Session):
        self.adapter = adapter
        self.db = db
        self._cache: Dict[str, SymbolMetadataDTO] = {}

    async def refresh(self) -> List[SymbolMetadataDTO]:
        try:
            symbols = await self.adapter.get_eligible_symbols()
        except Exception as e:
            logger.error("Failed to fetch eligible symbols: %s", e)
            raise
        now = datetime.now(timezone.utc)
        eligible_names = {dto.symbol for dto in symbols}
        self._cache.clear()
        for dto in symbols:
            existing = self.db.query(SymbolMetadata).filter(SymbolMetadata.symbol == dto.symbol).first()
            if existing:
                existing.status = dto.status
                existing.contract_type = dto.contract_type
                existing.margin_asset = dto.margin_asset
                existing.price_tick = dto.price_tick
                existing.qty_step = dto.qty_step
                existing.min_qty = dto.min_qty
                existing.min_notional = dto.min_notional
                existing.max_qty = dto.max_qty
                existing.price_precision = dto.price_precision
                existing.quantity_precision = dto.quantity_precision
                existing.is_eligible = True
                existing.ineligibility_reason = None
                existing.updated_at = now
            else:
                rec = SymbolMetadata(
                    symbol=dto.symbol,
                    status=dto.status,
                    contract_type=dto.contract_type,
                    margin_asset=dto.margin_asset,
                    price_tick=dto.price_tick,
                    qty_step=dto.qty_step,
                    min_qty=dto.min_qty,
                    min_notional=dto.min_notional,
                    max_qty=dto.max_qty,
                    price_precision=dto.price_precision,
                    quantity_precision=dto.quantity_precision,
                    is_eligible=True,
                    updated_at=now,
                )
                self.db.add(rec)
            self._cache[dto.symbol] = dto

        # Mark previously eligible symbols that disappeared from exchange metadata as ineligible
        stale_rows = (
            self.db.query(SymbolMetadata)
            .filter(SymbolMetadata.is_eligible == True)  # noqa: E712
            .all()
        )
        for row in stale_rows:
            if row.symbol not in eligible_names:
                row.is_eligible = False
                row.ineligibility_reason = "Excluded or paused in latest exchange metadata"
                row.updated_at = now

        self.db.commit()
        logger.info("Symbol universe refreshed: %d eligible", len(symbols))
        return symbols

    def get_cached(self, symbol: str) -> Optional[SymbolMetadataDTO]:
        return self._cache.get(symbol)

    def get_all_cached(self) -> List[SymbolMetadataDTO]:
        return list(self._cache.values())

    def get_db_symbols(self, only_eligible: bool = True):
        q = self.db.query(SymbolMetadata)
        if only_eligible:
            q = q.filter(SymbolMetadata.is_eligible == True)  # noqa: E712
        return q.all()
