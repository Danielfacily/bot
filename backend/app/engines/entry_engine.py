"""
Entry Engine — combina sinais de todos os engines e gera score 0-100.
"""
from dataclasses import dataclass
from sqlalchemy.orm import Session
import pandas as pd

from app.engines.trend_engine import TrendEngine, TrendResult
from app.engines.liquidity_engine import LiquidityEngine, LiquidityResult
from app.engines.volume_engine import VolumeEngine, VolumeResult
from app.engines.volatility_engine import VolatilityEngine, VolatilityResult
from app.engines.mean_reversion_engine import MeanReversionEngine, MeanReversionResult
from app.engines.microstructure_engine import MicrostructureEngine, MicrostructureResult
from app.engines.protection_engine import ProtectionEngine
from app.engines.ai_engine import AIEngine
from app.indicators import enrich_indicators
from app.binance_client import BinanceFuturesClient
from app.models.trading import Signal, Metric


SETUP_NAMES = {
    "breakout_volume": "Breakout com Volume",
    "pullback_institucional": "Pullback Institucional",
    "liquidity_sweep": "Liquidity Sweep",
    "exhaustion_reversal": "Reversão de Exaustão",
    "explosive_momentum": "Momentum Explosivo",
    "microstructure_scalp": "Scalping de Microestrutura",
    "mean_reversion": "Mean Reversion",
    "trend_following": "Trend Following",
    "manipulation_detect": "Detecção de Manipulação",
    "vc_expansion": "Volatility Compression → Expansion",
    "none": "Nenhum setup identificado",
}


@dataclass
class EntrySignal:
    symbol: str
    direction: str
    setup: str
    score: float
    entry_price: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    risk_reward: float
    timeframe: str
    reasons: list
    invalidation: str
    features: dict
    trend_score: float = 0.0
    liquidity_score: float = 0.0
    volume_score: float = 0.0
    volatility_score: float = 0.0
    mean_reversion_score: float = 0.0
    microstructure_score: float = 0.0


class EntryEngine:
    TIMEFRAMES = ["1m", "5m", "15m", "1h"]

    def __init__(self, client: BinanceFuturesClient | None = None, classifier: AIEngine | None = None):
        self.client = client or BinanceFuturesClient()
        self.trend_engine = TrendEngine()
        self.liquidity_engine = LiquidityEngine()
        self.volume_engine = VolumeEngine()
        self.volatility_engine = VolatilityEngine()
        self.mean_reversion_engine = MeanReversionEngine()
        self.microstructure_engine = MicrostructureEngine(self.client)
        self.protection_engine = ProtectionEngine()
        self.classifier = classifier or AIEngine()

    # Backward compat with StrategyEngine.analyze_symbol
    async def analyze_symbol(self, db: Session, symbol: str, timeframe: str = "15m") -> Signal:
        return await self.analyze(db, symbol, timeframe)

    async def analyze(self, db: Session, symbol: str, primary_tf: str = "15m") -> Signal:
        candles = {}
        for tf in self.TIMEFRAMES:
            try:
                df = await self.client.klines(symbol, tf, 200)
                candles[tf] = enrich_indicators(df).dropna()
            except Exception:
                candles[tf] = None

        primary = candles.get(primary_tf) or candles.get("15m") or candles.get("5m")
        if primary is None or len(primary) < 50:
            signal = Signal(
                symbol=symbol, timeframe=primary_tf, direction="LONG",
                score=0.0, price=0.0, reasons=["Dados insuficientes."],
                features={}, accepted=False, rejection_reason="Dados insuficientes.",
                setup="none",
            )
            db.add(signal)
            db.commit()
            db.refresh(signal)
            return signal

        row = primary.iloc[-1]
        prev_row = primary.iloc[-2]
        current_price = float(row["close"])

        trend_result = self.trend_engine.analyze(candles)
        liquidity_result = self.liquidity_engine.analyze(primary)
        volume_result = self.volume_engine.analyze(primary)
        volatility_result = self.volatility_engine.analyze(primary)
        mean_rev_result = self.mean_reversion_engine.analyze(
            primary, str(row.get("market_regime", "ranging"))
        )

        try:
            micro_result = await self.microstructure_engine.analyze(symbol)
        except Exception:
            micro_result = MicrostructureResult(0, 0, 0.0, "neutral", 0.0, False, 0.0)

        atr_rel = float(row.get("volatility_relative", 1.0) or 1.0)
        rel_vol = float(row.get("relative_volume", 1.0) or 1.0)
        protection = self.protection_engine.evaluate(
            spread_pct=micro_result.spread_pct,
            relative_volume=rel_vol,
            atr_relative=atr_rel,
            microstructure_thin=micro_result.liquidity_thin,
            last_candles=primary.tail(5),
        )

        setup, direction, reasons, long_score, short_score = self._detect_setup(
            row, prev_row, trend_result, liquidity_result, volume_result,
            volatility_result, mean_rev_result, micro_result
        )
        score = long_score if direction == "LONG" else short_score

        features = self._build_features(
            row, trend_result, liquidity_result, volume_result,
            volatility_result, mean_rev_result, micro_result
        )

        if not protection.allowed:
            signal = Signal(
                symbol=symbol, timeframe=primary_tf, direction=direction,
                score=round(score, 2), price=current_price,
                reasons=reasons, features=features,
                accepted=False, rejection_reason=protection.reason, setup=setup,
            )
            db.add(signal)
            db.commit()
            db.refresh(signal)
            return signal

        atr_1h = self._get_atr_1h(candles)
        base_atr = float(row.get("atr", 0) or 0)
        effective_atr = atr_1h if atr_1h and atr_1h > base_atr else base_atr
        stop_loss, tp1, tp2 = self._calculate_levels(
            direction, current_price, effective_atr, row, primary, liquidity_result
        )

        rr = abs(tp2 - current_price) / abs(current_price - stop_loss) if abs(current_price - stop_loss) > 0 else 0.0
        invalidation = self._invalidation(direction, current_price, stop_loss, liquidity_result)

        # target_move_pct compatibility for risk engine
        target_move_pct = abs(tp2 - current_price) / current_price * 100 if current_price > 0 else 0.0

        features.update({
            "setup": setup,
            "atr_1h": atr_1h or 0.0,
            "stop_loss": stop_loss,
            "take_profit_1": tp1,
            "take_profit_2": tp2,
            "risk_reward": round(rr, 3),
            "invalidation": invalidation,
            "target_move_pct": round(target_move_pct, 4),
            "score": round(score, 2),
        })

        # ML probability
        ml_prob = self.classifier.predict_probability(features)

        signal = Signal(
            symbol=symbol,
            timeframe=primary_tf,
            direction=direction,
            score=round(score, 2),
            price=current_price,
            ml_probability=ml_prob,
            reasons=reasons,
            features=features,
            accepted=False,
            setup=setup,
        )
        db.add(signal)
        db.add(Metric(symbol=symbol, timeframe=primary_tf, values=features))
        db.commit()
        db.refresh(signal)
        return signal

    def _detect_setup(self, row, prev_row, trend: TrendResult, liq: LiquidityResult,
                      vol: VolumeResult, vlt: VolatilityResult, mr: MeanReversionResult,
                      micro: MicrostructureResult) -> tuple:
        reasons = []
        long_score = 0.0
        short_score = 0.0
        setup = "none"

        # Trend
        if trend.direction == "bullish":
            long_score += trend.score * 0.30
            reasons.append(f"Tendência de alta ({trend.score:.0f}pts): ADX={trend.adx:.1f}, EMA={'alinhada' if trend.ema_aligned else 'mista'}.")
        elif trend.direction == "bearish":
            short_score += trend.score * 0.30
            reasons.append(f"Tendência de baixa ({trend.score:.0f}pts): ADX={trend.adx:.1f}.")

        # Volume
        long_score += vol.score * (0.15 if vol.delta_positive else 0.05)
        short_score += vol.score * (0.15 if not vol.delta_positive else 0.05)
        if vol.volume_spike:
            reasons.append(f"Volume spike detectado ({vol.relative_volume:.1f}x média).")
        if vol.breakout_confirmed:
            reasons.append("Breakout confirmado com volume forte.")

        # Volatility
        long_score += vlt.score * 0.10
        short_score += vlt.score * 0.10
        if vlt.setup_vc_expansion:
            reasons.append("Setup VC→Expansão detectado.")

        # Microstructure
        if micro.imbalance_signal == "buy_pressure":
            long_score += micro.score * 0.10
            reasons.append(f"Pressão compradora no order book (imbalance={micro.imbalance:.2f}).")
        elif micro.imbalance_signal == "sell_pressure":
            short_score += micro.score * 0.10
            reasons.append(f"Pressão vendedora no order book (imbalance={micro.imbalance:.2f}).")

        # Setup detection
        if vol.breakout_confirmed:
            if trend.direction == "bullish":
                long_score += 25
                setup = "breakout_volume"
            elif trend.direction == "bearish":
                short_score += 25
                setup = "breakout_volume"

        ema21 = float(row.get("ema_21", 0) or 0)
        close = float(row.get("close", 0) or 0)
        is_near_ema21 = abs(close - ema21) / ema21 < 0.003 if ema21 > 0 else False
        if trend.direction == "bullish" and trend.ema_aligned and is_near_ema21:
            long_score += 20
            if long_score > short_score:
                setup = "pullback_institucional"
                reasons.append("Pullback para EMA21 em tendência de alta.")
        elif trend.direction == "bearish" and trend.ema_aligned and is_near_ema21:
            short_score += 20
            if short_score > long_score:
                setup = "pullback_institucional"
                reasons.append("Pullback para EMA21 em tendência de baixa.")

        if liq.sweep_detected:
            if liq.setup == "liquidity_sweep_long":
                long_score += liq.score
                setup = "liquidity_sweep"
                reasons.append(f"Liquidity sweep bullish (score={liq.score:.0f}).")
            elif liq.setup == "liquidity_sweep_short":
                short_score += liq.score
                setup = "liquidity_sweep"
                reasons.append(f"Liquidity sweep bearish (score={liq.score:.0f}).")

        if mr.exhaustion_signal == "long" and mr.regime_suitable:
            long_score += mr.score
            if mr.score > 50:
                setup = "exhaustion_reversal"
            reasons.append(f"Exaustão de venda (Z={mr.z_score:.2f}, RSI={mr.rsi:.0f}).")
        elif mr.exhaustion_signal == "short" and mr.regime_suitable:
            short_score += mr.score
            if mr.score > 50:
                setup = "exhaustion_reversal"
            reasons.append(f"Exaustão de compra (Z={mr.z_score:.2f}, RSI={mr.rsi:.0f}).")

        if trend.adx > 35 and vol.volume_spike and vlt.expansion_detected:
            if trend.direction == "bullish":
                long_score += 30
                setup = "explosive_momentum"
                reasons.append(f"Momentum explosivo: ADX={trend.adx:.0f}.")
            elif trend.direction == "bearish":
                short_score += 30
                setup = "explosive_momentum"
                reasons.append(f"Momentum explosivo bearish: ADX={trend.adx:.0f}.")

        if not micro.liquidity_thin and abs(micro.imbalance) > 0.40 and 0 < micro.spread_pct < 0.08:
            if micro.imbalance > 0:
                long_score += 20
                if long_score > short_score and setup == "none":
                    setup = "microstructure_scalp"
            else:
                short_score += 20
                if short_score > long_score and setup == "none":
                    setup = "microstructure_scalp"

        if mr.regime_suitable and mr.exhaustion_signal != "none" and setup == "none":
            setup = "mean_reversion"

        if trend.direction != "neutral" and trend.score > 70 and trend.adx > 30 and setup == "none":
            setup = "trend_following"

        if liq.sweep_detected and liq.fake_breakout:
            if liq.setup == "liquidity_sweep_long":
                long_score += 15
            elif liq.setup == "liquidity_sweep_short":
                short_score += 15
            if setup == "none":
                setup = "manipulation_detect"
            reasons.append("Possível manipulação: sweep + fake breakout.")

        if vlt.setup_vc_expansion:
            if trend.direction == "bullish":
                long_score += 20
            elif trend.direction == "bearish":
                short_score += 20
            if setup == "none":
                setup = "vc_expansion"

        direction = "LONG" if long_score >= short_score else "SHORT"
        long_score = round(min(long_score, 100.0), 2)
        short_score = round(min(short_score, 100.0), 2)
        return setup, direction, reasons, long_score, short_score

    def _calculate_levels(self, direction: str, entry: float, effective_atr: float,
                           row, df: pd.DataFrame, liq: LiquidityResult) -> tuple[float, float, float]:
        atr_stop_mult = 1.5
        stop_dist = max(effective_atr * atr_stop_mult, entry * 0.005)

        if direction == "LONG":
            if liq.liquidity_below:
                struct_sl = liq.liquidity_below[0] - effective_atr * 0.25
                dist_struct = entry - struct_sl
                if effective_atr * 0.7 <= dist_struct <= effective_atr * 5.0:
                    stop_dist = dist_struct
            stop_loss = entry - stop_dist
            tp1 = entry + stop_dist * 1.5
            tp2 = entry + stop_dist * 3.0
            if liq.liquidity_above:
                struct_tp = liq.liquidity_above[0]
                if struct_tp > entry + stop_dist * 1.2:
                    tp2 = struct_tp
                    tp1 = entry + (struct_tp - entry) * 0.5
        else:
            if liq.liquidity_above:
                struct_sl = liq.liquidity_above[0] + effective_atr * 0.25
                dist_struct = struct_sl - entry
                if effective_atr * 0.7 <= dist_struct <= effective_atr * 5.0:
                    stop_dist = dist_struct
            stop_loss = entry + stop_dist
            tp1 = entry - stop_dist * 1.5
            tp2 = entry - stop_dist * 3.0
            if liq.liquidity_below:
                struct_tp = liq.liquidity_below[0]
                if struct_tp < entry - stop_dist * 1.2:
                    tp2 = struct_tp
                    tp1 = entry - (entry - struct_tp) * 0.5

        return round(stop_loss, 6), round(tp1, 6), round(tp2, 6)

    def _get_atr_1h(self, candles: dict) -> float | None:
        df_1h = candles.get("1h")
        if df_1h is not None and len(df_1h) > 0 and "atr" in df_1h.columns:
            series = df_1h["atr"].dropna()
            if len(series) > 0:
                val = float(series.iloc[-1])
                return val if val > 0 else None
        return None

    def _invalidation(self, direction: str, entry: float, sl: float, liq: LiquidityResult) -> str:
        if direction == "LONG":
            below = f"{liq.liquidity_below[0]:.4f}" if liq.liquidity_below else f"{sl * 0.99:.4f}"
            return f"Setup invalidado se preço fechar abaixo de {round(sl, 4)} ou romper {below}."
        above = f"{liq.liquidity_above[0]:.4f}" if liq.liquidity_above else f"{sl * 1.01:.4f}"
        return f"Setup invalidado se preço fechar acima de {round(sl, 4)} ou romper {above}."

    def _build_features(self, row, trend: TrendResult, liq: LiquidityResult,
                         vol: VolumeResult, vlt: VolatilityResult,
                         mr: MeanReversionResult, micro: MicrostructureResult) -> dict:
        close_val = float(row.get("close", 1) or 1) or 1.0
        return {
            "rsi": float(row.get("rsi", 50) or 50),
            "macd_hist": float(row.get("macd_hist", 0) or 0),
            "relative_volume": vol.relative_volume,
            "volatility_relative": vlt.atr_relative,
            "price_vs_vwap": float((float(row.get("close", 0) or 0) - float(row.get("vwap", close_val) or close_val)) / close_val),
            "ema_9_vs_21": float((float(row.get("ema_9", 0) or 0) - float(row.get("ema_21", 0) or 0)) / close_val),
            "ema_50_vs_200": float((float(row.get("ema_50", 0) or 0) - float(row.get("ema_200", 0) or 0)) / close_val),
            "adx": trend.adx,
            "volume_delta_ma": float(row.get("volume_delta_ma", 0) or 0),
            "atr": float(row.get("atr", 0) or 0),
            "z_score": mr.z_score,
            "bb_width": vlt.bb_width,
            "imbalance": micro.imbalance,
            "trend_score": trend.score,
            "liquidity_score": liq.score,
            "volume_score": vol.score,
            "volatility_score": vlt.score,
            "mean_reversion_score": mr.score,
            "microstructure_score": micro.score,
            "supertrend_dir": int(row.get("supertrend_dir", 0) or 0),
            "market_structure": str(row.get("market_structure", "neutral")),
            "market_regime": str(row.get("market_regime", "ranging")),
            "trend_direction": trend.direction,
            "sweep_detected": liq.sweep_detected,
            "volume_spike": vol.volume_spike,
            "vc_expansion": vlt.setup_vc_expansion,
        }
