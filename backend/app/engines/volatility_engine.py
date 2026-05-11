"""Volatility Engine — compressão/expansão de volatilidade."""
from dataclasses import dataclass
import pandas as pd
import numpy as np


@dataclass
class VolatilityResult:
    atr_relative: float
    bb_width: float
    bb_squeeze: bool
    expansion_detected: bool
    regime: str
    setup_vc_expansion: bool
    score: float


class VolatilityEngine:
    def analyze(self, df: pd.DataFrame) -> VolatilityResult:
        if df is None or len(df) < 30:
            return VolatilityResult(0.0, 0.0, False, False, "normal", False, 0.0)

        close = df["close"]
        high = df["high"]
        low = df["low"]

        atr_val = float(df["atr"].dropna().iloc[-1]) if "atr" in df.columns and not df["atr"].dropna().empty else 0.0
        curr_price = float(close.iloc[-1])
        atr_rel = (atr_val / curr_price * 100) if curr_price > 0 else 0.0

        if "bb_upper" in df.columns and "bb_lower" in df.columns and "bb_mid" in df.columns:
            bb_upper = float(df["bb_upper"].iloc[-1])
            bb_lower = float(df["bb_lower"].iloc[-1])
            bb_mid = float(df["bb_mid"].iloc[-1])
        else:
            bb_upper = bb_lower = bb_mid = curr_price
        bb_width = (bb_upper - bb_lower) / bb_mid if bb_mid > 0 else 0.0

        bb_squeeze = False
        if "bb_upper" in df.columns and "bb_lower" in df.columns and "bb_mid" in df.columns:
            hist_width = ((df["bb_upper"] - df["bb_lower"]) / df["bb_mid"].replace(0, np.nan)).tail(50).dropna()
            if len(hist_width) > 10:
                bb_squeeze = bb_width < float(hist_width.quantile(0.40))

        curr_range = float(high.iloc[-1]) - float(low.iloc[-1])
        expansion_detected = curr_range > atr_val * 1.5 if atr_val > 0 else False

        if bb_squeeze and not expansion_detected:
            regime = "compression"
        elif expansion_detected:
            regime = "expansion"
        else:
            regime = "normal"

        prev_3_range = float((high.iloc[-4:-1] - low.iloc[-4:-1]).mean()) if len(df) >= 5 else curr_range
        setup_vc = (prev_3_range < atr_val * 0.7) and expansion_detected if atr_val > 0 else False

        score = 0.0
        if 0.3 <= atr_rel <= 5.0:
            score += 20
        if regime == "expansion":
            score += 30
        if setup_vc:
            score += 40
        if atr_rel > 5.0:
            score -= 30

        return VolatilityResult(
            atr_relative=round(atr_rel, 4),
            bb_width=round(bb_width, 6),
            bb_squeeze=bb_squeeze,
            expansion_detected=expansion_detected,
            regime=regime,
            setup_vc_expansion=setup_vc,
            score=round(max(0.0, min(score, 100.0)), 2),
        )
