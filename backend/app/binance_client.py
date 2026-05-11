import hashlib
import hmac
import time
from decimal import Decimal, ROUND_CEILING, ROUND_DOWN
from urllib.parse import urlencode
import httpx
import pandas as pd
from app.config import Settings, get_settings


class BinanceFuturesClient:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.client = httpx.AsyncClient(base_url=self.settings.base_url, timeout=15)
        self._exchange_info_cache: dict | None = None

    async def close(self) -> None:
        await self.client.aclose()

    def _headers(self) -> dict:
        return {"X-MBX-APIKEY": self.settings.binance_api_key} if self.settings.binance_api_key else {}

    def _signed_params(self, params: dict | None = None) -> dict:
        if not self.settings.binance_api_key or not self.settings.binance_api_secret:
            raise RuntimeError("Binance API key/secret missing. Configure .env before real Testnet orders.")
        data = dict(params or {})
        data["timestamp"] = int(time.time() * 1000)
        data["recvWindow"] = self.settings.binance_recv_window
        query = urlencode(data)
        signature = hmac.new(self.settings.binance_api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        data["signature"] = signature
        return data

    async def exchange_info(self) -> dict:
        if self._exchange_info_cache:
            return self._exchange_info_cache
        response = await self.client.get("/fapi/v1/exchangeInfo")
        response.raise_for_status()
        self._exchange_info_cache = response.json()
        return self._exchange_info_cache

    async def symbol_rules(self, symbol: str) -> dict:
        info = await self.exchange_info()
        row = next((item for item in info.get("symbols", []) if item.get("symbol") == symbol), None)
        if not row:
            raise RuntimeError(f"Symbol {symbol} not found in Futures exchangeInfo.")
        filters = {item["filterType"]: item for item in row.get("filters", [])}
        return {"symbol": row, "filters": filters}

    def _floor_to_step(self, value: float | str, step: float | str) -> str:
        value_dec = Decimal(str(value))
        step_dec = Decimal(str(step))
        if step_dec == 0:
            return format(value_dec.normalize(), "f")
        floored = (value_dec / step_dec).to_integral_value(rounding=ROUND_DOWN) * step_dec
        return format(floored.normalize(), "f")

    def _ceil_to_step(self, value: float | str, step: float | str) -> str:
        value_dec = Decimal(str(value))
        step_dec = Decimal(str(step))
        if step_dec == 0:
            return format(value_dec.normalize(), "f")
        ceiled = (value_dec / step_dec).to_integral_value(rounding=ROUND_CEILING) * step_dec
        return format(ceiled.normalize(), "f")

    async def normalize_quantity(self, symbol: str, quantity: float, market: bool = True) -> str:
        rules = await self.symbol_rules(symbol)
        filters = rules["filters"]
        lot = filters.get("MARKET_LOT_SIZE" if market else "LOT_SIZE") or filters.get("LOT_SIZE")
        step = lot.get("stepSize", "1") if lot else "1"
        min_qty = Decimal(str(lot.get("minQty", "0"))) if lot else Decimal("0")
        max_qty = Decimal(str(lot.get("maxQty", "999999999"))) if lot else Decimal("999999999")
        normalized = Decimal(self._floor_to_step(quantity, step))
        if normalized < min_qty:
            raise RuntimeError(f"Quantity {normalized} below minQty {min_qty} for {symbol}.")
        if normalized > max_qty:
            normalized = Decimal(self._floor_to_step(max_qty, step))
        return format(normalized.normalize(), "f")

    async def quantity_for_min_notional(self, symbol: str, price: float, desired_quantity: float, market: bool = True) -> str:
        rules = await self.symbol_rules(symbol)
        filters = rules["filters"]
        lot = filters.get("MARKET_LOT_SIZE" if market else "LOT_SIZE") or filters.get("LOT_SIZE")
        step = lot.get("stepSize", "1") if lot else "1"
        min_notional = Decimal(str(await self.min_notional(symbol)))
        desired = Decimal(str(desired_quantity))
        price_dec = Decimal(str(price))
        if min_notional > 0 and desired * price_dec < min_notional:
            desired = Decimal(self._ceil_to_step(min_notional / price_dec, step))
        return await self.normalize_quantity(symbol, float(desired), market)

    async def min_notional(self, symbol: str) -> float:
        rules = await self.symbol_rules(symbol)
        filters = rules["filters"]
        notional = filters.get("MIN_NOTIONAL") or filters.get("NOTIONAL")
        if not notional:
            return 0
        return float(notional.get("notional") or notional.get("minNotional") or 0)

    async def normalize_price(self, symbol: str, price: float) -> str:
        rules = await self.symbol_rules(symbol)
        price_filter = rules["filters"].get("PRICE_FILTER")
        tick = price_filter.get("tickSize", "0.00000001") if price_filter else "0.00000001"
        normalized = Decimal(self._floor_to_step(price, tick))
        return format(normalized.normalize(), "f")

    async def ticker_24h(self) -> list[dict]:
        response = await self.client.get("/fapi/v1/ticker/24hr")
        response.raise_for_status()
        return response.json()

    async def book_ticker(self) -> list[dict]:
        response = await self.client.get("/fapi/v1/ticker/bookTicker")
        response.raise_for_status()
        return response.json()

    async def klines(self, symbol: str, interval: str = "15m", limit: int = 250) -> pd.DataFrame:
        response = await self.client.get("/fapi/v1/klines", params={"symbol": symbol, "interval": interval, "limit": limit})
        response.raise_for_status()
        rows = response.json()
        columns = [
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "close_time",
            "quote_volume",
            "trades",
            "taker_buy_base",
            "taker_buy_quote",
            "ignore",
        ]
        df = pd.DataFrame(rows, columns=columns)
        for col in ["open", "high", "low", "close", "volume", "quote_volume", "taker_buy_base", "taker_buy_quote"]:
            df[col] = df[col].astype(float)
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
        return df

    async def account(self) -> dict:
        params = self._signed_params()
        response = await self.client.get("/fapi/v2/account", params=params, headers=self._headers())
        response.raise_for_status()
        return response.json()

    async def position_risk(self) -> list[dict]:
        params = self._signed_params()
        response = await self.client.get("/fapi/v2/positionRisk", params=params, headers=self._headers())
        response.raise_for_status()
        return response.json()

    async def position_mode(self) -> dict:
        params = self._signed_params()
        response = await self.client.get("/fapi/v1/positionSide/dual", params=params, headers=self._headers())
        if response.status_code >= 400:
            raise RuntimeError(f"Binance Futures position mode error {response.status_code}: {response.text}")
        return response.json()

    async def set_leverage(self, symbol: str, leverage: int) -> dict:
        params = self._signed_params({"symbol": symbol, "leverage": leverage})
        response = await self.client.post("/fapi/v1/leverage", params=params, headers=self._headers())
        if response.status_code >= 400:
            raise RuntimeError(f"Binance Futures leverage error {response.status_code}: {response.text}")
        return response.json()

    async def set_margin_type(self, symbol: str, margin_type: str = "ISOLATED") -> dict:
        params = self._signed_params({"symbol": symbol, "marginType": margin_type})
        response = await self.client.post("/fapi/v1/marginType", params=params, headers=self._headers())
        if response.status_code in {400, 409}:
            return {"status": "already_set_or_ignored", "detail": response.text}
        if response.status_code >= 400:
            raise RuntimeError(f"Binance Futures margin error {response.status_code}: {response.text}")
        return response.json()

    async def create_order(self, **payload) -> dict:
        if not self.settings.real_orders_enabled:
            raise RuntimeError("Real orders are disabled. Use paper mode or set DRY_RUN_FORCE=false intentionally.")
        if payload.get("type") in {"STOP_MARKET", "TAKE_PROFIT_MARKET", "STOP", "TAKE_PROFIT", "TRAILING_STOP_MARKET"}:
            return await self.create_algo_order(**payload)
        symbol = payload.get("symbol")
        if symbol and payload.get("quantity") is not None:
            payload["quantity"] = await self.normalize_quantity(symbol, payload["quantity"], payload.get("type") == "MARKET")
        if symbol and payload.get("stopPrice") is not None:
            payload["stopPrice"] = await self.normalize_price(symbol, payload["stopPrice"])
        if symbol and payload.get("price") is not None:
            payload["price"] = await self.normalize_price(symbol, payload["price"])
        params = self._signed_params(payload)
        response = await self.client.post("/fapi/v1/order", params=params, headers=self._headers())
        if response.status_code >= 400:
            raise RuntimeError(f"Binance Futures order error {response.status_code}: {response.text}")
        return response.json()

    async def create_algo_order(self, **payload) -> dict:
        if not self.settings.real_orders_enabled:
            raise RuntimeError("Real orders are disabled. Use paper mode or set DRY_RUN_FORCE=false intentionally.")
        symbol = payload.get("symbol")
        if symbol and payload.get("quantity") is not None:
            is_market_type = payload.get("type") in {"MARKET", "STOP_MARKET", "TAKE_PROFIT_MARKET"}
            payload["quantity"] = await self.normalize_quantity(symbol, payload["quantity"], is_market_type)
        trigger_price = payload.pop("stopPrice", None)
        if trigger_price is not None:
            payload["triggerPrice"] = trigger_price
        if symbol and payload.get("triggerPrice") is not None:
            payload["triggerPrice"] = await self.normalize_price(symbol, payload["triggerPrice"])
        if symbol and payload.get("price") is not None:
            payload["price"] = await self.normalize_price(symbol, payload["price"])
        payload.setdefault("algoType", "CONDITIONAL")
        params = self._signed_params(payload)
        response = await self.client.post("/fapi/v1/algoOrder", params=params, headers=self._headers())
        if response.status_code >= 400:
            raise RuntimeError(f"Binance Futures algo order error {response.status_code}: {response.text}")
        return response.json()

    async def cancel_open_orders(self, symbol: str) -> dict:
        params = self._signed_params({"symbol": symbol})
        response = await self.client.delete("/fapi/v1/allOpenOrders", params=params, headers=self._headers())
        if response.status_code >= 400:
            raise RuntimeError(f"Binance Futures cancel open orders error {response.status_code}: {response.text}")
        return response.json()

    async def cancel_open_algo_orders(self, symbol: str) -> dict:
        params = self._signed_params({"symbol": symbol})
        response = await self.client.delete("/fapi/v1/algoOpenOrders", params=params, headers=self._headers())
        if response.status_code >= 400:
            raise RuntimeError(f"Binance Futures cancel algo orders error {response.status_code}: {response.text}")
        return response.json()
