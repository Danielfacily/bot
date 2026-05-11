import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import get_settings
from app.database import SessionLocal, init_db
from app.market_scanner import MarketScanner
from app.order_manager import OrderManager
from app.risk_manager import RiskManager
from app.routes.api import router
from app.services.logger import log_alert, log_event, print_daily_summary
from app.services.state import runtime_state
from app.services.trade_sync import sync_exchange_trade_pnl
from app.strategy_engine import StrategyEngine
from app.models.trading import Trade
from app.services.config_store import get_risk_config


# ── SINCRONIZAÇÃO COM A EXCHANGE ─────────────────────────────────────────────────

async def reconcile_exchange_trades(db, order_manager: OrderManager) -> None:
    """Marca como fechados trades locais que não têm mais posição na exchange."""
    settings = get_settings()
    if settings.trading_mode == "paper" or not settings.binance_api_key or not settings.binance_api_secret:
        return
    try:
        positions = await order_manager.client.position_risk()
        open_symbols = {row["symbol"] for row in positions if float(row.get("positionAmt", 0) or 0) != 0}
        for trade in db.query(Trade).filter(Trade.status == "open", Trade.mode == settings.trading_mode).all():
            if trade.symbol not in open_symbols:
                pnl = float(trade.pnl or 0)
                trade.status = "closed"
                trade.closed_at = trade.updated_at
                runtime_state.record_trade_closed(pnl)
                log_event(db, "info", "sync", "Trade fechado pela reconciliação com a exchange.", {"symbol": trade.symbol})
        db.commit()
    except Exception as exc:
        log_event(db, "warning", "sync", "Falha na reconciliação com a exchange.", {"error": str(exc)})


async def current_trading_balance(order_manager: OrderManager) -> float:
    settings = get_settings()
    if settings.trading_mode == "paper":
        return runtime_state.balance
    try:
        account = await order_manager.client.account()
        usdt = next((asset for asset in account.get("assets", []) if asset.get("asset") == "USDT"), None)
        if usdt:
            balance = float(usdt.get("availableBalance") or usdt.get("walletBalance") or runtime_state.balance)
            runtime_state.balance = balance
            return balance
    except Exception:
        return runtime_state.balance
    return runtime_state.balance


# ── MONITORAMENTO DE PAPER TRADES ────────────────────────────────────────────────

async def monitor_paper_trades(db, order_manager: OrderManager, risk_config: dict) -> None:
    """
    Monitora trades em modo paper:
      - Verifica SL e TP no candle mais recente
      - Implementa trailing stop após TP1 (se habilitado)
      - Implementa breakeven após TP1 (se habilitado)
      - Atualiza PnL não-realizado de posições abertas
    """
    open_trades = db.query(Trade).filter(Trade.status == "open", Trade.mode == "paper").all()
    if not open_trades:
        return

    trailing_enabled = risk_config.get("trailing_stop_enabled", True)
    breakeven_enabled = risk_config.get("break_even_enabled", True)

    for trade in open_trades:
        try:
            candles = await MarketScanner().client.klines(trade.symbol, "1m", 3)
            latest = candles.iloc[-1]
            high = float(latest["high"])
            low = float(latest["low"])
            close = float(latest["close"])

            # PnL não-realizado
            if trade.side == "LONG":
                unrealized_pnl = (close - trade.entry_price) * trade.quantity
            else:
                unrealized_pnl = (trade.entry_price - close) * trade.quantity
            trade.pnl = round(unrealized_pnl, 4)

            # ROI em % da margem
            margin = max(trade.entry_price * trade.quantity / max(trade.leverage, 1), 0.001)
            current_roi = (unrealized_pnl / margin) * 100
            peak_roi = max(float(runtime_state.trailing_peak_roi.get(trade.id, current_roi)), current_roi)
            runtime_state.trailing_peak_roi[trade.id] = peak_roi

            tp1 = float(trade.take_profit_1) if hasattr(trade, "take_profit_1") and trade.take_profit_1 else None
            tp2 = float(trade.take_profit)

            if trade.side == "LONG":
                # Trailing stop: ativado após TP1
                if trailing_enabled and peak_roi >= 8:
                    giveback_threshold = max(3.0, peak_roi * 0.35)
                    if current_roi <= peak_roi - giveback_threshold:
                        order_manager.close_paper_trade(db, trade, close, "trailing_stop")
                        runtime_state.record_trade_closed(float(trade.pnl or 0))
                        runtime_state.trailing_peak_roi.pop(trade.id, None)
                        log_event(db, "info", "paper", "Trailing stop paper executado.", {"symbol": trade.symbol, "roi": round(current_roi, 2)})
                        continue

                # Breakeven: mover SL para entry após atingir TP1
                if breakeven_enabled and tp1 and high >= tp1 and trade.stop_loss < trade.entry_price:
                    trade.stop_loss = trade.entry_price
                    log_event(db, "info", "paper", "Stop movido para breakeven após TP1.", {"symbol": trade.symbol})

                # Stop Loss
                if low <= trade.stop_loss:
                    order_manager.close_paper_trade(db, trade, trade.stop_loss, "stop_loss")
                    runtime_state.record_trade_closed(float(trade.pnl or 0))
                    runtime_state.trailing_peak_roi.pop(trade.id, None)
                    log_event(db, "warning", "paper", "Stop loss paper executado.", {"symbol": trade.symbol, "exit": trade.stop_loss})

                # Take Profit
                elif high >= tp2:
                    order_manager.close_paper_trade(db, trade, tp2, "take_profit")
                    runtime_state.record_trade_closed(float(trade.pnl or 0))
                    runtime_state.trailing_peak_roi.pop(trade.id, None)
                    log_event(db, "info", "paper", "Take profit paper executado.", {"symbol": trade.symbol, "exit": tp2})

            else:  # SHORT
                # Trailing stop
                if trailing_enabled and peak_roi >= 8:
                    giveback_threshold = max(3.0, peak_roi * 0.35)
                    if current_roi <= peak_roi - giveback_threshold:
                        order_manager.close_paper_trade(db, trade, close, "trailing_stop")
                        runtime_state.record_trade_closed(float(trade.pnl or 0))
                        runtime_state.trailing_peak_roi.pop(trade.id, None)
                        log_event(db, "info", "paper", "Trailing stop paper executado.", {"symbol": trade.symbol, "roi": round(current_roi, 2)})
                        continue

                # Breakeven
                if breakeven_enabled and tp1 and low <= tp1 and trade.stop_loss > trade.entry_price:
                    trade.stop_loss = trade.entry_price
                    log_event(db, "info", "paper", "Stop movido para breakeven após TP1.", {"symbol": trade.symbol})

                # Stop Loss
                if high >= trade.stop_loss:
                    order_manager.close_paper_trade(db, trade, trade.stop_loss, "stop_loss")
                    runtime_state.record_trade_closed(float(trade.pnl or 0))
                    runtime_state.trailing_peak_roi.pop(trade.id, None)
                    log_event(db, "warning", "paper", "Stop loss paper executado.", {"symbol": trade.symbol, "exit": trade.stop_loss})

                # Take Profit
                elif low <= tp2:
                    order_manager.close_paper_trade(db, trade, tp2, "take_profit")
                    runtime_state.record_trade_closed(float(trade.pnl or 0))
                    runtime_state.trailing_peak_roi.pop(trade.id, None)
                    log_event(db, "info", "paper", "Take profit paper executado.", {"symbol": trade.symbol, "exit": tp2})

        except Exception as exc:
            log_event(db, "error", "paper", "Erro ao monitorar trade simulado.", {"symbol": trade.symbol, "error": str(exc)})

    db.commit()


# ── LOOPS PRINCIPAIS ──────────────────────────────────────────────────────────────

async def scanner_loop() -> None:
    settings = get_settings()
    log_alert("info", "scanner", "Scanner de mercado iniciado.", {"interval": settings.scanner_interval_seconds})
    while True:
        try:
            scanner = MarketScanner()
            coins = await scanner.scan(30)
            runtime_state.update_hot_coins(coins)
        except Exception as exc:
            log_alert("warning", "scanner", "Erro no scanner de mercado.", {"error": str(exc)})
        await asyncio.sleep(settings.scanner_interval_seconds)


async def strategy_loop() -> None:
    settings = get_settings()
    log_alert("info", "strategy", "Loop de estratégia iniciado.", {
        "timeframe_primary": settings.primary_timeframe,
        "timeframe_confirm": settings.confirmation_timeframe,
        "min_score": settings.min_signal_score,
    })

    while True:
        if not runtime_state.running or runtime_state.kill_switch:
            await asyncio.sleep(settings.strategy_interval_seconds)
            continue

        db = SessionLocal()
        try:
            # Verifica virada de dia e reinicia contadores
            is_new_day = runtime_state.check_new_day()

            risk_config = get_risk_config(db)
            order_manager = OrderManager()

            # Atualiza saldo
            trading_balance = await current_trading_balance(order_manager)

            # Reinicia saldo do dia se mudou
            if is_new_day:
                runtime_state.balance_day_start = trading_balance
                log_event(db, "info", "strategy", "Novo dia iniciado — contadores zerados.", {
                    "balance": trading_balance,
                    "date": runtime_state._current_day,
                })

            # Sumário diário (imprime uma vez por dia, ao começo do novo dia)
            if is_new_day and not runtime_state._daily_summary_printed:
                print_daily_summary(db)
                runtime_state._daily_summary_printed = True

            # Monitora trades existentes
            await monitor_paper_trades(db, order_manager, risk_config)
            await sync_exchange_trade_pnl(db, order_manager)
            await reconcile_exchange_trades(db, order_manager)

            # Gestão ativa de saída por IA
            try:
                from app.services.ai_exit_manager import AIExitManager
                await AIExitManager().manage(db, order_manager)
            except Exception as exc:
                log_event(db, "error", "ai_exit", "Falha no gerenciador IA de saída.", {"error": str(exc)})

            # Verifica limites diários antes de analisar novos sinais
            halted, halt_reason = runtime_state.is_daily_halted(
                max_loss_pct=float(risk_config.get("max_daily_loss_pct", settings.max_daily_loss_pct)),
                max_trades=int(risk_config.get("max_trades_per_day", settings.max_trades_per_day)),
            )
            if halted:
                log_alert("warning", "strategy", halt_reason, {
                    "daily_pnl": round(runtime_state.daily_pnl, 4),
                    "daily_trades": runtime_state.daily_trades,
                    "drawdown_pct": round(runtime_state.daily_drawdown_pct, 2),
                })
                await asyncio.sleep(settings.strategy_interval_seconds)
                db.close()
                continue

            # Análise e abertura de novos sinais
            engine = StrategyEngine()
            risk_manager = RiskManager()
            leverage = int(risk_config["leverage"])
            coins = runtime_state.hot_coins[:8]

            for coin in coins:
                signal = None
                try:
                    signal = await engine.analyze_symbol(db, coin["symbol"], settings.primary_timeframe)
                    atr_val = float(signal.features.get("atr", 0))
                    regime = signal.features.get("regime", "ranging")
                    trend_1h = signal.features.get("trend_1h", "neutral")

                    # Filtro de regime: apenas operar em mercados com tendência
                    if risk_config.get("regime_filter_enabled", True) and regime == "ranging":
                        signal.accepted = False
                        signal.rejection_reason = f"Regime lateral (ADX<25) — aguardando tendência."
                        db.commit()
                        continue

                    # Filtro de volatilidade: evitar mercados planos ou extremamente voláteis
                    volatility_rel = float(signal.features.get("volatility_relative", 0))
                    if risk_config.get("volatility_filter_enabled", True):
                        if volatility_rel < 0.2:
                            signal.accepted = False
                            signal.rejection_reason = "Volatilidade ATR muito baixa — mercado flat."
                            db.commit()
                            continue
                        if volatility_rel > 6.0:
                            signal.accepted = False
                            signal.rejection_reason = f"Volatilidade ATR extrema ({volatility_rel:.1f}%) — risco de liquidação."
                            db.commit()
                            continue

                    decision = risk_manager.evaluate(
                        db,
                        signal.symbol,
                        signal.direction,
                        signal.price,
                        atr_val,
                        trading_balance,
                        leverage,
                        signal.score,
                        float(signal.features.get("target_move_pct") or 0),
                    )

                    if not decision.allowed:
                        signal.accepted = False
                        signal.rejection_reason = decision.reason
                        db.commit()
                        log_event(db, "info", "strategy", "Sinal rejeitado.", {
                            "symbol": signal.symbol,
                            "score": signal.score,
                            "regime": regime,
                            "reason": decision.reason,
                        })
                        continue

                    trade = await order_manager.open_position(
                        db,
                        signal.symbol,
                        signal.direction,
                        signal.price,
                        decision.leverage,
                        decision,
                        signal.id,
                    )
                    signal.accepted = True
                    signal.rejection_reason = None
                    db.commit()

                    # Registra abertura no rastreador diário
                    runtime_state.record_trade_opened()

                    log_event(
                        db,
                        "info",
                        "strategy",
                        "Trade aberto." if settings.trading_mode != "paper" else "Trade paper aberto.",
                        {
                            "symbol": trade.symbol,
                            "side": trade.side,
                            "score": signal.score,
                            "regime": regime,
                            "trend_1h": trend_1h,
                            "leverage": trade.leverage,
                            "quantity": trade.quantity,
                            "entry": trade.entry_price,
                            "stop_loss": trade.stop_loss,
                            "take_profit_1": decision.take_profit_1,
                            "take_profit_2": trade.take_profit,
                        },
                    )

                except Exception as exc:
                    try:
                        if signal is not None:
                            signal.accepted = False
                            signal.rejection_reason = str(exc)[:500]
                            db.commit()
                        log_event(db, "error", "strategy", "Falha ao processar sinal.", {
                            "symbol": coin.get("symbol"),
                            "error": str(exc),
                        })
                    except Exception:
                        pass

        except Exception as exc:
            try:
                log_event(db, "error", "strategy", "Erro crítico no loop de estratégia.", {"error": str(exc)})
            except Exception:
                log_alert("error", "strategy", f"Erro crítico no loop: {exc}")
        finally:
            db.close()

        await asyncio.sleep(settings.strategy_interval_seconds)


# ── APLICAÇÃO FASTAPI ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    runtime_state.balance = settings.paper_initial_balance
    runtime_state.balance_day_start = settings.paper_initial_balance
    init_db()
    log_alert("info", "app", f"Bot iniciado — modo: {settings.trading_mode} | exchange: {settings.exchange_mode}")
    log_alert("info", "app", f"Perfil: alavancagem {settings.default_leverage}x-{settings.max_leverage}x | score mínimo: {settings.min_signal_score}")
    scanner_task = asyncio.create_task(scanner_loop())
    strategy_task = asyncio.create_task(strategy_loop())
    yield
    scanner_task.cancel()
    strategy_task.cancel()
    log_alert("info", "app", "Bot encerrado.")


settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix="/api")
