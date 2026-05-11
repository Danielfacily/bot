"""Microstructure Engine — order book imbalance e pressão."""
from dataclasses import dataclass
from app.binance_client import BinanceFuturesClient


@dataclass
class MicrostructureResult:
    bid_volume: float
    ask_volume: float
    imbalance: float
    imbalance_signal: str
    spread_pct: float
    liquidity_thin: bool
    score: float


class MicrostructureEngine:
    def __init__(self, client: BinanceFuturesClient | None = None):
        self.client = client or BinanceFuturesClient()

    async def analyze(self, symbol: str) -> MicrostructureResult:
        try:
            depth = await self._get_depth(symbol)
            return self._compute(depth)
        except Exception:
            return MicrostructureResult(0.0, 0.0, 0.0, "neutral", 0.0, False, 0.0)

    async def _get_depth(self, symbol: str) -> dict:
        response = await self.client.client.get("/fapi/v1/depth", params={"symbol": symbol, "limit": 20})
        response.raise_for_status()
        return response.json()

    def _compute(self, depth: dict) -> MicrostructureResult:
        bids = depth.get("bids", [])[:10]
        asks = depth.get("asks", [])[:10]

        bid_vol = sum(float(qty) for _, qty in bids)
        ask_vol = sum(float(qty) for _, qty in asks)
        total = bid_vol + ask_vol

        imbalance = (bid_vol - ask_vol) / total if total > 0 else 0.0

        if imbalance > 0.20:
            signal = "buy_pressure"
        elif imbalance < -0.20:
            signal = "sell_pressure"
        else:
            signal = "neutral"

        best_bid = float(bids[0][0]) if bids else 0.0
        best_ask = float(asks[0][0]) if asks else 0.0
        mid = (best_bid + best_ask) / 2 if (best_bid and best_ask) else 1.0
        spread_pct = ((best_ask - best_bid) / mid * 100) if mid > 0 else 0.0

        thin = spread_pct > 0.15 or total < 10

        score = 0.0
        if signal != "neutral":
            score += 20
        if abs(imbalance) > 0.30:
            score += 20
        if abs(imbalance) > 0.50:
            score += 20
        if thin:
            score -= 30

        return MicrostructureResult(
            bid_volume=round(bid_vol, 4),
            ask_volume=round(ask_vol, 4),
            imbalance=round(imbalance, 4),
            imbalance_signal=signal,
            spread_pct=round(spread_pct, 4),
            liquidity_thin=thin,
            score=round(max(0.0, min(score, 100.0)), 2),
        )
