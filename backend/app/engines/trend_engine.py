"""
Trend Engine — identifica tendência dominante em múltiplos timeframes.
"""
from dataclasses import dataclass, field
import pandas as pd


@dataclass
class TrendResult:
    direction: str
    strength: float
    ema_aligned: bool
    supertrend_bullish: bool
    adx: float
    market_structure: str
    timeframe_agreement: dict
    score: float


class TrendEngine:
    def analyze(self, candles_by_tf: dict[str, pd.DataFrame]) -> TrendResult:
        agreement = {}
        for tf, df in candles_by_tf.items():
            if df is None or len(df) < 50:
                agreement[tf] = "neutral"
                continue
            row = df.iloc[-1]
            agreement[tf] = self._direction_from_row(row)

        weights = {"1m": 0.10, "5m": 0.15, "15m": 0.35, "1h": 0.40}
        weighted_bull = sum(weights.get(tf, 0.25) for tf, d in agreement.items() if d == "bullish")
        weighted_bear = sum(weights.get(tf, 0.25) for tf, d in agreement.items() if d == "bearish")

        if weighted_bull > weighted_bear and weighted_bull > 0.35:
            direction = "bullish"
        elif weighted_bear > weighted_bull and weighted_bear > 0.35:
            direction = "bearish"
        else:
            direction = "neutral"

        primary_df = candles_by_tf.get("15m")
        if primary_df is None or len(primary_df) == 0:
            primary_df = candles_by_tf.get("1h")
        if primary_df is None or len(primary_df) == 0:
            primary_df = candles_by_tf.get("5m")
        row_primary = primary_df.iloc[-1] if primary_df is not None and len(primary_df) > 0 else None

        ema_aligned = False
        st_bullish = False
        adx_val = 0.0
        struct = "neutral"
        strength = 0.0

        if row_primary is not None:
            ema9 = float(row_primary.get("ema_9", 0) or 0)
            ema21 = float(row_primary.get("ema_21", 0) or 0)
            ema50 = float(row_primary.get("ema_50", 0) or 0)
            if direction == "bullish":
                ema_aligned = ema9 > ema21 > ema50
            elif direction == "bearish":
                ema_aligned = ema9 < ema21 < ema50
            st_bullish = int(row_primary.get("supertrend_dir", -1) or -1) == 1
            adx_val = float(row_primary.get("adx", 0) or 0)
            struct = str(row_primary.get("market_structure", "neutral"))
            strength = min(100.0, adx_val * 2)

        trend_score = 0.0
        if direction != "neutral":
            if ema_aligned:
                trend_score += 25
            if st_bullish == (direction == "bullish"):
                trend_score += 20
            if adx_val >= 25:
                trend_score += 20
            elif adx_val >= 20:
                trend_score += 10
            if struct == direction:
                trend_score += 15
            trend_score += (weighted_bull if direction == "bullish" else weighted_bear) * 20

        return TrendResult(
            direction=direction,
            strength=round(strength, 2),
            ema_aligned=ema_aligned,
            supertrend_bullish=st_bullish,
            adx=round(adx_val, 2),
            market_structure=struct,
            timeframe_agreement=agreement,
            score=round(min(trend_score, 100.0), 2),
        )

    def _direction_from_row(self, row) -> str:
        ema9 = float(row.get("ema_9", 0) or 0)
        ema21 = float(row.get("ema_21", 0) or 0)
        ema50 = float(row.get("ema_50", 0) or 0)
        st_dir = int(row.get("supertrend_dir", 0) or 0)
        struct = str(row.get("market_structure", ""))
        bull_signals = (ema9 > ema21, ema21 > ema50, st_dir == 1, struct == "bullish")
        bear_signals = (ema9 < ema21, ema21 < ema50, st_dir == -1, struct == "bearish")
        bull_count = sum(1 for s in bull_signals if s)
        bear_count = sum(1 for s in bear_signals if s)
        if bull_count >= 3:
            return "bullish"
        if bear_count >= 3:
            return "bearish"
        return "neutral"
