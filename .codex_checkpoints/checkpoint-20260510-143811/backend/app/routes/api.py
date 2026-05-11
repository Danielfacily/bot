from fastapi import APIRouter, Depends, HTTPException
from datetime import date, datetime
from sqlalchemy import desc, func
from sqlalchemy.orm import Session
from app.backtester import Backtester
from app.binance_client import BinanceFuturesClient
from app.config import get_settings
from app.database import get_db
from app.market_scanner import MarketScanner
from app.models.trading import Backtest, LogEntry, Order, Signal, Trade
from app.order_manager import OrderManager
from app.risk_manager import RiskManager
from app.schemas.trading import AccountBalance, BacktestRequest, BotControl, BotStatus, ExchangePosition, RiskConfig
from app.services.config_store import get_risk_config as load_risk_config, save_risk_config
from app.services.logger import log_event
from app.services.state import runtime_state
from app.services.trade_sync import sync_exchange_trade_pnl

router = APIRouter()


@router.get("/health")
def health() -> dict:
    settings = get_settings()
    return {"status": "ok", "mode": settings.trading_mode, "exchange": settings.exchange_mode, "mainnet_enabled": settings.enable_mainnet}


@router.get("/status", response_model=BotStatus)
async def status(db: Session = Depends(get_db)) -> BotStatus:
    settings = get_settings()
    risk_config = load_risk_config(db)
    paper_open_positions = db.query(Trade).filter(Trade.status == "open", Trade.mode == "paper").count()
    exchange_open_positions = 0
    if settings.trading_mode != "paper" and settings.binance_api_key and settings.binance_api_secret:
        try:
            rows = await BinanceFuturesClient(settings).position_risk()
            exchange_open_positions = sum(1 for row in rows if float(row.get("positionAmt", 0) or 0) != 0)
        except Exception:
            exchange_open_positions = 0
    open_positions = paper_open_positions if settings.trading_mode == "paper" else exchange_open_positions
    daily_pnl = (
        db.query(func.coalesce(func.sum(Trade.pnl), 0))
        .filter(Trade.status == "closed", func.date(Trade.closed_at) == date.today())
        .scalar()
    )
    return BotStatus(
        running=runtime_state.running,
        kill_switch=runtime_state.kill_switch,
        mode=settings.trading_mode,
        exchange=settings.exchange_mode,
        market="USDT-M Futures",
        futures_base_url=settings.base_url,
        mainnet_enabled=settings.enable_mainnet,
        open_positions=open_positions,
        paper_open_positions=paper_open_positions,
        exchange_open_positions=exchange_open_positions,
        max_open_positions=risk_config["max_open_positions"],
        daily_pnl=round(float(daily_pnl or 0), 4),
        balance=runtime_state.balance,
    )


@router.get("/positions/exchange", response_model=list[ExchangePosition])
async def exchange_positions() -> list[ExchangePosition]:
    settings = get_settings()
    if not settings.binance_api_key or not settings.binance_api_secret:
        return []
    try:
        rows = await BinanceFuturesClient(settings).position_risk()
        positions = []
        for row in rows:
            quantity = float(row.get("positionAmt", 0) or 0)
            if quantity == 0:
                continue
            positions.append(
                ExchangePosition(
                    symbol=row.get("symbol", ""),
                    side="LONG" if quantity > 0 else "SHORT",
                    quantity=abs(quantity),
                    entry_price=float(row.get("entryPrice", 0) or 0),
                    mark_price=float(row.get("markPrice", 0) or 0),
                    unrealized_pnl=float(row.get("unRealizedProfit", 0) or 0),
                    leverage=int(float(row.get("leverage", 0) or 0)),
                    liquidation_price=float(row["liquidationPrice"]) if row.get("liquidationPrice") not in {None, "", "0"} else None,
                )
            )
        return positions
    except Exception:
        return []


@router.get("/account/balance", response_model=AccountBalance)
async def account_balance() -> AccountBalance:
    settings = get_settings()
    if not settings.binance_api_key or not settings.binance_api_secret:
        return AccountBalance(
            connected=False,
            mode=settings.trading_mode,
            exchange=settings.exchange_mode,
            message="Configure BINANCE_API_KEY e BINANCE_API_SECRET no .env para consultar saldo da Futures.",
        )
    try:
        account = await BinanceFuturesClient(settings).account()
        usdt_asset = next((asset for asset in account.get("assets", []) if asset.get("asset") == "USDT"), None)
        if not usdt_asset:
            return AccountBalance(
                connected=False,
                mode=settings.trading_mode,
                exchange=settings.exchange_mode,
                message="Saldo USDT não encontrado na conta Futures.",
            )
        return AccountBalance(
            connected=True,
            mode=settings.trading_mode,
            exchange=settings.exchange_mode,
            wallet_balance=float(usdt_asset.get("walletBalance", 0) or 0),
            available_balance=float(usdt_asset.get("availableBalance", 0) or 0),
            unrealized_pnl=float(usdt_asset.get("unrealizedProfit", 0) or 0),
        )
    except Exception as exc:
        return AccountBalance(
            connected=False,
            mode=settings.trading_mode,
            exchange=settings.exchange_mode,
            message=f"Não foi possível consultar a carteira Futures: {exc}",
        )
async def trading_balance_for_mode(settings) -> float:
    if settings.trading_mode == "paper":
        return runtime_state.balance
    try:
        account = await BinanceFuturesClient(settings).account()
        usdt = next((asset for asset in account.get("assets", []) if asset.get("asset") == "USDT"), None)
        if usdt:
            return float(usdt.get("availableBalance") or usdt.get("walletBalance") or runtime_state.balance)
    except Exception:
        return runtime_state.balance
    return runtime_state.balance


@router.post("/control", response_model=BotStatus)
async def control(payload: BotControl, db: Session = Depends(get_db)) -> BotStatus:
    if payload.running is not None:
        runtime_state.running = payload.running
        log_event(db, "info", "control", "Robô iniciado." if payload.running else "Robô parado.")
    if payload.kill_switch is not None:
        runtime_state.kill_switch = payload.kill_switch
        if payload.kill_switch:
            runtime_state.running = False
        log_event(db, "warning", "control", "Kill switch ativado." if payload.kill_switch else "Kill switch desativado.")
    return await status(db)


@router.get("/scanner/hot")
async def hot_coins(limit: int = 20):
    scanner = MarketScanner()
    coins = await scanner.scan(limit)
    runtime_state.update_hot_coins(coins)
    return coins


@router.get("/signals")
def signals(limit: int = 30, db: Session = Depends(get_db)):
    return db.query(Signal).order_by(desc(Signal.created_at)).limit(limit).all()


@router.post("/signals/run")
async def run_signal(symbol: str = "BTCUSDT", timeframe: str = "15m", db: Session = Depends(get_db)):
    from app.strategy_engine import StrategyEngine

    signal = await StrategyEngine().analyze_symbol(db, symbol, timeframe)
    return signal


@router.post("/signals/{signal_id}/force-open")
async def force_open_signal(signal_id: int, db: Session = Depends(get_db)):
    if runtime_state.kill_switch:
        raise HTTPException(423, "Kill switch ativo. Desative antes de aceitar sinais manualmente.")
    signal = db.query(Signal).filter(Signal.id == signal_id).first()
    if not signal:
        raise HTTPException(404, "Sinal não encontrado.")
    if signal.accepted:
        raise HTTPException(400, "Este sinal já foi aceito.")
    settings = get_settings()
    risk_config = load_risk_config(db)
    balance = await trading_balance_for_mode(settings)
    decision = RiskManager().evaluate(
        db,
        signal.symbol,
        signal.direction,
        signal.price,
        float(signal.features.get("atr", 0)),
        balance,
        int(risk_config["leverage"]),
        signal.score,
        float(signal.features.get("target_move_pct") or 0),
        manual_override=True,
    )
    if not decision.allowed:
        signal.rejection_reason = f"Aceite manual bloqueado: {decision.reason}"
        db.commit()
        raise HTTPException(400, decision.reason)
    trade = await OrderManager().open_position(
        db,
        signal.symbol,
        signal.direction,
        signal.price,
        decision.leverage,
        decision,
        signal.id,
    )
    signal.accepted = True
    signal.rejection_reason = "Aceito manualmente."
    db.commit()
    log_event(
        db,
        "warning",
        "manual",
        "Sinal aceito manualmente e posição aberta.",
        {"signal_id": signal.id, "symbol": trade.symbol, "side": trade.side, "leverage": trade.leverage, "quantity": trade.quantity},
    )
    return {"accepted": True, "signal": signal, "trade": trade}


@router.get("/trades")
async def trades(limit: int = 50, mode: str = "current", db: Session = Depends(get_db)):
    settings = get_settings()
    if mode in {"current", settings.trading_mode} and settings.trading_mode != "paper":
        try:
            await sync_exchange_trade_pnl(db, OrderManager())
        except Exception as exc:
            log_event(db, "warning", "sync", "Não foi possível atualizar PnL das posições.", {"error": str(exc)})
    query = db.query(Trade)
    if mode == "current":
        query = query.filter(Trade.mode == settings.trading_mode)
    elif mode != "all":
        query = query.filter(Trade.mode == mode)
    return query.order_by(desc(Trade.created_at)).limit(limit).all()


@router.get("/performance/summary")
async def performance_summary(mode: str = "current", db: Session = Depends(get_db)):
    settings = get_settings()
    active_mode = settings.trading_mode if mode == "current" else mode
    if active_mode == settings.trading_mode and settings.trading_mode != "paper":
        try:
            await sync_exchange_trade_pnl(db, OrderManager())
        except Exception as exc:
            log_event(db, "warning", "sync", "Não foi possível atualizar performance.", {"error": str(exc)})

    base = db.query(Trade).filter(Trade.mode == active_mode) if mode != "all" else db.query(Trade)
    closed = base.filter(Trade.status == "closed").all()
    open_rows = base.filter(Trade.status == "open").all()
    wins = [trade for trade in closed if float(trade.pnl or 0) > 0]
    losses = [trade for trade in closed if float(trade.pnl or 0) < 0]
    breakeven = [trade for trade in closed if float(trade.pnl or 0) == 0]
    closed_pnl = sum(float(trade.pnl or 0) for trade in closed)
    open_pnl = sum(float(trade.pnl or 0) for trade in open_rows)
    total_closed = len(closed)
    win_rate = (len(wins) / total_closed * 100) if total_closed else 0
    profit_factor = None
    gross_loss = abs(sum(float(trade.pnl or 0) for trade in losses))
    if gross_loss > 0:
        profit_factor = sum(float(trade.pnl or 0) for trade in wins) / gross_loss
    return {
        "mode": active_mode,
        "closed_trades": total_closed,
        "open_trades": len(open_rows),
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": len(breakeven),
        "win_rate": round(win_rate, 2),
        "closed_pnl": round(closed_pnl, 4),
        "open_pnl": round(open_pnl, 4),
        "total_pnl": round(closed_pnl + open_pnl, 4),
        "average_closed_pnl": round(closed_pnl / total_closed, 4) if total_closed else 0,
        "best_trade": round(max((float(trade.pnl or 0) for trade in closed), default=0), 4),
        "worst_trade": round(min((float(trade.pnl or 0) for trade in closed), default=0), 4),
        "profit_factor": round(profit_factor, 3) if profit_factor is not None else None,
    }


@router.get("/orders")
def orders(limit: int = 80, mode: str = "current", db: Session = Depends(get_db)):
    query = db.query(Order)
    if mode != "all":
        trade_query = db.query(Trade.id)
        if mode == "current":
            trade_query = trade_query.filter(Trade.mode == get_settings().trading_mode)
        else:
            trade_query = trade_query.filter(Trade.mode == mode)
        query = query.filter((Order.trade_id.in_(trade_query)) | (Order.trade_id.is_(None)))
    return query.order_by(desc(Order.created_at)).limit(limit).all()


@router.get("/diagnostics/trading")
async def trading_diagnostics(db: Session = Depends(get_db)):
    settings = get_settings()
    risk_config = load_risk_config(db)
    last_errors = (
        db.query(LogEntry)
        .filter(LogEntry.level.in_(["error", "warning"]))
        .order_by(desc(LogEntry.created_at))
        .limit(10)
        .all()
    )
    return {
        "mode": settings.trading_mode,
        "exchange": settings.exchange_mode,
        "base_url": settings.base_url,
        "real_orders_enabled": settings.real_orders_enabled,
        "mainnet_enabled": settings.enable_mainnet,
        "risk_config": risk_config,
        "exchange_positions": await exchange_positions(),
        "open_local_trades": db.query(Trade).filter(Trade.status == "open", Trade.mode == settings.trading_mode).count(),
        "last_errors": last_errors,
    }


@router.post("/trades/close-all")
async def close_all_trades(db: Session = Depends(get_db)):
    settings = get_settings()
    manager = OrderManager()
    closed = []
    errors = []

    if settings.trading_mode == "paper":
        open_trades = db.query(Trade).filter(Trade.status == "open", Trade.mode == "paper").all()
        for trade in open_trades:
            try:
                closed_trade = manager.close_paper_trade(db, trade, trade.entry_price, "close_all")
                closed.append({"symbol": closed_trade.symbol, "side": closed_trade.side, "trade_id": closed_trade.id})
            except Exception as exc:
                errors.append({"symbol": trade.symbol, "side": trade.side, "error": str(exc)})
        log_event(db, "warning", "manual", "Fechamento geral solicitado no modo paper.", {"closed": len(closed), "errors": errors})
        return {"closed_count": len(closed), "closed": closed, "errors": errors}

    if not settings.binance_api_key or not settings.binance_api_secret:
        raise HTTPException(400, "API Binance não configurada.")

    await sync_exchange_trade_pnl(db, manager)
    positions = await manager.client.position_risk()
    open_positions = [row for row in positions if float(row.get("positionAmt", 0) or 0) != 0]
    open_trades = db.query(Trade).filter(Trade.status == "open", Trade.mode == settings.trading_mode).all()
    local_map = {}
    for trade in open_trades:
        local_map.setdefault((trade.symbol, trade.side), []).append(trade)

    for row in open_positions:
        amount = float(row.get("positionAmt", 0) or 0)
        symbol = row.get("symbol", "")
        side = row.get("positionSide") if row.get("positionSide") in {"LONG", "SHORT"} else ("LONG" if amount > 0 else "SHORT")
        exit_price = float(row.get("markPrice") or row.get("entryPrice") or 0)
        local_trades = local_map.get((symbol, side), [])
        try:
            close_side = "SELL" if amount > 0 else "BUY"
            payload = {"symbol": symbol, "side": close_side, "type": "MARKET", "quantity": abs(amount)}
            if row.get("positionSide") in {"LONG", "SHORT"}:
                payload["positionSide"] = row["positionSide"]
            else:
                payload["reduceOnly"] = "true"
            response = await manager.client.create_order(**payload)
            cancel_responses = {}
            try:
                cancel_responses["orders"] = await manager.client.cancel_open_orders(symbol)
            except Exception as exc:
                cancel_responses["orders_error"] = str(exc)
            try:
                cancel_responses["algo_orders"] = await manager.client.cancel_open_algo_orders(symbol)
            except Exception as exc:
                cancel_responses["algo_orders_error"] = str(exc)
            db.add(
                Order(
                    trade_id=local_trades[0].id if local_trades else None,
                    symbol=symbol,
                    side=close_side,
                    order_type="EXCHANGE_CLOSE_ALL",
                    status=response.get("status", "sent"),
                    price=exit_price,
                    quantity=abs(amount),
                    reduce_only=True,
                    raw_response={"response": response, "cancel": cancel_responses},
                )
            )
            for trade in local_trades:
                multiplier = 1 if trade.side == "LONG" else -1
                pnl = (exit_price - trade.entry_price) * trade.quantity * multiplier
                margin = max(trade.entry_price * trade.quantity / max(trade.leverage, 1), 1)
                trade.exit_price = exit_price
                trade.pnl = round(pnl, 4)
                trade.pnl_pct = round((pnl / margin) * 100, 4)
                trade.status = "closed"
                trade.closed_at = datetime.utcnow()
            db.commit()
            closed.append({"symbol": symbol, "side": side, "trade_id": local_trades[0].id if local_trades else None})
        except Exception as exc:
            errors.append({"symbol": symbol, "side": side, "error": str(exc)})

    log_event(db, "warning", "manual", "Fechamento geral de posições solicitado.", {"closed": len(closed), "errors": errors})
    if errors and not closed:
        raise HTTPException(500, {"message": "Nenhuma posição foi fechada.", "errors": errors})
    return {"closed_count": len(closed), "closed": closed, "errors": errors}


@router.post("/trades/{trade_id}/close")
async def close_trade(trade_id: int, db: Session = Depends(get_db)):
    trade = db.query(Trade).filter(Trade.id == trade_id).first()
    if not trade:
        raise HTTPException(404, "Trade não encontrado.")
    if trade.status != "open":
        raise HTTPException(400, "Trade já está fechado.")
    manager = OrderManager()
    if get_settings().trading_mode == "paper":
        return manager.close_paper_trade(db, trade, trade.entry_price, "manual")
    exit_price = trade.exit_price or trade.entry_price
    return await manager.close_exchange_trade(db, trade, exit_price, "manual")


@router.get("/logs")
def logs(limit: int = 100, db: Session = Depends(get_db)):
    return db.query(LogEntry).order_by(desc(LogEntry.created_at)).limit(limit).all()


@router.get("/config/risk")
def get_risk_config_route(db: Session = Depends(get_db)) -> RiskConfig:
    return RiskConfig(**load_risk_config(db))


@router.post("/config/risk")
def set_risk_config(payload: RiskConfig, db: Session = Depends(get_db)):
    saved = save_risk_config(db, payload.model_dump())
    log_event(db, "info", "config", "Configuração de risco recebida.", payload.model_dump())
    return {"saved": True, "config": saved}


@router.post("/backtests/run")
async def run_backtest(payload: BacktestRequest, db: Session = Depends(get_db)):
    results = await Backtester().run(payload.symbol, payload.timeframe, payload.limit, payload.initial_balance)
    db.add(Backtest(symbol=payload.symbol, timeframe=payload.timeframe, parameters=payload.model_dump(), results=results))
    db.commit()
    return results


@router.post("/risk/evaluate")
def evaluate_risk(symbol: str, side: str, entry_price: float, atr: float, score: float, db: Session = Depends(get_db)):
    risk_config = load_risk_config(db)
    return RiskManager().evaluate(db, symbol, side, entry_price, atr, runtime_state.balance, int(risk_config["leverage"]), score)
