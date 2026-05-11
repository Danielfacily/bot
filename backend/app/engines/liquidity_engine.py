"""
Liquidity Engine — zonas de liquidez, sweeps, fake breakouts, caça de stops.
"""
from dataclasses import dataclass
import pandas as pd
from app.indicators import swing_highs_lows, atr as atr_fn


@dataclass
class LiquidityResult:
    liquidity_above: list[float]
    liquidity_below: list[float]
    sweep_detected: bool
    sweep_direction: str
    fake_breakout: bool
    rejection_strong: bool
    setup: str
    score: float


class LiquidityEngine:
    def analyze(self, df: pd.DataFrame) -> LiquidityResult:
        if df is None or len(df) < 30:
            return LiquidityResult([], [], False, "none", False, False, "none", 0.0)

        if "atr" in df.columns and not df["atr"].dropna().empty:
            atr_val = float(df["atr"].dropna().iloc[-1])
        else:
            atr_val = float(atr_fn(df).dropna().iloc[-1]) if len(df) > 14 else 0.0

        current = float(df["close"].iloc[-1])
        curr_high = float(df["high"].iloc[-1])
        curr_low = float(df["low"].iloc[-1])
        curr_close = float(df["close"].iloc[-1])
        curr_open = float(df["open"].iloc[-1])

        sh, sl = swing_highs_lows(df.iloc[:-1], lookback=3)
        sh_prices = df["high"][sh].tail(10).values.tolist()
        sl_prices = df["low"][sl].tail(10).values.tolist()

        above = sorted([float(p) for p in sh_prices if p > current])[:3]
        below = sorted([float(p) for p in sl_prices if p < current], reverse=True)[:3]

        sweep_up = False
        if above and curr_high > above[0] and curr_close < above[0]:
            sweep_up = True
        sweep_down = False
        if below and curr_low < below[0] and curr_close > below[0]:
            sweep_down = True

        sweep_detected = sweep_up or sweep_down
        sweep_direction = "up" if sweep_up else ("down" if sweep_down else "none")

        candle_range = curr_high - curr_low
        upper_wick = curr_high - max(curr_open, curr_close)
        lower_wick = min(curr_open, curr_close) - curr_low
        if candle_range > 0:
            fake_breakout = (upper_wick / candle_range > 0.50) or (lower_wick / candle_range > 0.50)
            rejection_strong = (upper_wick / candle_range > 0.60) or (lower_wick / candle_range > 0.60)
        else:
            fake_breakout = False
            rejection_strong = False

        setup = "none"
        score = 0.0
        if sweep_down and below:
            setup = "liquidity_sweep_long"
            score = 70.0
            if rejection_strong:
                score += 15
            if fake_breakout:
                score += 10
        elif sweep_up and above:
            setup = "liquidity_sweep_short"
            score = 70.0
            if rejection_strong:
                score += 15
            if fake_breakout:
                score += 10
        elif rejection_strong:
            score = 30.0

        return LiquidityResult(
            liquidity_above=above,
            liquidity_below=below,
            sweep_detected=sweep_detected,
            sweep_direction=sweep_direction,
            fake_breakout=fake_breakout,
            rejection_strong=rejection_strong,
            setup=setup,
            score=round(min(score, 100.0), 2),
        )
