"""Mean Reversion Engine — preço afastado da média + sinais reversivos."""
from dataclasses import dataclass
import pandas as pd


@dataclass
class MeanReversionResult:
    z_score: float
    rsi: float
    price_vs_vwap_pct: float
    oversold: bool
    overbought: bool
    exhaustion_signal: str
    regime_suitable: bool
    score: float


class MeanReversionEngine:
    def analyze(self, df: pd.DataFrame, market_regime: str = "ranging") -> MeanReversionResult:
        if df is None or len(df) < 25:
            return MeanReversionResult(0.0, 50.0, 0.0, False, False, "none", False, 0.0)

        row = df.iloc[-1]
        curr_close = float(row["close"])

        z = float(df["z_score"].iloc[-1]) if "z_score" in df.columns and not pd.isna(df["z_score"].iloc[-1]) else 0.0
        rsi_val = float(row.get("rsi", 50) or 50)
        vwap_val = float(row.get("vwap", curr_close) or curr_close)
        price_vs_vwap = ((curr_close - vwap_val) / vwap_val * 100) if vwap_val > 0 else 0.0

        oversold = z < -2.0 or rsi_val < 30
        overbought = z > 2.0 or rsi_val > 70

        regime_ok = market_regime == "ranging" or (abs(z) > 2.5)

        body = abs(float(row.get("close", 0)) - float(row.get("open", 0)))
        candle_range = float(row.get("high", 0)) - float(row.get("low", 0))
        force_body = (body / candle_range > 0.55) if candle_range > 0 else False

        exhaustion = "none"
        if oversold and regime_ok and force_body and float(row.get("close", 0)) > float(row.get("open", 0)):
            exhaustion = "long"
        elif overbought and regime_ok and force_body and float(row.get("close", 0)) < float(row.get("open", 0)):
            exhaustion = "short"

        score = 0.0
        if regime_ok and exhaustion != "none":
            score += 50
            if abs(z) > 2.5:
                score += 20
            if abs(z) > 3.0:
                score += 15
            if abs(price_vs_vwap) > 1.5:
                score += 15

        return MeanReversionResult(
            z_score=round(z, 4),
            rsi=round(rsi_val, 2),
            price_vs_vwap_pct=round(price_vs_vwap, 4),
            oversold=oversold,
            overbought=overbought,
            exhaustion_signal=exhaustion,
            regime_suitable=regime_ok,
            score=round(min(score, 100.0), 2),
        )
