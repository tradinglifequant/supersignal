from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Optional, List, Dict, Any

"""
Binance USD-M Futures adapter interface.
All financial values as Decimal. Timestamps as datetime.
Implementations must not invent endpoints; verified docs:
- https://developers.binance.com/docs/derivatives/usds-margined-futures/general-info
Testnet: https://testnet.binancefuture.com
Endpoints used:
- GET /fapi/v1/exchangeInfo
- GET /fapi/v1/ticker/price (or /fapi/v1/premiumIndex etc.)
- GET /fapi/v2/balance, /fapi/v2/account (Portfolio Margin)
- GET /fapi/v1/positionRisk
- POST /fapi/v1/order
- GET /fapi/v1/order, /fapi/v1/openOrders, /fapi/v1/allOrders
- DELETE /fapi/v1/order, /fapi/v1/allOpenOrders
- POST /fapi/v1/listenKey etc are for user data stream, not used for polling.
"""

class SymbolFilter(ABC):
    pass

class SymbolMetadataDTO:
    def __init__(
        self,
        symbol: str,
        status: str,
        contract_type: str,
        margin_asset: str,
        price_tick: Decimal,
        qty_step: Decimal,
        min_qty: Decimal,
        max_qty: Decimal | None,
        min_notional: Decimal,
        price_precision: int,
        quantity_precision: int,
    ):
        self.symbol = symbol
        self.status = status
        self.contract_type = contract_type
        self.margin_asset = margin_asset
        self.price_tick = price_tick
        self.qty_step = qty_step
        self.min_qty = min_qty
        self.max_qty = max_qty
        self.min_notional = min_notional
        self.price_precision = price_precision
        self.quantity_precision = quantity_precision

class BalanceDTO:
    def __init__(self, asset: str, balance: Decimal, available: Decimal, cross_unrealized: Decimal):
        self.asset = asset
        self.balance = balance
        self.available = available
        self.cross_unrealized = cross_unrealized

class PositionDTO:
    def __init__(
        self,
        symbol: str,
        position_amt: Decimal,
        entry_price: Decimal,
        mark_price: Decimal,
        unrealized_profit: Decimal,
        leverage: int,
        margin_type: str,
        isolated_margin: Decimal | None = None,
    ):
        self.symbol = symbol
        self.position_amt = position_amt
        self.entry_price = entry_price
        self.mark_price = mark_price
        self.unrealized_profit = unrealized_profit
        self.leverage = leverage
        self.margin_type = margin_type
        self.isolated_margin = isolated_margin

class OrderResultDTO:
    def __init__(
        self,
        symbol: str,
        order_id: int,
        client_order_id: str,
        status: str,
        side: str,
        order_type: str,
        orig_qty: Decimal,
        executed_qty: Decimal,
        avg_price: Decimal | None,
        price: Decimal | None = None,
        stop_price: Decimal | None = None,
        reduce_only: bool = False,
        close_position: bool = False,
    ):
        self.symbol = symbol
        self.order_id = order_id
        self.client_order_id = client_order_id
        self.status = status
        self.side = side
        self.order_type = order_type
        self.orig_qty = orig_qty
        self.executed_qty = executed_qty
        self.avg_price = avg_price
        self.price = price
        self.stop_price = stop_price
        self.reduce_only = reduce_only
        self.close_position = close_position


class ExchangeAdapter(ABC):
    """Adapter interface - keeps exchange-specific code behind interface."""

    @abstractmethod
    async def get_exchange_info(self) -> dict:
        ...

    @abstractmethod
    async def get_eligible_symbols(self) -> List[SymbolMetadataDTO]:
        ...

    @abstractmethod
    async def get_balances(self) -> List[BalanceDTO]:
        ...

    @abstractmethod
    async def get_positions(self) -> List[PositionDTO]:
        ...

    @abstractmethod
    async def get_open_orders(self, symbol: Optional[str] = None) -> List[OrderResultDTO]:
        ...

    @abstractmethod
    async def create_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: Decimal,
        price: Optional[Decimal] = None,
        stop_price: Optional[Decimal] = None,
        client_order_id: Optional[str] = None,
        reduce_only: bool = False,
        close_position: bool = False,
        position_side: Optional[str] = None,
        working_type: Optional[str] = None,
    ) -> OrderResultDTO:
        ...

    @abstractmethod
    async def query_order(self, symbol: str, order_id: Optional[int] = None, client_order_id: Optional[str] = None) -> OrderResultDTO:
        ...

    @abstractmethod
    async def cancel_order(self, symbol: str, order_id: Optional[int] = None, client_order_id: Optional[str] = None) -> OrderResultDTO:
        ...

    @abstractmethod
    async def cancel_all_orders(self, symbol: str) -> dict:
        ...

    @abstractmethod
    async def get_account_info(self) -> dict:
        """Portfolio Margin / account mode info."""

    @abstractmethod
    async def test_connectivity(self) -> bool:
        ...

    @abstractmethod
    async def validate_credentials(self) -> tuple[bool, str, dict | None]:
        ...
