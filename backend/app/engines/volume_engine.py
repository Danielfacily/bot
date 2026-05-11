"""Volume Engine — breakouts com volume, spikes, absorção e falhas."""
from dataclasses import dataclass
import pandas as pd


@dataclass
class VolumeResult:
    relative_volume: float
    volume_spike: bool
    breakout_confirmed: bool
    absorption: bool
    breakout_failure: bool
    volume_trend: str
    delta_positive: bool
    score: float


class VolumeEngine:
    def analyze(self, df: pd.DataFrame) -> VolumeResult:
        if df is None or len(df) < 25:
            return VolumeResult(1.0, False, False, False, False, "flat", True, 0.0)

        vol = df["volume"]
        close = df["close"]
        high = df["high"]
        low = df["low"]

        vol_ma20 = vol.rolling(20).mean()
        curr_vol = float(vol.iloc[-1])
        avg_vol = float(vol_ma20.iloc[-1]) if not pd.isna(vol_ma20.iloc[-1]) else curr_vol
        rel_vol = curr_vol / avg_vol if avg_vol > 0 else 1.0

        spike = rel_vol > 2.0

        is_breakout_high = bool(df["breakout_high"].iloc[-1]) if "breakout_high" in df.columns else False
        is_breakout_low = bool(df["breakdown_low"].iloc[-1]) if "breakdown_low" in df.columns else False
        breakout_confirmed = (is_breakout_high or is_breakout_low) and rel_vol > 1.5

        body = abs(float(close.iloc[-1]) - float(df["open"].iloc[-1]))
        candle_range = float(high.iloc[-1]) - float(low.iloc[-1])
        absorption = curr_vol > avg_vol * 1.5 and (body / candle_range < 0.20 if candle_range > 0 else False)

        breakout_failure = (is_breakout_high or is_breakout_low) and rel_vol < 0.8

        recent_vol = float(vol.tail(5).mean())
        prev_vol = float(vol.iloc[-10:-5].mean()) if len(vol) >= 10 else recent_vol
        if recent_vol > prev_vol * 1.15:
            vol_trend = "increasing"
        elif recent_vol < prev_vol * 0.85:
            vol_trend = "decreasing"
        else:
            vol_trend = "flat"

        delta = 0.0
        if "volume_delta_ma" in df.columns and not pd.isna(df["volume_delta_ma"].iloc[-1]):
            delta = float(df["volume_delta_ma"].iloc[-1])
        delta_pos = delta > 0

        score = 0.0
        if rel_vol > 1.35:
            score += 20
        if rel_vol > 2.0:
            score += 15
        if breakout_confirmed:
            score += 25
        if absorption:
            score += 15
        if vol_trend == "increasing":
            score += 15
        if delta_pos:
            score += 10
        if breakout_failure:
            score -= 20

        return VolumeResult(
            relative_volume=round(rel_vol, 3),
            volume_spike=spike,
            breakout_confirmed=breakout_confirmed,
            absorption=absorption,
            breakout_failure=breakout_failure,
            volume_trend=vol_trend,
            delta_positive=delta_pos,
            score=round(max(0.0, min(score, 100.0)), 2),
        )
