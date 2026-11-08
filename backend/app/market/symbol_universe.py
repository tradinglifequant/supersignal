from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Dict, Optional
from decimal import Decimal

from sqlalchemy.orm import Session

from app.exchange.interface import ExchangeAdapter, SymbolMetadataDTO
from app.db.models import SymbolMetadata

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
            logger.error(f"Failed to fetch eligible symbols: {e}")
            raise
        now = datetime.now(timezone.utc)
        for dto in symbols:
            # Upsert DB
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
        self.db.commit()
        # Mark ineligible those not in fresh list? We keep but not is_eligible if delisted
        # For now, just return
        logger.info(f"Symbol universe refreshed: {len(symbols)} eligible")
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
