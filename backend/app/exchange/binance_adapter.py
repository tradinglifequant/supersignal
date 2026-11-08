from __future__ import annotations

import hashlib
import hmac
import time
import urllib.parse
from decimal import Decimal
from typing import Optional, List, Dict, Any
import logging

import httpx

from app.core.config import get_settings
from app.exchange.interface import ExchangeAdapter, SymbolMetadataDTO, BalanceDTO, PositionDTO, OrderResultDTO
from app.security.encryption import decrypt_value
from app.db.session import get_sync_session_factory
from app.db.models import ExchangeCredential, SystemLog
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Binance error codes that are NOT retryable
NON_RETRYABLE_CODES = {-2010, -2011, -2015, -2018, -2021, -1100, -1101, -1102, -1104, -1111, -1112, -1117, -1121, -4003, -4004, -4005}
RETRYABLE_CODES = {-1000, -1001, -1003, -1016, -1021}  # timeout, rate limit, etc. Use carefully

def _decimal(v: Any) -> Decimal:
    return Decimal(str(v))

class BinanceAdapter(ExchangeAdapter):
    """
    Binance USD-M Futures adapter.
    Verified endpoints (2024-2026 docs):
    - GET /fapi/v1/ping
    - GET /fapi/v1/exchangeInfo
    - GET /fapi/v1/ticker/price
    - GET /fapi/v2/balance
    - GET /fapi/v2/account  (includes feeTier, canTrade, etc.)
    - GET /fapi/v2/positionRisk
    - POST /fapi/v1/order
    - GET /fapi/v1/order
    - GET /fapi/v1/openOrders
    - DELETE /fapi/v1/order
    - DELETE /fapi/v1/allOpenOrders
    - Portfolio Margin: GET /papi/v1/balance, /papi/v1/account etc. We attempt papi then fallback to fapi.
    Research note: Portfolio Margin account compatibility must be verified per account; adapter tries papi first.
    """

    def __init__(self, api_key: str | None = None, api_secret: str | None = None, testnet: bool | None = None):
        settings = get_settings()
        self.api_key = api_key if api_key is not None else settings.binance_api_key
        self.api_secret = api_secret if api_secret is not None else settings.binance_api_secret
        self.testnet = testnet if testnet is not None else settings.binance_testnet
        self.base_url = settings.binance_testnet_base_url if self.testnet else settings.binance_base_url
        self.recv_window = settings.binance_recv_window
        self.client = httpx.AsyncClient(timeout=10.0, headers={"X-MBX-APIKEY": self.api_key} if self.api_key else {})
        logger.info(f"BinanceAdapter initialized testnet={self.testnet} base={self.base_url}")

    def _sign(self, params: dict) -> dict:
        if not self.api_secret:
            return params
        params["timestamp"] = int(time.time() * 1000)
        params["recvWindow"] = self.recv_window
        query = urllib.parse.urlencode(params, doseq=True)
        signature = hmac.new(self.api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        params["signature"] = signature
        return params

    async def _request(self, method: str, path: str, params: dict | None = None, signed: bool = False) -> Any:
        params = params or {}
        if signed:
            params = self._sign(params.copy())
        url = self.base_url + path
        try:
            resp = await self.client.request(method, url, params=params)
        except httpx.RequestError as e:
            logger.error(f"Binance request error {method} {path}: {e}")
            raise

        if resp.status_code != 200:
            try:
                body = resp.json()
            except Exception:
                body = resp.text
            logger.warning(f"Binance API error {resp.status_code} {path}: {body}")
            # Raise with code if present
            raise BinanceAPIError(resp.status_code, body)

        return resp.json()

    async def test_connectivity(self) -> bool:
        try:
            await self._request("GET", "/fapi/v1/ping")
            return True
        except Exception:
            return False

    async def get_exchange_info(self) -> dict:
        return await self._request("GET", "/fapi/v1/exchangeInfo")

    async def get_eligible_symbols(self) -> List[SymbolMetadataDTO]:
        info = await self.get_exchange_info()
        symbols = info.get("symbols", [])
        result: List[SymbolMetadataDTO] = []
        for s in symbols:
            # Filter per PRD: USDT-margined perpetual, TRADING
            symbol = s.get("symbol", "")
            status = s.get("status", "")
            contract_type = s.get("contractType", "")
            margin_asset = s.get("marginAsset", "")
            if contract_type != "PERPETUAL":
                continue
            if margin_asset != "USDT":
                continue
            if status != "TRADING":
                continue
            # parse filters
            filters = {f["filterType"]: f for f in s.get("filters", [])}
            price_filter = filters.get("PRICE_FILTER", {})
            lot_size = filters.get("LOT_SIZE", {})
            market_lot = filters.get("MARKET_LOT_SIZE", {})
            min_notional = filters.get("MIN_NOTIONAL", {}) or filters.get("NOTIONAL", {}) or {}

            tick = _decimal(price_filter.get("tickSize", "0.01"))
            step = _decimal(lot_size.get("stepSize", "0.001"))
            min_qty = _decimal(lot_size.get("minQty", "0"))
            # market lot may override
            if market_lot:
                step = _decimal(market_lot.get("stepSize", step))
                min_qty = _decimal(market_lot.get("minQty", min_qty))

            min_not = _decimal(min_notional.get("notional", "5") if min_notional else "5")
            # Binance often returns minNotional as string, or not present for some symbols
            try:
                price_precision = int(s.get("pricePrecision", 2))
                qty_precision = int(s.get("quantityPrecision", 3))
            except Exception:
                price_precision, qty_precision = 2, 3

            max_qty = None
            if lot_size.get("maxQty"):
                max_qty = _decimal(lot_size["maxQty"])

            dto = SymbolMetadataDTO(
                symbol=symbol,
                status=status,
                contract_type=contract_type,
                margin_asset=margin_asset,
                price_tick=tick,
                qty_step=step,
                min_qty=min_qty,
                max_qty=max_qty,
                min_notional=min_not,
                price_precision=price_precision,
                quantity_precision=qty_precision,
            )
            result.append(dto)
        logger.info(f"Eligible symbols count: {len(result)}")
        return result

    async def get_account_info(self) -> dict:
        # Try Portfolio Margin first, then fapi
        for path in ["/papi/v1/account", "/fapi/v2/account"]:
            try:
                return await self._request("GET", path, signed=True)
            except BinanceAPIError as e:
                if e.status_code in (404, 400):
                    continue
                raise
        # fallback
        return await self._request("GET", "/fapi/v2/account", signed=True)

    async def get_balances(self) -> List[BalanceDTO]:
        # Try papi balance, else fapi
        data = None
        for path in ["/papi/v1/balance", "/fapi/v2/balance"]:
            try:
                data = await self._request("GET", path, signed=True)
                break
            except BinanceAPIError as e:
                if e.status_code in (404, 400):
                    continue
                raise
        if data is None:
            raise BinanceAPIError(500, "Unable to fetch balances")

        balances: List[BalanceDTO] = []
        for item in data:
            asset = item.get("asset", "")
            # papi and fapi have slightly different fields
            bal = _decimal(item.get("balance", item.get("walletBalance", "0")))
            avail = _decimal(item.get("availableBalance", item.get("crossWalletBalance", item.get("balance", "0"))))
            unreal = _decimal(item.get("crossUnPnl", item.get("crossUnrealizedPnl", "0")))
            balances.append(BalanceDTO(asset=asset, balance=bal, available=avail, cross_unrealized=unreal))
        return balances

    async def get_positions(self) -> List[PositionDTO]:
        # papi vs fapi
        data = None
        for path in ["/papi/v1/positionRisk", "/fapi/v2/positionRisk"]:
            try:
                data = await self._request("GET", path, signed=True)
                break
            except BinanceAPIError as e:
                if e.status_code in (404, 400):
                    continue
                raise
        if data is None:
            return []
        positions: List[PositionDTO] = []
        for p in data:
            # positionRisk returns list with symbol, positionAmt, entryPrice, markPrice, unRealizedProfit, leverage, marginType
            amt = _decimal(p.get("positionAmt", "0"))
            if amt == Decimal("0"):
                # optionally skip zero, but return for reconciliation awareness
                pass
            positions.append(PositionDTO(
                symbol=p.get("symbol", ""),
                position_amt=amt,
                entry_price=_decimal(p.get("entryPrice", "0")),
                mark_price=_decimal(p.get("markPrice", "0")),
                unrealized_profit=_decimal(p.get("unRealizedProfit", p.get("unrealizedProfit", "0"))),
                leverage=int(float(p.get("leverage", "10"))),
                margin_type=p.get("marginType", "cross"),
                isolated_margin=_decimal(p.get("isolatedMargin", "0")) if p.get("isolatedMargin") else None,
            ))
        return positions

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[OrderResultDTO]:
        params = {}
        if symbol:
            params["symbol"] = symbol
        data = await self._request("GET", "/fapi/v1/openOrders", params=params, signed=True)
        return [self._to_order_dto(o) for o in data]

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
        params: dict[str, Any] = {
            "symbol": symbol,
            "side": side.upper(),
            "type": order_type.upper(),
            "quantity": str(quantity),
        }
        if price is not None:
            params["price"] = str(price)
        if stop_price is not None:
            params["stopPrice"] = str(stop_price)
        if client_order_id:
            params["newClientOrderId"] = client_order_id
        if reduce_only:
            params["reduceOnly"] = "true"
        if close_position:
            params["closePosition"] = "true"
            # closePosition orders must not have quantity
            params.pop("quantity", None)
        if position_side:
            params["positionSide"] = position_side
        if working_type:
            params["workingType"] = working_type
        # For market orders, additional params like timeInForce not needed

        data = await self._request("POST", "/fapi/v1/order", params=params, signed=True)
        return self._to_order_dto(data)

    async def query_order(self, symbol: str, order_id: Optional[int] = None, client_order_id: Optional[str] = None) -> OrderResultDTO:
        params: dict[str, Any] = {"symbol": symbol}
        if order_id is not None:
            params["orderId"] = str(order_id)
        if client_order_id:
            params["origClientOrderId"] = client_order_id
        data = await self._request("GET", "/fapi/v1/order", params=params, signed=True)
        return self._to_order_dto(data)

    async def cancel_order(self, symbol: str, order_id: Optional[int] = None, client_order_id: Optional[str] = None) -> OrderResultDTO:
        params: dict[str, Any] = {"symbol": symbol}
        if order_id is not None:
            params["orderId"] = str(order_id)
        if client_order_id:
            params["origClientOrderId"] = client_order_id
        data = await self._request("DELETE", "/fapi/v1/order", params=params, signed=True)
        return self._to_order_dto(data)

    async def cancel_all_orders(self, symbol: str) -> dict:
        return await self._request("DELETE", "/fapi/v1/allOpenOrders", params={"symbol": symbol}, signed=True)

    async def validate_credentials(self) -> tuple[bool, str, dict | None]:
        if not self.api_key or not self.api_secret:
            return False, "API key/secret not configured", None
        try:
            acct = await self.get_account_info()
            # Check canTrade
            can_trade = acct.get("canTrade", True)
            if not can_trade:
                return False, "Account cannot trade (canTrade=false)", acct
            # Check withdrawal? Binance account info doesn't directly show withdrawal permission, but we warn operator
            return True, "Credentials valid", acct
        except BinanceAPIError as e:
            return False, f"Validation failed: {e.body}", None
        except Exception as e:
            return False, f"Validation error: {e}", None

    def _to_order_dto(self, data: dict) -> OrderResultDTO:
        return OrderResultDTO(
            symbol=data.get("symbol", ""),
            order_id=int(data.get("orderId", 0)),
            client_order_id=data.get("clientOrderId", data.get("origClientOrderId", "")),
            status=data.get("status", "NEW"),
            side=data.get("side", ""),
            order_type=data.get("type", ""),
            orig_qty=_decimal(data.get("origQty", data.get("quantity", "0"))),
            executed_qty=_decimal(data.get("executedQty", "0")),
            avg_price=_decimal(data.get("avgPrice", "0")) if str(data.get("avgPrice", "0")) != "0" else None,
            price=_decimal(data["price"]) if data.get("price") not in (None, "", 0, "0") else None,
            stop_price=_decimal(data["stopPrice"]) if data.get("stopPrice") not in (None, "", 0, "0") else None,
            reduce_only=(str(data.get("reduceOnly", "")).lower() == "true" or data.get("reduceOnly") is True),
            close_position=(str(data.get("closePosition", "")).lower() == "true" or data.get("closePosition") is True),
        )

    async def close(self):
        await self.client.aclose()


class BinanceAPIError(Exception):
    def __init__(self, status_code: int, body: Any):
        self.status_code = status_code
        self.body = body
        super().__init__(f"Binance API {status_code}: {body}")

    @property
    def code(self) -> int | None:
        if isinstance(self.body, dict):
            return self.body.get("code")
        return None

    def is_retryable(self) -> bool:
        c = self.code
        if c is None:
            return self.status_code in (429, 500, 502, 503, 504)
        return c in RETRYABLE_CODES

    def is_non_retryable(self) -> bool:
        c = self.code
        if c is None:
            return False
        return c in NON_RETRYABLE_CODES
