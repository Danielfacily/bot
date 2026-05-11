"""Protection Engine — bloqueia entradas em condições adversas."""
from dataclasses import dataclass
import pandas as pd


@dataclass
class ProtectionResult:
    allowed: bool
    reason: str
    checks: dict


class ProtectionEngine:
    MAX_SPREAD_PCT = 0.15
    MIN_RELATIVE_VOLUME = 0.5
    MAX_ATR_RELATIVE = 6.0
    MIN_ATR_RELATIVE = 0.15

    def evaluate(
        self,
        spread_pct: float,
        relative_volume: float,
        atr_relative: float,
        microstructure_thin: bool,
        last_candles: pd.DataFrame | None = None,
        overtrading_blocked: bool = False,
    ) -> ProtectionResult:
        checks = {}
        # Spread só é checado se há dado válido
        checks["spread_ok"] = (spread_pct <= 0) or (spread_pct <= self.MAX_SPREAD_PCT)
        checks["liquidity_ok"] = relative_volume >= self.MIN_RELATIVE_VOLUME and not microstructure_thin
        checks["volatility_ok"] = self.MIN_ATR_RELATIVE <= atr_relative <= self.MAX_ATR_RELATIVE
        checks["no_overtrading"] = not overtrading_blocked

        abnormal_candle = False
        if last_candles is not None and len(last_candles) >= 5 and "atr" in last_candles.columns:
            try:
                atr_val = float(last_candles["atr"].dropna().iloc[-1])
                last_range = float(last_candles["high"].iloc[-1]) - float(last_candles["low"].iloc[-1])
                if atr_val > 0 and last_range > atr_val * 4.0:
                    abnormal_candle = True
            except Exception:
                pass
        checks["no_abnormal_candle"] = not abnormal_candle

        failed = [name for name, passed in checks.items() if not passed]
        allowed = len(failed) == 0

        if not allowed:
            reasons_map = {
                "spread_ok": f"Spread {spread_pct:.3f}% acima do máximo permitido.",
                "liquidity_ok": "Liquidez insuficiente para entrada segura.",
                "volatility_ok": f"Volatilidade ATR {atr_relative:.2f}% fora da faixa operável.",
                "no_overtrading": "Bloqueado: limite de trades atingido (overtrading).",
                "no_abnormal_candle": "Candle anormal detectado — possível evento extremo.",
            }
            reason = " | ".join(reasons_map.get(f, f) for f in failed)
        else:
            reason = "Condições de entrada aprovadas."

        return ProtectionResult(allowed=allowed, reason=reason, checks=checks)
