from sqlalchemy.orm import Session
from app.models.trading import Position, Trade


class PositionManager:
    def sync_from_open_trades(self, db: Session) -> list[Position]:
        open_trades = db.query(Trade).filter(Trade.status == "open").all()
        positions = []
        for trade in open_trades:
            position = db.query(Position).filter(Position.symbol == trade.symbol, Position.is_open.is_(True)).first()
            if not position:
                position = Position(
                    symbol=trade.symbol,
                    side=trade.side,
                    quantity=trade.quantity,
                    entry_price=trade.entry_price,
                    mark_price=trade.entry_price,
                    leverage=trade.leverage,
                    liquidation_price=None,
                    margin_type="isolated",
                    unrealized_pnl=0,
                    is_open=True,
                )
                db.add(position)
            positions.append(position)
        db.commit()
        return positions
