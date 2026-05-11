"""Portfolio Engine — controla posições abertas, PnL e exposição."""
from dataclasses import dataclass
from sqlalchemy.orm import Session
from app.models.trading import Trade


@dataclass
class PortfolioSummary:
    open_positions: int
    total_exposure_usdt: float
    unrealized_pnl: float
    realized_pnl_today: float
    margin_used: float
    largest_position: str | None
    risk_pct_of_balance: float


class PortfolioEngine:
    def summary(self, db: Session, balance: float, mode: str = "paper") -> PortfolioSummary:
        open_trades = db.query(Trade).filter(Trade.status == "open", Trade.mode == mode).all()

        total_notional = sum(
            float(t.entry_price or 0) * float(t.quantity or 0)
            for t in open_trades
        )
        unrealized = sum(float(t.pnl or 0) for t in open_trades if t.pnl is not None)
        margin_used = sum(
            float(t.entry_price or 0) * float(t.quantity or 0) / max(int(t.leverage or 1), 1)
            for t in open_trades
        )

        largest = None
        if open_trades:
            largest_trade = max(
                open_trades, key=lambda t: float(t.entry_price or 0) * float(t.quantity or 0)
            )
            largest = largest_trade.symbol

        risk_pct = (margin_used / balance * 100) if balance > 0 else 0.0

        return PortfolioSummary(
            open_positions=len(open_trades),
            total_exposure_usdt=round(total_notional, 2),
            unrealized_pnl=round(unrealized, 4),
            realized_pnl_today=0.0,
            margin_used=round(margin_used, 2),
            largest_position=largest,
            risk_pct_of_balance=round(risk_pct, 2),
        )

    def check_max_exposure(self, summary: PortfolioSummary, balance: float, max_pct: float = 80.0) -> bool:
        return summary.risk_pct_of_balance <= max_pct
