from app.binance_client import BinanceFuturesClient
from app.indicators import enrich_indicators


class Backtester:
    def __init__(self, client: BinanceFuturesClient | None = None):
        self.client = client or BinanceFuturesClient()

    async def run(self, symbol: str, timeframe: str, limit: int, initial_balance: float) -> dict:
        df = await self.client.klines(symbol, timeframe, limit)
        data = enrich_indicators(df).dropna().reset_index(drop=True)
        balance = initial_balance
        equity_peak = initial_balance
        drawdown = 0.0
        trades = []
        open_trade = None
        for _, row in data.iterrows():
            if open_trade:
                if open_trade["side"] == "LONG":
                    hit_stop = row["low"] <= open_trade["stop"]
                    hit_take = row["high"] >= open_trade["take"]
                    exit_price = open_trade["stop"] if hit_stop else open_trade["take"] if hit_take else None
                    pnl = (exit_price - open_trade["entry"]) * open_trade["qty"] if exit_price else None
                else:
                    hit_stop = row["high"] >= open_trade["stop"]
                    hit_take = row["low"] <= open_trade["take"]
                    exit_price = open_trade["stop"] if hit_stop else open_trade["take"] if hit_take else None
                    pnl = (open_trade["entry"] - exit_price) * open_trade["qty"] if exit_price else None
                if pnl is not None:
                    balance += pnl
                    trades.append({**open_trade, "exit": exit_price, "pnl": pnl})
                    open_trade = None
                    equity_peak = max(equity_peak, balance)
                    drawdown = min(drawdown, (balance - equity_peak) / equity_peak * 100)
                continue
            long_ok = row["ema_9"] > row["ema_21"] and row["close"] > row["vwap"] and row["relative_volume"] > 1.2 and row["rsi"] < 72
            short_ok = row["ema_9"] < row["ema_21"] and row["close"] < row["vwap"] and row["relative_volume"] > 1.2 and row["rsi"] > 30
            if long_ok or short_ok:
                side = "LONG" if long_ok else "SHORT"
                risk_amount = balance * 0.005
                stop_distance = max(row["atr"] * 1.4, row["close"] * 0.0025)
                qty = risk_amount / stop_distance
                open_trade = {
                    "side": side,
                    "entry": float(row["close"]),
                    "qty": float(qty),
                    "stop": float(row["close"] - stop_distance if side == "LONG" else row["close"] + stop_distance),
                    "take": float(row["close"] + stop_distance * 1.8 if side == "LONG" else row["close"] - stop_distance * 1.8),
                }
        pnls = [trade["pnl"] for trade in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        total = sum(pnls)
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "win_rate": round((len(wins) / len(trades) * 100) if trades else 0, 2),
            "drawdown": round(abs(drawdown), 2),
            "pnl": round(total, 2),
            "average_trade": round(total / len(trades), 2) if trades else 0,
            "largest_loss": round(min(losses), 2) if losses else 0,
            "largest_win": round(max(wins), 2) if wins else 0,
            "trades_count": len(trades),
            "by_asset": {symbol: round(total, 2)},
            "by_timeframe": {timeframe: round(total, 2)},
        }
