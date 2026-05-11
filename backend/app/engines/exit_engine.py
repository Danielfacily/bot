"""Exit Engine — regras de saída: TP, SL, trailing, reversão, momentum, tempo."""
from dataclasses import dataclass
from datetime import datetime
from sqlalchemy.orm import Session

from app.indicators import enrich_indicators
from app.models.trading import Trade
from app.binance_client import BinanceFuturesClient
from app.services.config_store import get_risk_config
from app.services.logger import log_event
from app.services.state import runtime_state
from app.services.trade_sync import sync_exchange_trade_pnl


@dataclass
class ExitDecision:
    action: str
    reason: str
    adverse_score: int
    continuation_score: int
    exit_price: float
    details: dict


class ExitEngine:
    MAX_TRADE_HOURS = 4  # tempo máximo para trades de 15m/1h

    def __init__(self, client: BinanceFuturesClient | None = None):
        self.client = client

    async def manage(self, db: Session, order_manager) -> None:
        """Avalia trades abertos e aplica regras (AI exit + tempo + momentum)."""
        config = get_risk_config(db)
        if not config.get("ai_exit_enabled", True):
            # Mesmo desativado, ainda aplicamos tempo/momentum
            pass

        settings = order_manager.settings
        if settings.trading_mode != "paper":
            try:
                await sync_exchange_trade_pnl(db, order_manager)
            except Exception:
                pass

        open_trades = db.query(Trade).filter(
            Trade.status == "open", Trade.mode == settings.trading_mode
        ).all()
        for trade in open_trades:
            try:
                decision = await self.evaluate_trade(trade, order_manager, config)
                if decision.action == "hold":
                    continue
                if settings.trading_mode == "paper":
                    order_manager.close_paper_trade(db, trade, decision.exit_price, decision.reason)
                else:
                    await order_manager.close_exchange_trade(db, trade, decision.exit_price, decision.reason)
                runtime_state.trailing_peak_roi.pop(trade.id, None)
                log_event(
                    db, "warning", "exit_engine",
                    "Posição fechada pelo Exit Engine.",
                    {
                        "symbol": trade.symbol,
                        "side": trade.side,
                        "reason": decision.reason,
                        "roi": round(float(trade.pnl_pct or 0), 4),
                        "adverse_score": decision.adverse_score,
                        "continuation_score": decision.continuation_score,
                        **decision.details,
                    },
                )
            except Exception as exc:
                log_event(db, "error", "exit_engine", "Falha na avaliação de saída.",
                          {"symbol": trade.symbol, "error": str(exc)})

    async def evaluate_trade(self, trade: Trade, order_manager, config: dict) -> ExitDecision:
        candles = await order_manager.client.klines(trade.symbol, "1m", 80)
        enriched = enrich_indicators(candles).dropna()
        if len(enriched) < 25:
            return self._hold(trade, 0, 0, float(trade.exit_price or trade.entry_price), {"data": "insufficient"})

        latest = enriched.iloc[-1]
        previous = enriched.iloc[-2]
        exit_price = float(latest["close"])
        current_roi = float(trade.pnl_pct or 0)
        peak_roi = max(float(runtime_state.trailing_peak_roi.get(trade.id, current_roi)), current_roi)
        runtime_state.trailing_peak_roi[trade.id] = peak_roi

        adverse_score, continuation_score, details = self._score_market(trade, enriched)
        details.update({"peak_roi": round(peak_roi, 4), "current_roi": round(current_roi, 4)})

        # Time-based exit
        if trade.created_at:
            age_hours = (datetime.utcnow() - trade.created_at).total_seconds() / 3600
            if age_hours > self.MAX_TRADE_HOURS and current_roi < 0:
                details["age_hours"] = round(age_hours, 2)
                return ExitDecision("close", "time_exit", adverse_score, continuation_score, exit_price, details)

        # Momentum reversal exit
        rsi_val = float(latest.get("rsi", 50) or 50)
        min_roi = float(config.get("ai_exit_min_profit_roi", 4.0))
        if trade.side == "LONG" and rsi_val > 75 and current_roi > min_roi:
            return ExitDecision("close", "momentum_reversal_exit", adverse_score, continuation_score, exit_price, details)
        if trade.side == "SHORT" and rsi_val < 25 and current_roi > min_roi:
            return ExitDecision("close", "momentum_reversal_exit", adverse_score, continuation_score, exit_price, details)

        # AI exit rules
        if not config.get("ai_exit_enabled", True):
            return self._hold(trade, adverse_score, continuation_score, exit_price, details)

        giveback = peak_roi - current_roi
        hard_adverse = adverse_score >= 78 and adverse_score > continuation_score + 18
        profit_fade = peak_roi >= min_roi and giveback >= max(2.5, peak_roi * 0.35) and adverse_score >= 55
        breakeven_fade = peak_roi >= 6 and current_roi <= 0.8 and adverse_score >= 50
        loss_cut = current_roi <= -3.0 and adverse_score >= 68
        invalidation = current_roi <= -1.0 and adverse_score >= 84

        if hard_adverse and current_roi > 0:
            return ExitDecision("close", "ai_exhaustion_profit", adverse_score, continuation_score, exit_price, details)
        if profit_fade:
            return ExitDecision("close", "ai_profit_fade", adverse_score, continuation_score, exit_price, details)
        if breakeven_fade:
            return ExitDecision("close", "ai_breakeven_protection", adverse_score, continuation_score, exit_price, details)
        if loss_cut or invalidation:
            return ExitDecision("close", "ai_loss_cut", adverse_score, continuation_score, exit_price, details)

        return self._hold(trade, adverse_score, continuation_score, exit_price, details)

    def _score_market(self, trade: Trade, enriched) -> tuple[int, int, dict]:
        latest = enriched.iloc[-1]
        previous = enriched.iloc[-2]
        recent = enriched.tail(8)
        close = float(latest["close"])
        open_price = float(latest["open"])
        high = float(latest["high"])
        low = float(latest["low"])
        candle_range = max(high - low, close * 0.0001)
        upper_wick = high - max(open_price, close)
        lower_wick = min(open_price, close) - low
        volume_spike = float(latest["relative_volume"]) >= 1.6
        macd_falling = float(latest["macd_hist"]) < float(previous["macd_hist"])
        macd_rising = float(latest["macd_hist"]) > float(previous["macd_hist"])
        ema_bull = float(latest["ema_9"]) >= float(latest["ema_21"])
        ema_bear = float(latest["ema_9"]) <= float(latest["ema_21"])
        force_candle = bool(latest["force_candle"])
        rejection = bool(latest["rejection_candle"])
        rsi_value = float(latest["rsi"])
        recent_high_fail = close < float(recent["high"].max()) and float(latest["high"]) <= float(previous["high"])
        recent_low_fail = close > float(recent["low"].min()) and float(latest["low"]) >= float(previous["low"])

        adverse = 0
        continuation = 0
        reasons = []

        if trade.side == "LONG":
            if close < float(latest["vwap"]):
                adverse += 18; reasons.append("perdeu_vwap")
            else:
                continuation += 14
            if close < float(latest["ema_9"]):
                adverse += 14; reasons.append("abaixo_ema9")
            if ema_bear:
                adverse += 16; reasons.append("ema9_abaixo_ema21")
            elif ema_bull:
                continuation += 12
            if close < open_price and force_candle:
                adverse += 16; reasons.append("candle_vendedor_forca")
            if volume_spike and close < open_price:
                adverse += 14; reasons.append("volume_vendedor")
            if rejection and upper_wick / candle_range > 0.42:
                adverse += 14; reasons.append("rejeicao_topo")
            if rsi_value >= 72 and close < open_price:
                adverse += 10; reasons.append("rsi_extremo_reversao")
            if recent_high_fail:
                adverse += 10; reasons.append("falha_renovar_maxima")
            if macd_falling:
                adverse += 8
            if close > float(latest["vwap"]) and ema_bull and macd_rising:
                continuation += 22
            if volume_spike and close > open_price:
                continuation += 12
        else:
            if close > float(latest["vwap"]):
                adverse += 18; reasons.append("recuperou_vwap")
            else:
                continuation += 14
            if close > float(latest["ema_9"]):
                adverse += 14; reasons.append("acima_ema9")
            if ema_bull:
                adverse += 16; reasons.append("ema9_acima_ema21")
            elif ema_bear:
                continuation += 12
            if close > open_price and force_candle:
                adverse += 16; reasons.append("candle_comprador_forca")
            if volume_spike and close > open_price:
                adverse += 14; reasons.append("volume_comprador")
            if rejection and lower_wick / candle_range > 0.42:
                adverse += 14; reasons.append("rejeicao_fundo")
            if rsi_value <= 28 and close > open_price:
                adverse += 10; reasons.append("rsi_extremo_reversao")
            if recent_low_fail:
                adverse += 10; reasons.append("falha_renovar_minima")
            if macd_rising:
                adverse += 8
            if close < float(latest["vwap"]) and ema_bear and macd_falling:
                continuation += 22
            if volume_spike and close < open_price:
                continuation += 12

        return min(adverse, 100), min(continuation, 100), {
            "reasons": reasons,
            "price": round(close, 8),
            "rsi": round(rsi_value, 2),
            "relative_volume": round(float(latest["relative_volume"]), 2),
        }

    def _hold(self, trade: Trade, adverse: int, continuation: int, exit_price: float, details: dict) -> ExitDecision:
        return ExitDecision("hold", "hold", adverse, continuation, exit_price, details)


# Backward compatibility
AIExitManager = ExitEngine
