from datetime import datetime
from sqlalchemy.orm import Session
from app.config import get_settings
from app.models.trading import Trade
from app.order_manager import OrderManager
from app.services.config_store import get_risk_config
from app.services.logger import log_event
from app.services.state import runtime_state


def _position_key(row: dict) -> tuple[str, str | None]:
    amount = float(row.get("positionAmt", 0) or 0)
    side = row.get("positionSide")
    if side and side != "BOTH":
        return row.get("symbol", ""), side
    return row.get("symbol", ""), "LONG" if amount > 0 else "SHORT"


def _trade_roi_pct(trade: Trade, pnl: float) -> float:
    margin = max(trade.entry_price * trade.quantity / max(trade.leverage, 1), 1)
    return round((pnl / margin) * 100, 4)


async def sync_exchange_trade_pnl(db: Session, order_manager: OrderManager | None = None) -> None:
    settings = get_settings()
    if settings.trading_mode == "paper" or not settings.binance_api_key or not settings.binance_api_secret:
        return
    manager = order_manager or OrderManager()
    positions = await manager.client.position_risk()
    position_map = {
        _position_key(row): row
        for row in positions
        if float(row.get("positionAmt", 0) or 0) != 0
    }
    open_trades = db.query(Trade).filter(Trade.status == "open", Trade.mode == settings.trading_mode).all()
    for trade in open_trades:
        row = position_map.get((trade.symbol, trade.side))
        if not row:
            trade.status = "closed"
            trade.closed_at = datetime.utcnow()
            runtime_state.trailing_peak_roi.pop(trade.id, None)
            log_event(db, "info", "sync", "Trade local marcado como fechado porque não existe posição aberta na Binance.", {"symbol": trade.symbol})
            continue
        pnl = float(row.get("unRealizedProfit", 0) or 0)
        mark_price = float(row.get("markPrice", 0) or 0)
        trade.pnl = round(pnl, 4)
        trade.pnl_pct = _trade_roi_pct(trade, pnl)
        if mark_price > 0:
            trade.exit_price = mark_price
    db.commit()


async def exchange_account_snapshot(order_manager: OrderManager | None = None) -> dict:
    settings = get_settings()
    manager = order_manager or OrderManager()
    account = await manager.client.account()
    positions = await manager.client.position_risk()
    usdt = next((asset for asset in account.get("assets", []) if asset.get("asset") == "USDT"), {})
    open_positions = [row for row in positions if float(row.get("positionAmt", 0) or 0) != 0]
    unrealized = sum(float(row.get("unRealizedProfit", 0) or 0) for row in open_positions)
    return {
        "connected": True,
        "mode": settings.trading_mode,
        "exchange": settings.exchange_mode,
        "asset": "USDT",
        "wallet_balance": float(usdt.get("walletBalance", 0) or 0),
        "available_balance": float(usdt.get("availableBalance", 0) or 0),
        "unrealized_pnl": round(unrealized, 4),
        "open_positions": len(open_positions),
    }


async def manage_exchange_exits(db: Session, order_manager: OrderManager) -> None:
    settings = get_settings()
    if settings.trading_mode == "paper":
        return
    config = get_risk_config(db)
    if not config.get("trailing_stop_enabled") and not config.get("break_even_enabled"):
        await sync_exchange_trade_pnl(db, order_manager)
        return

    await sync_exchange_trade_pnl(db, order_manager)
    open_trades = db.query(Trade).filter(Trade.status == "open", Trade.mode == settings.trading_mode).all()
    for trade in open_trades:
        current_roi = float(trade.pnl_pct or 0)
        peak_roi = max(float(runtime_state.trailing_peak_roi.get(trade.id, current_roi)), current_roi)
        runtime_state.trailing_peak_roi[trade.id] = peak_roi
        reason = None

        if config.get("break_even_enabled") and peak_roi >= 6 and current_roi <= 0.5:
            reason = "break_even"
        if config.get("trailing_stop_enabled") and peak_roi >= 10:
            giveback = max(3.0, peak_roi * 0.35)
            if current_roi <= peak_roi - giveback:
                reason = "trailing_stop"
        if config.get("trailing_stop_enabled") and peak_roi >= 18 and current_roi <= peak_roi - 5:
            reason = "profit_fade"

        if not reason:
            continue
        try:
            exit_price = float(trade.exit_price or trade.entry_price)
            await order_manager.close_exchange_trade(db, trade, exit_price, reason)
            runtime_state.trailing_peak_roi.pop(trade.id, None)
            log_event(
                db,
                "warning",
                "exit",
                "Posição fechada por gestão ativa.",
                {"symbol": trade.symbol, "reason": reason, "roi": current_roi, "peak_roi": peak_roi},
            )
        except Exception as exc:
            log_event(db, "error", "exit", "Falha ao fechar posição por gestão ativa.", {"symbol": trade.symbol, "error": str(exc)})
