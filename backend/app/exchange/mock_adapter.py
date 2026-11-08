"""
Mock adapter for tests and local dev without Binance.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional, List
import uuid

from app.exchange.interface import ExchangeAdapter, SymbolMetadataDTO, BalanceDTO, PositionDTO, OrderResultDTO

class MockBinanceAdapter(ExchangeAdapter):
    def __init__(self):
        self.symbols: List[SymbolMetadataDTO] = [
            SymbolMetadataDTO(
                symbol="BTCUSDT", status="TRADING", contract_type="PERPETUAL", margin_asset="USDT",
                price_tick=Decimal("0.1"), qty_step=Decimal("0.001"), min_qty=Decimal("0.001"),
                max_qty=Decimal("1000"), min_notional=Decimal("5"), price_precision=1, quantity_precision=3,
            ),
            SymbolMetadataDTO(
                symbol="ETHUSDT", status="TRADING", contract_type="PERPETUAL", margin_asset="USDT",
                price_tick=Decimal("0.01"), qty_step=Decimal("0.01"), min_qty=Decimal("0.01"),
                max_qty=Decimal("10000"), min_notional=Decimal("5"), price_precision=2, quantity_precision=2,
            ),
        ]
        self.balances = [BalanceDTO(asset="USDT", balance=Decimal("1000"), available=Decimal("900"), cross_unrealized=Decimal("0"))]
        self.positions: List[PositionDTO] = []
        self.orders: List[OrderResultDTO] = []
        self._next_order_id = 100000

    async def get_exchange_info(self) -> dict:
        return {"symbols": [
            {"symbol": s.symbol, "status": s.status, "contractType": s.contract_type, "marginAsset": s.margin_asset,
             "pricePrecision": s.price_precision, "quantityPrecision": s.quantity_precision,
             "filters": [
                 {"filterType": "PRICE_FILTER", "tickSize": str(s.price_tick)},
                 {"filterType": "LOT_SIZE", "stepSize": str(s.qty_step), "minQty": str(s.min_qty), "maxQty": str(s.max_qty or "1000000")},
                 {"filterType": "MIN_NOTIONAL", "notional": str(s.min_notional)},
             ]} for s in self.symbols
        ]}

    async def get_eligible_symbols(self) -> List[SymbolMetadataDTO]:
        return self.symbols

    async def get_balances(self) -> List[BalanceDTO]:
        return self.balances

    async def get_positions(self) -> List[PositionDTO]:
        return [p for p in self.positions if p.position_amt != Decimal("0")]

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[OrderResultDTO]:
        if symbol:
            return [o for o in self.orders if o.symbol == symbol and o.status in ("NEW", "PARTIALLY_FILLED")]
        return [o for o in self.orders if o.status in ("NEW", "PARTIALLY_FILLED")]

    async def create_order(self, symbol, side, order_type, quantity, price=None, stop_price=None, client_order_id=None, reduce_only=False, close_position=False, position_side=None, working_type=None):
        self._next_order_id += 1
        oid = self._next_order_id
        cid = client_order_id or f"mock-{oid}"
        # Simulate immediate fill for MARKET
        status = "FILLED" if order_type.upper() == "MARKET" else "NEW"
        avg_price = price or Decimal("50000")
        if order_type.upper() == "MARKET":
            avg_price = Decimal("65000") if symbol == "BTCUSDT" else Decimal("2500")
            # Update position
            amt = quantity if side.upper() == "BUY" else -quantity
            # Find existing
            existing = next((p for p in self.positions if p.symbol == symbol), None)
            if existing:
                # Simple aggregation
                new_amt = existing.position_amt + amt
                if new_amt == Decimal("0"):
                    self.positions.remove(existing)
                else:
                    existing.position_amt = new_amt
            else:
                if amt != Decimal("0"):
                    self.positions.append(PositionDTO(symbol=symbol, position_amt=amt, entry_price=avg_price, mark_price=avg_price, unrealized_profit=Decimal("0"), leverage=10, margin_type="cross"))

        dto = OrderResultDTO(symbol=symbol, order_id=oid, client_order_id=cid, status=status, side=side, order_type=order_type, orig_qty=quantity, executed_qty=quantity if status=="FILLED" else Decimal("0"), avg_price=avg_price, price=price, stop_price=stop_price, reduce_only=reduce_only, close_position=close_position)
        self.orders.append(dto)
        return dto

    async def query_order(self, symbol, order_id=None, client_order_id=None):
        for o in self.orders:
            if (order_id and o.order_id == order_id) or (client_order_id and o.client_order_id == client_order_id):
                if o.symbol == symbol:
                    return o
        raise Exception(f"Order not found {symbol} {order_id} {client_order_id}")

    async def cancel_order(self, symbol, order_id=None, client_order_id=None):
        o = await self.query_order(symbol, order_id, client_order_id)
        o.status = "CANCELED"
        return o

    async def cancel_all_orders(self, symbol):
        for o in self.orders:
            if o.symbol == symbol and o.status in ("NEW", "PARTIALLY_FILLED"):
                o.status = "CANCELED"
        return {"msg": "canceled"}

    async def get_account_info(self):
        return {"canTrade": True, "feeTier": 0, "totalWalletBalance": "1000", "availableBalance": "900"}

    async def test_connectivity(self):
        return True

    async def validate_credentials(self):
        return True, "Mock valid", {"canTrade": True}

    async def close(self):
        pass
