import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import SessionLocal, init_db
from app.engines.market_scanner import MarketScanner
from app.engines.execution_engine import ExecutionEngine
from app.engines.risk_engine import RiskEngine
from app.engines.entry_engine import EntryEngine
from app.engines.exit_engine import ExitEngine
from app.routes.api import router
from app.services.logger import log_event
from app.services.state import runtime_state
from app.services.trade_sync import sync_exchange_trade_pnl
from app.services.websocket_manager import ws_manager
from app.services.config_store import get_risk_config
from app.models.trading import ModelFeatures, ModelPrediction, RiskEvent, Trade


async def reconcile_exchange_trades(db, execution_engine: ExecutionEngine) -> None:
    settings = get_settings()
    if settings.trading_mode == "paper" or not settings.binance_api_key or not settings.binance_api_secret:
        return
    try:
        positions = await execution_engine.client.position_risk()
        open_symbols = {row["symbol"] for row in positions if float(row.get("positionAmt", 0) or 0) != 0}
        for trade in db.query(Trade).filter(Trade.status == "open", Trade.mode == settings.trading_mode).all():
            if trade.symbol not in open_symbols:
                trade.status = "closed"
                trade.closed_at = trade.updated_at
                log_event(db, "info", "sync", "Trade local fechado: posição não existe na Binance.", {"symbol": trade.symbol})
        db.commit()
    except Exception as exc:
        log_event(db, "warning", "sync", "Falha ao sincronizar posições Binance.", {"error": str(exc)})


async def current_trading_balance(execution_engine: ExecutionEngine) -> float:
    settings = get_settings()
    if settings.trading_mode == "paper":
        return runtime_state.balance
    try:
        account = await execution_engine.client.account()
        usdt = next((asset for asset in account.get("assets", []) if asset.get("asset") == "USDT"), None)
        if usdt:
            return float(usdt.get("availableBalance") or usdt.get("walletBalance") or runtime_state.balance)
    except Exception:
        return runtime_state.balance
    return runtime_state.balance


async def monitor_paper_trades(db, execution_engine: ExecutionEngine) -> None:
    open_trades = db.query(Trade).filter(Trade.status == "open", Trade.mode == "paper").all()
    if not open_trades:
        return
    scanner_client = MarketScanner().client
    for trade in open_trades:
        try:
            candles = await scanner_client.klines(trade.symbol, "1m", 2)
            latest = candles.iloc[-1]
            high = float(latest["high"])
            low = float(latest["low"])
            close = float(latest["close"])
            if trade.side == "LONG":
                if low <= trade.stop_loss:
                    execution_engine.close_paper_trade(db, trade, trade.stop_loss, "stop_loss")
                    log_event(db, "warning", "paper", "Stop loss simulado.", {"symbol": trade.symbol})
                    asyncio.create_task(ws_manager.broadcast_trade({"symbol": trade.symbol, "event": "stop_loss"}))
                elif high >= trade.take_profit:
                    execution_engine.close_paper_trade(db, trade, trade.take_profit, "take_profit")
                    log_event(db, "info", "paper", "Take profit simulado.", {"symbol": trade.symbol})
                    asyncio.create_task(ws_manager.broadcast_trade({"symbol": trade.symbol, "event": "take_profit"}))
                else:
                    trade.pnl = round((close - trade.entry_price) * trade.quantity, 4)
            else:
                if high >= trade.stop_loss:
                    execution_engine.close_paper_trade(db, trade, trade.stop_loss, "stop_loss")
                    log_event(db, "warning", "paper", "Stop loss simulado.", {"symbol": trade.symbol})
                    asyncio.create_task(ws_manager.broadcast_trade({"symbol": trade.symbol, "event": "stop_loss"}))
                elif low <= trade.take_profit:
                    execution_engine.close_paper_trade(db, trade, trade.take_profit, "take_profit")
                    log_event(db, "info", "paper", "Take profit simulado.", {"symbol": trade.symbol})
                    asyncio.create_task(ws_manager.broadcast_trade({"symbol": trade.symbol, "event": "take_profit"}))
                else:
                    trade.pnl = round((trade.entry_price - close) * trade.quantity, 4)
        except Exception as exc:
            log_event(db, "error", "paper", "Erro ao monitorar trade paper.", {"symbol": trade.symbol, "error": str(exc)})
    db.commit()


async def scanner_loop() -> None:
    settings = get_settings()
    while True:
        try:
            scanner = MarketScanner()
            coins = await scanner.scan(30)
            runtime_state.update_hot_coins(coins)
        except Exception:
            pass
        await asyncio.sleep(settings.scanner_interval_seconds)


async def strategy_loop() -> None:
    settings = get_settings()
    while True:
        if runtime_state.running and not runtime_state.kill_switch:
            db = SessionLocal()
            try:
                coins = runtime_state.hot_coins[:8]
                entry_engine = EntryEngine()
                risk_engine = RiskEngine()
                execution_engine = ExecutionEngine()
                exit_engine = ExitEngine()
                risk_config = get_risk_config(db)
                leverage = int(risk_config["leverage"])
                await monitor_paper_trades(db, execution_engine)
                await sync_exchange_trade_pnl(db, execution_engine)
                # Run exit engine
                try:
                    await exit_engine.manage(db, execution_engine)
                except Exception as exc:
                    log_event(db, "error", "exit_engine", "Erro no exit engine.", {"error": str(exc)})

                trading_balance = await current_trading_balance(execution_engine)
                for coin in coins:
                    signal = None
                    try:
                        signal = await entry_engine.analyze(db, coin["symbol"], "15m")
                        atr = float(signal.features.get("atr", 0))
                        target_move = float(signal.features.get("target_move_pct") or 0)
                        decision = risk_engine.evaluate(
                            db,
                            signal.symbol,
                            signal.direction,
                            signal.price,
                            atr,
                            trading_balance,
                            leverage,
                            signal.score,
                            target_move,
                        )
                        if not decision.allowed:
                            signal.accepted = False
                            signal.rejection_reason = decision.reason
                            db.commit()
                            # Log risk events for major blocks
                            if "consecutiv" in decision.reason.lower() or "exposição" in decision.reason.lower() or "limite de posições" in decision.reason.lower():
                                db.add(RiskEvent(
                                    event_type="block",
                                    reason=decision.reason,
                                    details={"symbol": signal.symbol, "score": signal.score},
                                ))
                                db.commit()
                            log_event(db, "info", "strategy", "Sinal rejeitado pelo risco.", {"symbol": signal.symbol, "reason": decision.reason})
                            asyncio.create_task(ws_manager.broadcast_signal({
                                "symbol": signal.symbol, "score": signal.score,
                                "direction": signal.direction, "setup": signal.features.get("setup"),
                                "accepted": False, "reason": decision.reason,
                            }))
                            continue

                        trade = await execution_engine.open_position(
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

                        # Save model features
                        try:
                            db.add(ModelFeatures(
                                trade_id=trade.id,
                                signal_id=signal.id,
                                symbol=signal.symbol,
                                setup=signal.features.get("setup", "none"),
                                features=signal.features,
                            ))
                            if signal.ml_probability is not None:
                                db.add(ModelPrediction(
                                    signal_id=signal.id,
                                    probability=float(signal.ml_probability),
                                    features_used=signal.features,
                                ))
                            db.commit()
                        except Exception:
                            db.rollback()

                        log_event(
                            db, "info", "strategy",
                            "Trade aberto na Binance Futures." if settings.trading_mode != "paper" else "Trade paper aberto.",
                            {
                                "symbol": trade.symbol,
                                "side": trade.side,
                                "leverage": trade.leverage,
                                "quantity": trade.quantity,
                                "stop_loss": trade.stop_loss,
                                "take_profit": trade.take_profit,
                                "setup": signal.features.get("setup"),
                            },
                        )
                        asyncio.create_task(ws_manager.broadcast_trade({
                            "symbol": trade.symbol,
                            "side": trade.side,
                            "score": signal.score,
                            "setup": signal.features.get("setup", "none"),
                            "entry": trade.entry_price,
                            "stop_loss": trade.stop_loss,
                            "take_profit": trade.take_profit,
                        }))
                        asyncio.create_task(ws_manager.broadcast_signal({
                            "symbol": signal.symbol, "score": signal.score,
                            "direction": signal.direction, "setup": signal.features.get("setup"),
                            "accepted": True,
                        }))
                    except Exception as exc:
                        try:
                            if signal is not None:
                                signal.accepted = False
                                signal.rejection_reason = str(exc)[:500]
                                db.commit()
                            log_event(db, "error", "strategy", "Falha ao abrir trade.", {"symbol": coin.get("symbol"), "error": str(exc)})
                        except Exception:
                            pass
            except Exception as exc:
                try:
                    log_event(db, "error", "strategy", "Erro no loop de estratégia.", {"error": str(exc)})
                except Exception:
                    pass
            finally:
                db.close()
        await asyncio.sleep(settings.strategy_interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    runtime_state.balance = settings.paper_initial_balance
    init_db()
    scanner_task = asyncio.create_task(scanner_loop())
    strategy_task = asyncio.create_task(strategy_loop())
    yield
    scanner_task.cancel()
    strategy_task.cancel()


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
