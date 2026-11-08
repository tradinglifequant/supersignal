"""
Mock adapter for tests and local dev without Binance.
"""
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

from app.exchange.interface import (
    BalanceDTO,
    ExchangeAdapter,
    OrderResultDTO,
    PositionDTO,
    SymbolMetadataDTO,
)


class OrderNotFoundError(LookupError):
    """Raised when a queried order does not exist on the exchange."""


class MockBinanceAdapter(ExchangeAdapter):
    def __init__(self):
        self.symbols: List[SymbolMetadataDTO] = [
            SymbolMetadataDTO(
                symbol="BTCUSDT",
                status="TRADING",
                contract_type="PERPETUAL",
                margin_asset="USDT",
                price_tick=Decimal("0.1"),
                qty_step=Decimal("0.001"),
                min_qty=Decimal("0.001"),
                max_qty=Decimal("1000"),
                min_notional=Decimal("5"),
                price_precision=1,
                quantity_precision=3,
            ),
            SymbolMetadataDTO(
                symbol="ETHUSDT",
                status="TRADING",
                contract_type="PERPETUAL",
                margin_asset="USDT",
                price_tick=Decimal("0.01"),
                qty_step=Decimal("0.01"),
                min_qty=Decimal("0.01"),
                max_qty=Decimal("10000"),
                min_notional=Decimal("5"),
                price_precision=2,
                quantity_precision=2,
            ),
            SymbolMetadataDTO(
                symbol="SOLUSDT",
                status="TRADING",
                contract_type="PERPETUAL",
                margin_asset="USDT",
                price_tick=Decimal("0.01"),
                qty_step=Decimal("0.1"),
                min_qty=Decimal("0.1"),
                max_qty=Decimal("50000"),
                min_notional=Decimal("5"),
                price_precision=2,
                quantity_precision=1,
            ),
            SymbolMetadataDTO(
                symbol="BNBUSDT",
                status="TRADING",
                contract_type="PERPETUAL",
                margin_asset="USDT",
                price_tick=Decimal("0.01"),
                qty_step=Decimal("0.01"),
                min_qty=Decimal("0.01"),
                max_qty=Decimal("10000"),
                min_notional=Decimal("5"),
                price_precision=2,
                quantity_precision=2,
            ),
        ]
        self.balances = [
            BalanceDTO(
                asset="USDT",
                balance=Decimal("1000"),
                available=Decimal("900"),
                cross_unrealized=Decimal("0"),
            )
        ]
        self.positions: List[PositionDTO] = []
        self.orders: List[OrderResultDTO] = []
        self._next_order_id = 100000

    async def get_exchange_info(self) -> dict:
        return {
            "symbols": [
                {
                    "symbol": s.symbol,
                    "status": s.status,
                    "contractType": s.contract_type,
                    "marginAsset": s.margin_asset,
                    "pricePrecision": s.price_precision,
                    "quantityPrecision": s.quantity_precision,
                    "filters": [
                        {"filterType": "PRICE_FILTER", "tickSize": str(s.price_tick)},
                        {
                            "filterType": "LOT_SIZE",
                            "stepSize": str(s.qty_step),
                            "minQty": str(s.min_qty),
                            "maxQty": str(s.max_qty or "1000000"),
                        },
                        {"filterType": "MIN_NOTIONAL", "notional": str(s.min_notional)},
                    ],
                }
                for s in self.symbols
            ]
        }

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

    async def create_order(
        self,
        symbol,
        side,
        order_type,
        quantity,
        price=None,
        stop_price=None,
        client_order_id=None,
        reduce_only=False,
        close_position=False,
        position_side=None,
        working_type=None,
    ):
        self._next_order_id += 1
        oid = self._next_order_id
        cid = client_order_id or f"mock-{oid}"
        status = "FILLED" if order_type.upper() == "MARKET" else "NEW"
        default_prices = {
            "BTCUSDT": Decimal("65000"),
            "ETHUSDT": Decimal("2500"),
            "SOLUSDT": Decimal("150"),
            "BNBUSDT": Decimal("600"),
        }
        avg_price = price or default_prices.get(symbol, Decimal("100"))
        exec_qty = quantity

        if order_type.upper() == "MARKET":
            avg_price = default_prices.get(symbol, Decimal("100"))
            existing = next((p for p in self.positions if p.symbol == symbol), None)
            if close_position:
                if not existing or existing.position_amt == Decimal("0"):
                    exec_qty = Decimal("0")
                    status = "EXPIRED"
                else:
                    exec_qty = abs(existing.position_amt)
                    self.positions.remove(existing)
            elif reduce_only:
                if not existing or existing.position_amt == Decimal("0"):
                    exec_qty = Decimal("0")
                    status = "EXPIRED"
                else:
                    # Clamp reduce-only so it can never flip or increase exposure
                    max_reduce = abs(existing.position_amt)
                    actual_reduce = min(quantity, max_reduce)
                    signed_delta = actual_reduce if side.upper() == "BUY" else -actual_reduce
                    # Ensure reducing direction only
                    if (existing.position_amt > 0 and signed_delta >= 0) or (
                        existing.position_amt < 0 and signed_delta <= 0
                    ):
                        exec_qty = Decimal("0")
                        status = "REJECTED"
                    else:
                        exec_qty = actual_reduce
                        new_amt = existing.position_amt + signed_delta
                        if new_amt == Decimal("0"):
                            self.positions.remove(existing)
                        else:
                            existing.position_amt = new_amt
            else:
                amt = quantity if side.upper() == "BUY" else -quantity
                if existing:
                    new_amt = existing.position_amt + amt
                    if new_amt == Decimal("0"):
                        self.positions.remove(existing)
                    else:
                        existing.position_amt = new_amt
                elif amt != Decimal("0"):
                    self.positions.append(
                        PositionDTO(
                            symbol=symbol,
                            position_amt=amt,
                            entry_price=avg_price,
                            mark_price=avg_price,
                            unrealized_profit=Decimal("0"),
                            leverage=10,
                            margin_type="cross",
                        )
                    )

        dto = OrderResultDTO(
            symbol=symbol,
            order_id=oid,
            client_order_id=cid,
            status=status,
            side=side,
            order_type=order_type,
            orig_qty=exec_qty,
            executed_qty=exec_qty if status == "FILLED" else Decimal("0"),
            avg_price=avg_price if status == "FILLED" else None,
            price=price,
            stop_price=stop_price,
            reduce_only=reduce_only,
            close_position=close_position,
        )
        self.orders.append(dto)
        return dto

    async def query_order(self, symbol, order_id=None, client_order_id=None):
        for o in self.orders:
            if (order_id and o.order_id == order_id) or (client_order_id and o.client_order_id == client_order_id):
                if o.symbol == symbol:
                    return o
        raise OrderNotFoundError(f"Order not found {symbol} {order_id} {client_order_id}")

    async def cancel_order(self, symbol, order_id=None, client_order_id=None):
        o = await self.query_order(symbol, order_id, client_order_id)
        o.status = "CANCELED"
        return o

    async def cancel_all_orders(self, symbol):
        for o in self.orders:
            if o.symbol == symbol and o.status in ("NEW", "PARTIALLY_FILLED"):
                o.status = "CANCELED"
        return {"msg": "canceled"}

    # --- deterministic market-context feeds --------------------------------
    # Deterministic (seeded off the symbol) so tests are reproducible while the
    # snapshot/context path is exercised for real instead of being all-missing.

    _FEED_PRICES = {
        "BTCUSDT": Decimal("65000"),
        "ETHUSDT": Decimal("2500"),
        "SOLUSDT": Decimal("150"),
        "BNBUSDT": Decimal("600"),
    }

    def _px(self, symbol: str) -> Decimal:
        return self._FEED_PRICES.get(symbol, Decimal("100"))

    async def get_klines(self, symbol: str, interval: str = "1m", limit: int = 60) -> list[dict] | None:
        px = self._px(symbol)
        out = []
        for i in range(min(limit, 60)):
            # Slow deterministic ramp so the structure (and drift) is realistic.
            c = px * (Decimal("1") + Decimal(i) / Decimal("600"))
            o = c * Decimal("0.999")
            out.append(
                {
                    "open_time": 1_700_000_000_000 + i * 60_000,
                    "open": str(o),
                    "high": str(c * Decimal("1.001")),
                    "low": str(o * Decimal("0.999")),
                    "close": str(c),
                    "volume": str(Decimal("10") + i),
                    "close_time": 1_700_000_000_000 + (i + 1) * 60_000,
                    "quote_volume": str((Decimal("10") + i) * c),
                    "trades": 50 + i,
                }
            )
        return out

    async def get_depth(self, symbol: str, limit: int = 20) -> dict | None:
        px = self._px(symbol)
        tick = px * Decimal("0.0001")
        # A perfectly symmetric book gives a bid share of exactly 0.500, which no
        # imbalance rule can ever pass. Skew it deterministically per symbol so the
        # order-flow rule is actually exercised.
        skew = {"BTCUSDT": Decimal("1.35"), "ETHUSDT": Decimal("1.30"),
                "SOLUSDT": Decimal("0.90"), "BNBUSDT": Decimal("1.05")}.get(symbol, Decimal("1.0"))
        bids = [{"price": str(px - tick * (i + 1)), "qty": str((Decimal("1") + i) * skew)} for i in range(10)]
        asks = [{"price": str(px + tick * (i + 1)), "qty": str(Decimal("1") + i)} for i in range(10)]
        return {
            "last_update_id": 1,
            "top_bids": bids,
            "top_asks": asks,
            "bid_ask_spread": str(tick * 2),
        }

    async def get_funding_rate(self, symbol: str) -> dict | None:
        px = self._px(symbol)
        return {
            "mark_price": str(px),
            "index_price": str(px * Decimal("0.9999")),
            "last_funding_rate": "0.0001",
            "next_funding_time": 1_700_003_600_000,
        }

    async def get_open_interest(self, symbol: str) -> dict | None:
        return {"open_interest": "123456.789", "symbol": symbol}

    async def get_ticker_24h(self, symbol: str) -> dict | None:
        px = self._px(symbol)
        return {
            "volume": "1000000",
            "quote_volume": str(px * Decimal("1000000")),
            "price_change_pct": "1.23",
            "high": str(px * Decimal("1.02")),
            "low": str(px * Decimal("0.98")),
        }

    async def get_server_time(self) -> int | None:
        import time

        return int(time.time() * 1000)

    async def get_api_key_permissions(self) -> dict | None:
        # A mock key is never withdrawal-capable, so the preflight passes in dev.
        return {
            "can_trade": True,
            "can_withdraw": False,
            "can_deposit": True,
            "source": "mock",
        }

    async def get_account_info(self):
        return {"canTrade": True, "feeTier": 0, "totalWalletBalance": "1000", "availableBalance": "900"}

    async def test_connectivity(self):
        return True

    async def validate_credentials(self):
        return True, "Mock valid", {"canTrade": True}

    async def close(self):
        pass
