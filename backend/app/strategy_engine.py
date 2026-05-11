from sqlalchemy.orm import Session
from app.binance_client import BinanceFuturesClient
from app.indicators import enrich_indicators, volume_profile
from app.ml_model import SignalClassifier
from app.models.trading import Metric, Signal


class StrategyEngine:
    """
    Motor de análise técnica e geração de sinais.

    Fluxo de decisão:
      1. Busca candles no timeframe primário (15m) e de confirmação (1h)
      2. Calcula todos os indicadores via enrich_indicators()
      3. Detecta regime de mercado (trending / ranging)
      4. Aplica filtro de volatilidade (ATR relativo)
      5. Pontua sinal LONG e SHORT com sistema de confluência
      6. Exige confirmação no 1h para validar a direção
      7. Score final (0-100) — threshold mínimo configurável (padrão 70)
    """

    def __init__(self, client: BinanceFuturesClient | None = None, classifier: SignalClassifier | None = None):
        self.client = client or BinanceFuturesClient()
        self.classifier = classifier or SignalClassifier()

    async def analyze_symbol(self, db: Session, symbol: str, timeframe: str = "15m") -> Signal:
        # Candles do timeframe primário (15m)
        df_primary = await self.client.klines(symbol, timeframe, 250)
        enriched = enrich_indicators(df_primary).dropna()
        latest = enriched.iloc[-1]
        previous = enriched.iloc[-2]

        # Candles de confirmação (1h)
        try:
            df_1h = await self.client.klines(symbol, "1h", 100)
            enriched_1h = enrich_indicators(df_1h).dropna()
            latest_1h = enriched_1h.iloc[-1] if len(enriched_1h) >= 2 else None
        except Exception:
            latest_1h = None

        regime = str(latest.get("market_regime", "ranging"))
        profile = volume_profile(enriched.tail(120))
        features = self._features(latest)
        features["regime"] = regime
        features["trend_1h"] = self._trend_1h(latest_1h)

        long_score, long_reasons = self._score_long(latest, previous, latest_1h)
        short_score, short_reasons = self._score_short(latest, previous, latest_1h)

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

    # ── FEATURES PARA O MODELO ML ────────────────────────────────────────────────

    def _features(self, row) -> dict:
        return {
            "rsi": float(row["rsi"]),
            "macd_hist": float(row["macd_hist"]),
            "relative_volume": float(row["relative_volume"]),
            "volatility_relative": float(row["volatility_relative"]),
            "price_vs_vwap": float((row["close"] - row["vwap"]) / row["close"]),
            "ema_9_vs_21": float((row["ema_9"] - row["ema_21"]) / row["close"]),
            "ema_50_vs_200": float((row["ema_50"] - row["ema_200"]) / row["close"]),
            "adx": float(row.get("adx", 0) or 0),
            "volume_delta_ma": float(row.get("volume_delta_ma", 0) or 0),
            "atr": float(row["atr"]),
        }

    # ── TENDÊNCIA NO 1H ──────────────────────────────────────────────────────────

    def _trend_1h(self, row_1h) -> str:
        """
        Detecta a tendência macro no 1h pela sequência das EMAs.
        Retorna: 'bullish', 'bearish' ou 'neutral'
        """
        if row_1h is None:
            return "neutral"
        ema9 = float(row_1h["ema_9"])
        ema21 = float(row_1h["ema_21"])
        ema50 = float(row_1h["ema_50"])
        if ema9 > ema21 > ema50:
            return "bullish"
        if ema9 < ema21 < ema50:
            return "bearish"
        return "neutral"

    # ── PONTUAÇÃO LONG ───────────────────────────────────────────────────────────

    def _score_long(self, row, previous, row_1h=None) -> tuple[float, list[str]]:
        """
        Pontua o sinal de LONG com sistema de confluência.

        Pontos máximos por categoria:
          - Confirmação 1h             : +15 (bônus) / -10 (penalidade)
          - Alinhamento de EMAs (15m)  : +18
          - Volume acima da média      : +14
          - Rompimento de máxima       : +16
          - Posição vs VWAP            : +12
          - RSI em zona favorável      : +10
          - Candle de força comprador  : +10
          - Volatilidade operável      : +8
          - Volume Delta positivo      : +8
          - Mercado em tendência (ADX) : +9
          - Momentum MACD crescente    : +6
          - Preço acima da BB sup.     : +5
        Total possível (sem 1h): ~116 → limitado a 100
        Threshold padrão: score >= 70
        """
        score = 0.0
        reasons = []

        # Bônus/penalidade de confirmação no 1h
        trend_1h = self._trend_1h(row_1h)
        if trend_1h == "bullish":
            score += 15
            reasons.append("Tendência de alta confirmada no 1h (EMA 9>21>50).")
        elif trend_1h == "bearish":
            score -= 10  # contra-tendência no timeframe maior = risco elevado

        # Verificações de confluência no 15m
        checks = [
            (row["ema_9"] > row["ema_21"] > row["ema_50"], 18, "Tendência curta positiva (EMA 9>21>50)."),
            (row["relative_volume"] > 1.35, 14, "Volume acima da média (>1.35x)."),
            (bool(row["breakout_high"]), 16, "Rompimento da máxima de 20 candles."),
            (row["close"] > row["vwap"], 12, "Preço acima da VWAP."),
            (45 <= row["rsi"] <= 72, 10, "RSI em zona comprador (45-72)."),
            (bool(row["force_candle"]) and row["close"] > row["open"], 10, "Candle de força comprador (corpo >65%)."),
            (0.25 <= row["volatility_relative"] <= 6.0, 8, "Volatilidade ATR em range operável."),
            (float(row.get("volume_delta_ma", 0) or 0) > 0, 8, "Pressão compradora dominante (Volume Delta +)."),
            (str(row.get("market_regime", "ranging")) == "trending", 9, "Mercado em tendência (ADX >= 25)."),
        ]
        for condition, points, reason in checks:
            if condition:
                score += points
                reasons.append(reason)

        # MACD ganhando momentum
        if row["macd_hist"] > previous["macd_hist"]:
            score += 6
            reasons.append("MACD histograma crescente (momentum comprador).")

        # Breakout acima da Bollinger Band superior
        if row["close"] > row["bb_upper"]:
            score += 5
            reasons.append("Preço rompendo a Bollinger Band superior.")

        return max(0.0, min(float(score), 100.0)), reasons

    # ── PONTUAÇÃO SHORT ──────────────────────────────────────────────────────────

    def _score_short(self, row, previous, row_1h=None) -> tuple[float, list[str]]:
        """
        Pontua o sinal de SHORT — espelho invertido do score LONG.
        Threshold padrão: score >= 70
        """
        score = 0.0
        reasons = []

        # Bônus/penalidade de confirmação no 1h
        trend_1h = self._trend_1h(row_1h)
        if trend_1h == "bearish":
            score += 15
            reasons.append("Tendência de queda confirmada no 1h (EMA 9<21<50).")
        elif trend_1h == "bullish":
            score -= 10  # contra-tendência no 1h = risco elevado

        checks = [
            (row["ema_9"] < row["ema_21"] < row["ema_50"], 18, "Tendência curta negativa (EMA 9<21<50)."),
            (row["relative_volume"] > 1.35, 14, "Volume vendedor forte ou impulso elevado."),
            (bool(row["breakdown_low"]), 16, "Perda da mínima de 20 candles."),
            (row["close"] < row["vwap"], 12, "Preço abaixo da VWAP."),
            (bool(row["rejection_candle"]) and row["close"] < row["open"], 10, "Rejeição em resistência (candle de força vendedor)."),
            (30 <= row["rsi"] <= 58, 10, "RSI em zona vendedor (30-58)."),
            (0.25 <= row["volatility_relative"] <= 6.0, 8, "Volatilidade ATR em range operável."),
            (float(row.get("volume_delta_ma", 0) or 0) < 0, 8, "Pressão vendedora dominante (Volume Delta -)."),
            (str(row.get("market_regime", "ranging")) == "trending", 9, "Mercado em tendência (ADX >= 25)."),
        ]
        for condition, points, reason in checks:
            if condition:
                score += points
                reasons.append(reason)

        # MACD perdendo momentum
        if row["macd_hist"] < previous["macd_hist"]:
            score += 6
            reasons.append("MACD histograma decrescente (momentum vendedor).")

        # Breakdown abaixo da Bollinger Band inferior
        if row["close"] < row["bb_lower"]:
            score += 5
            reasons.append("Preço rompendo a Bollinger Band inferior.")

        return max(0.0, min(float(score), 100.0)), reasons

    # ── ALVO DE MOVIMENTO ────────────────────────────────────────────────────────

    def _target_move_pct(self, features: dict, score: float) -> float:
        volatility = max(float(features.get("volatility_relative", 0)), 0.15)
        relative_volume = max(float(features.get("relative_volume", 1)), 0.5)
        score_boost = 1 + (max(score, 0) / 250)
        volume_boost = min(relative_volume, 3) / 2
        target = volatility * score_boost * max(volume_boost, 0.75)
        return round(max(0.35, min(target, 5.0)), 4)
