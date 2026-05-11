from sqlalchemy.orm import Session
from app.binance_client import BinanceFuturesClient
from app.indicators import enrich_indicators, volume_profile
from app.ml_model import SignalClassifier
from app.models.trading import Metric, Signal


class StrategyEngine:
    def __init__(self, client: BinanceFuturesClient | None = None, classifier: SignalClassifier | None = None):
        self.client = client or BinanceFuturesClient()
        self.classifier = classifier or SignalClassifier()

    async def analyze_symbol(self, db: Session, symbol: str, timeframe: str = "15m") -> Signal:
        df = await self.client.klines(symbol, timeframe, 250)
        enriched = enrich_indicators(df).dropna()
        latest = enriched.iloc[-1]
        previous = enriched.iloc[-2]
        profile = volume_profile(enriched.tail(120))
        features = self._features(latest)
        long_score, long_reasons = self._score_long(latest, previous)
        short_score, short_reasons = self._score_short(latest, previous)
        if long_score >= short_score:
            direction = "LONG"
            score = long_score
            reasons = long_reasons
        else:
            direction = "SHORT"
            score = short_score
            reasons = short_reasons
        features["score"] = score
        features["target_move_pct"] = self._target_move_pct(features, score)
        ml_probability = self.classifier.predict_probability(features)

        signal = Signal(
            symbol=symbol,
            timeframe=timeframe,
            direction=direction,
            score=round(float(score), 2),
            ml_probability=ml_probability,
            price=float(latest["close"]),
            reasons=reasons,
            features=features,
            accepted=False,
        )
        db.add(signal)
        db.add(Metric(symbol=symbol, timeframe=timeframe, values={**features, "volume_profile": profile}))
        db.commit()
        db.refresh(signal)
        return signal

    def _features(self, row) -> dict:
        return {
            "rsi": float(row["rsi"]),
            "macd_hist": float(row["macd_hist"]),
            "relative_volume": float(row["relative_volume"]),
            "volatility_relative": float(row["volatility_relative"]),
            "price_vs_vwap": float((row["close"] - row["vwap"]) / row["close"]),
            "ema_9_vs_21": float((row["ema_9"] - row["ema_21"]) / row["close"]),
            "atr": float(row["atr"]),
            "ema_50_vs_200": float((row["ema_50"] - row["ema_200"]) / row["close"]),
        }

    def _score_long(self, row, previous) -> tuple[float, list[str]]:
        score = 0
        reasons = []
        checks = [
            (row["ema_9"] > row["ema_21"] > row["ema_50"], 18, "Tendência curta positiva."),
            (row["relative_volume"] > 1.35, 16, "Volume acima da média."),
            (bool(row["breakout_high"]), 18, "Rompimento de máxima confirmado."),
            (row["close"] > row["vwap"], 14, "Preço acima da VWAP."),
            (45 <= row["rsi"] <= 72, 12, "RSI sem sobrecompra extrema."),
            (bool(row["force_candle"]) and row["close"] > row["open"], 12, "Candle de força comprador."),
            (0.25 <= row["volatility_relative"] <= 5, 10, "Volatilidade suficiente."),
        ]
        for ok, points, reason in checks:
            if ok:
                score += points
                reasons.append(reason)
        if row["macd_hist"] > previous["macd_hist"]:
            score += 6
            reasons.append("MACD ganhando força.")
        return min(score, 100), reasons

    def _target_move_pct(self, features: dict, score: float) -> float:
        volatility = max(float(features.get("volatility_relative", 0)), 0.15)
        relative_volume = max(float(features.get("relative_volume", 1)), 0.5)
        score_boost = 1 + (max(score, 0) / 250)
        volume_boost = min(relative_volume, 3) / 2
        target = volatility * score_boost * max(volume_boost, 0.75)
        return round(max(0.35, min(target, 5.0)), 4)

    def _score_short(self, row, previous) -> tuple[float, list[str]]:
        score = 0
        reasons = []
        checks = [
            (row["ema_9"] < row["ema_21"] < row["ema_50"], 18, "Tendência curta negativa."),
            (row["relative_volume"] > 1.35, 16, "Volume vendedor forte ou impulso elevado."),
            (bool(row["breakdown_low"]), 18, "Perda de suporte confirmada."),
            (row["close"] < row["vwap"], 14, "Preço abaixo da VWAP."),
            (bool(row["rejection_candle"]) and row["close"] < row["open"], 12, "Rejeição em resistência."),
            (30 <= row["rsi"] <= 58, 12, "RSI favorável sem sobrevenda extrema."),
            (0.25 <= row["volatility_relative"] <= 5, 10, "Volatilidade suficiente."),
        ]
        for ok, points, reason in checks:
            if ok:
                score += points
                reasons.append(reason)
        if row["macd_hist"] < previous["macd_hist"]:
            score += 6
            reasons.append("MACD perdendo força.")
        return min(score, 100), reasons
