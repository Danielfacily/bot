"""Execution Engine — execução de ordens (paper e Binance Futures)."""
from datetime import datetime
from sqlalchemy.orm import Session
from app.binance_client import BinanceFuturesClient
from app.config import get_settings
from app.models.trading import Order, Trade
from app.engines.risk_engine import RiskDecision


class ExecutionEngine:
    def __init__(self, client: BinanceFuturesClient | None = None):
        self.settings = get_settings()
        self.client = client or BinanceFuturesClient(self.settings)

    async def open_position(
        self,
        db: Session,
        symbol: str,
        side: str,
        entry_price: float,
        leverage: int,
        risk: RiskDecision,
        signal_id: int | None,
    ) -> Trade:
        if self.settings.trading_mode == "paper" or not self.settings.real_orders_enabled:
            return self._paper_open(db, symbol, side, entry_price, leverage, risk, signal_id)
        await self.client.set_margin_type(symbol, "ISOLATED")
        leverage = await self._set_best_leverage(symbol, leverage)
        risk.leverage = leverage
        order_side = "BUY" if side == "LONG" else "SELL"
        close_side = "SELL" if side == "LONG" else "BUY"
        position_side = await self._position_side(side)
        entry_payload = {"symbol": symbol, "side": order_side, "type": "MARKET"}
        protection_base = {"symbol": symbol, "side": close_side, "workingType": "MARK_PRICE", "priceProtect": "true"}
        emergency_payload = {"symbol": symbol, "side": close_side, "type": "MARKET"}
        emergency_extra = {"reduceOnly": "true"}
        if position_side:
            entry_payload["positionSide"] = position_side
            protection_base["positionSide"] = position_side
            emergency_payload["positionSide"] = position_side
            emergency_extra = {}
        normalized_quantity = float(await self.client.quantity_for_min_notional(symbol, entry_price, risk.quantity, market=True))
        risk.quantity = normalized_quantity
        response = await self.client.create_order(**entry_payload, quantity=normalized_quantity)
        trade = self._record_trade(db, symbol, side, entry_price, leverage, risk, signal_id, mode=self.settings.trading_mode)
        db.add(
            Order(
                trade_id=trade.id,
                symbol=symbol,
                side=order_side,
                order_type="MARKET",
                status=response.get("status", "sent"),
                price=entry_price,
                quantity=risk.quantity,
                raw_response=response,
            )
        )
        try:
            stop_response = await self.client.create_algo_order(
                **protection_base,
                type="STOP_MARKET",
                stopPrice=risk.stop_loss,
                closePosition="true",
            )
            take_response = await self.client.create_algo_order(
                **protection_base,
                type="TAKE_PROFIT_MARKET",
                stopPrice=risk.take_profit,
                closePosition="true",
            )
        except Exception as exc:
            try:
                close_response = await self.client.create_order(
                    **emergency_payload,
                    quantity=normalized_quantity,
                    **emergency_extra,
                )
                db.add(
                    Order(
                        trade_id=trade.id,
                        symbol=symbol,
                        side=close_side,
                        order_type="EMERGENCY_CLOSE",
                        status=close_response.get("status", "sent"),
                        quantity=normalized_quantity,
                        reduce_only=True,
                        raw_response=close_response,
                    )
                )
                trade.status = "closed"
            except Exception as close_exc:
                db.add(
                    Order(
                        trade_id=trade.id,
                        symbol=symbol,
                        side=close_side,
                        order_type="EMERGENCY_CLOSE_FAILED",
                        status="error",
                        quantity=normalized_quantity,
                        reduce_only=True,
                        error=str(close_exc),
                    )
                )
            db.add(
                Order(
                    trade_id=trade.id,
                    symbol=symbol,
                    side=close_side,
                    order_type="PROTECTION_FAILED",
                    status="error",
                    quantity=normalized_quantity,
                    reduce_only=True,
                    error=str(exc),
                )
            )
            db.commit()
            raise
        db.add(
            Order(
                trade_id=trade.id,
                symbol=symbol,
                side=close_side,
                order_type="STOP_MARKET",
                status=stop_response.get("algoStatus") or stop_response.get("status", "sent"),
                price=risk.stop_loss,
                quantity=risk.quantity,
                reduce_only=True,
                exchange_order_id=str(stop_response.get("algoId") or stop_response.get("orderId", "")),
                raw_response=stop_response,
            )
        )
        db.add(
            Order(
                trade_id=trade.id,
                symbol=symbol,
                side=close_side,
                order_type="TAKE_PROFIT_MARKET",
                status=take_response.get("algoStatus") or take_response.get("status", "sent"),
                price=risk.take_profit,
                quantity=risk.quantity,
                reduce_only=True,
                exchange_order_id=str(take_response.get("algoId") or take_response.get("orderId", "")),
                raw_response=take_response,
            )
        )
        db.commit()
        return trade

    async def _position_side(self, side: str) -> str | None:
        try:
            mode = await self.client.position_mode()
        except Exception:
            return None
        if not mode.get("dualSidePosition"):
            return None
        return "LONG" if side == "LONG" else "SHORT"

    async def _set_best_leverage(self, symbol: str, requested: int) -> int:
        candidates = []
        for value in [requested, 20, 15, 10, 5, 3, 1]:
            if value not in candidates and value <= requested:
                candidates.append(value)
        last_error = None
        for value in candidates:
            try:
                await self.client.set_leverage(symbol, value)
                return value
            except Exception as exc:
                last_error = exc
        raise RuntimeError(f"Unable to set leverage for {symbol}: {last_error}")

    def _paper_open(self, db: Session, symbol: str, side: str, entry_price: float, leverage: int, risk: RiskDecision, signal_id: int | None) -> Trade:
        trade = self._record_trade(db, symbol, side, entry_price, leverage, risk, signal_id, "paper")
        db.add(
            Order(
                trade_id=trade.id,
                symbol=symbol,
                side="BUY" if side == "LONG" else "SELL",
                order_type="PAPER_MARKET",
                status="filled",
                price=entry_price,
                quantity=risk.quantity,
            )
        )
        db.add(
            Order(
                trade_id=trade.id,
                symbol=symbol,
                side="SELL" if side == "LONG" else "BUY",
                order_type="PAPER_STOP_MARKET",
                status="armed",
                price=risk.stop_loss,
                quantity=risk.quantity,
                reduce_only=True,
            )
        )
        db.add(
            Order(
                trade_id=trade.id,
                symbol=symbol,
                side="SELL" if side == "LONG" else "BUY",
                order_type="PAPER_TAKE_PROFIT",
                status="armed",
                price=risk.take_profit,
                quantity=risk.quantity,
                reduce_only=True,
            )
        )
        db.commit()
        db.refresh(trade)
        return trade

    def _record_trade(
        self,
        db: Session,
        symbol: str,
        side: str,
        entry_price: float,
        leverage: int,
        risk: RiskDecision,
        signal_id: int | None,
        mode: str,
    ) -> Trade:
        trade = Trade(
            symbol=symbol,
            side=side,
            status="open",
            entry_price=entry_price,
            quantity=risk.quantity,
            leverage=leverage,
            stop_loss=risk.stop_loss,
            take_profit=risk.take_profit,
            mode=mode,
            signal_id=signal_id,
        )
        db.add(trade)
        db.commit()
        db.refresh(trade)
        return trade

    def close_paper_trade(self, db: Session, trade: Trade, exit_price: float, reason: str = "manual") -> Trade:
        multiplier = 1 if trade.side == "LONG" else -1
        pnl = (exit_price - trade.entry_price) * trade.quantity * multiplier
        trade.exit_price = exit_price
        trade.pnl = round(pnl, 4)
        trade.pnl_pct = round((pnl / max(trade.entry_price * trade.quantity / trade.leverage, 1)) * 100, 4)
        trade.status = "closed"
        trade.closed_at = datetime.utcnow()
        db.add(
            Order(
                trade_id=trade.id,
                symbol=trade.symbol,
                side="SELL" if trade.side == "LONG" else "BUY",
                order_type="PAPER_CLOSE",
                status="filled",
                price=exit_price,
                quantity=trade.quantity,
                reduce_only=True,
                raw_response={"reason": reason},
            )
        )
        db.commit()
        db.refresh(trade)
        return trade

    async def close_exchange_trade(self, db: Session, trade: Trade, exit_price: float, reason: str = "manual") -> Trade:
        if self.settings.trading_mode == "paper" or not self.settings.real_orders_enabled:
            return self.close_paper_trade(db, trade, exit_price, reason)
        close_side = "SELL" if trade.side == "LONG" else "BUY"
        position_side = await self._position_side(trade.side)
        payload = {
            "symbol": trade.symbol,
            "side": close_side,
            "type": "MARKET",
            "quantity": trade.quantity,
        }
        if position_side:
            payload["positionSide"] = position_side
        else:
            payload["reduceOnly"] = "true"
        response = await self.client.create_order(**payload)
        cancel_responses = {}
        try:
            cancel_responses["orders"] = await self.client.cancel_open_orders(trade.symbol)
        except Exception as exc:
            cancel_responses["orders_error"] = str(exc)
        try:
            cancel_responses["algo_orders"] = await self.client.cancel_open_algo_orders(trade.symbol)
        except Exception as exc:
            cancel_responses["algo_orders_error"] = str(exc)
        multiplier = 1 if trade.side == "LONG" else -1
        pnl = (exit_price - trade.entry_price) * trade.quantity * multiplier
        margin = max(trade.entry_price * trade.quantity / max(trade.leverage, 1), 1)
        trade.exit_price = exit_price
        trade.pnl = round(pnl, 4)
        trade.pnl_pct = round((pnl / margin) * 100, 4)
        trade.status = "closed"
        trade.closed_at = datetime.utcnow()
        db.add(
            Order(
                trade_id=trade.id,
                symbol=trade.symbol,
                side=close_side,
                order_type="EXCHANGE_CLOSE",
                status=response.get("status", "sent"),
                price=exit_price,
                quantity=trade.quantity,
                reduce_only=True,
                raw_response={"reason": reason, "response": response, "cancel": cancel_responses},
            )
        )
        db.commit()
        db.refresh(trade)
        return trade


# Backward compatibility
OrderManager = ExecutionEngine
