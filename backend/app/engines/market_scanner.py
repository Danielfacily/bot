"""Market Scanner — ranqueia ativos com base em volume, volatilidade e momentum."""
from datetime import datetime
import math
from app.binance_client import BinanceFuturesClient
from app.config import get_settings


class MarketScanner:
    def __init__(self, client: BinanceFuturesClient | None = None):
        self.settings = get_settings()
        self.client = client or BinanceFuturesClient(self.settings)

    async def scan(self, limit: int = 30) -> list[dict]:
        try:
            exchange, tickers, books = await self._fetch_market_data()
            active = {
                item["symbol"]
                for item in exchange.get("symbols", [])
                if item.get("contractType") == "PERPETUAL"
                and item.get("quoteAsset") == self.settings.quote_asset
                and item.get("status") == "TRADING"
            }
            book_map = {item["symbol"]: item for item in books}
            ranked = []
            for ticker in tickers:
                symbol = ticker.get("symbol", "")
                if symbol not in active:
                    continue
                price = float(ticker.get("lastPrice", 0) or 0)
                quote_volume = float(ticker.get("quoteVolume", 0) or 0)
                price_change_pct = abs(float(ticker.get("priceChangePercent", 0) or 0))
                high = float(ticker.get("highPrice", 0) or 0)
                low = float(ticker.get("lowPrice", 0) or 0)
                weighted_avg = float(ticker.get("weightedAvgPrice", 0) or 0) or price
                count = float(ticker.get("count", 0) or 0)
                if price <= 0 or quote_volume < self.settings.min_quote_volume:
                    continue
                book = book_map.get(symbol, {})
                bid = float(book.get("bidPrice", price) or price)
                ask = float(book.get("askPrice", price) or price)
                spread_pct = ((ask - bid) / price) * 100 if price else 99
                if spread_pct > self.settings.max_spread_pct:
                    continue
                volatility_pct = ((high - low) / price) * 100 if price else 0
                atr_rel = self._atr_rel(high, low, price, weighted_avg)
                relative_volume = self._relative_volume_proxy(
                    quote_volume, price_change_pct, volatility_pct, count, weighted_avg
                )
                # Score components
                momentum_score = min(price_change_pct * 3, 35)
                volume_score = min(math.log10(max(quote_volume, 1)) * 4, 30)
                rel_vol_score = min(relative_volume * 10, 20)
                volatility_score = min(volatility_pct * 2, 15)
                atr_rel_score = min(atr_rel * 8, 15)  # nova componente
                spread_penalty = min(spread_pct * 40, 20)
                score = (
                    momentum_score
                    + volume_score
                    + rel_vol_score
                    + volatility_score
                    + atr_rel_score
                    - spread_penalty
                )
                ranked.append(
                    {
                        "symbol": symbol,
                        "price": price,
                        "price_change_pct": price_change_pct,
                        "quote_volume": quote_volume,
                        "relative_volume": relative_volume,
                        "volatility_pct": volatility_pct,
                        "atr_rel": round(atr_rel, 4),
                        "spread_pct": spread_pct,
                        "score": round(max(score, 0), 2),
                        "updated_at": datetime.utcnow(),
                    }
                )
            return sorted(ranked, key=lambda item: item["score"], reverse=True)[:limit]
        except Exception:
            return self._fallback_hot_coins(limit)

    async def _fetch_market_data(self) -> tuple[dict, list[dict], list[dict]]:
        exchange = await self.client.exchange_info()
        tickers = await self.client.ticker_24h()
        books = await self.client.book_ticker()
        return exchange, tickers, books

    def _atr_rel(self, high: float, low: float, price: float, weighted_avg: float) -> float:
        """Proxy de ATR relativo: range diário normalizado pelo weighted avg."""
        if price <= 0 or weighted_avg <= 0:
            return 0.0
        return (high - low) / weighted_avg * 100

    def _relative_volume_proxy(self, quote_volume: float, price_change_pct: float,
                                volatility_pct: float, count: float, weighted_avg: float) -> float:
        """Proxy melhorado: combina volume bruto, número de trades e impulso."""
        base = math.log10(max(quote_volume, 1)) / 8
        # trades-per-dollar como proxy de atividade real
        trade_density = math.log10(max(count, 1)) / 7 if count > 0 else 0
        impulse = (price_change_pct + volatility_pct) / 10
        score = base + trade_density + impulse * 0.6
        return round(max(0.5, min(score, 5)), 2)

    def _fallback_hot_coins(self, limit: int) -> list[dict]:
        symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "LINKUSDT"]
        now = datetime.utcnow()
        coins = []
        for index, symbol in enumerate(symbols[:limit]):
            coins.append(
                {
                    "symbol": symbol,
                    "price": 1000 / (index + 1),
                    "price_change_pct": 2.5 + index,
                    "quote_volume": 50_000_000 + index * 5_000_000,
                    "relative_volume": 1.5 + index * 0.2,
                    "volatility_pct": 1.2 + index * 0.3,
                    "atr_rel": 1.2 + index * 0.2,
                    "spread_pct": 0.03,
                    "score": 80 - index * 3,
                    "updated_at": now,
                }
            )
        return coins
