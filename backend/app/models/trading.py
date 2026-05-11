from datetime import datetime
from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Trade(Base, TimestampMixin):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(30), index=True)
    side: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    entry_price: Mapped[float] = mapped_column(Float)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity: Mapped[float] = mapped_column(Float)
    leverage: Mapped[int] = mapped_column(Integer)
    stop_loss: Mapped[float] = mapped_column(Float)
    take_profit: Mapped[float] = mapped_column(Float)
    pnl: Mapped[float] = mapped_column(Float, default=0)
    pnl_pct: Mapped[float] = mapped_column(Float, default=0)
    mode: Mapped[str] = mapped_column(String(20), default="paper")
    signal_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Order(Base, TimestampMixin):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    symbol: Mapped[str] = mapped_column(String(30), index=True)
    side: Mapped[str] = mapped_column(String(10))
    order_type: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30), default="created")
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity: Mapped[float] = mapped_column(Float)
    reduce_only: Mapped[bool] = mapped_column(Boolean, default=False)
    exchange_order_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    slippage_pct: Mapped[float] = mapped_column(Float, default=0)
    raw_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Position(Base, TimestampMixin):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(30), index=True)
    side: Mapped[str] = mapped_column(String(10))
    quantity: Mapped[float] = mapped_column(Float)
    entry_price: Mapped[float] = mapped_column(Float)
    mark_price: Mapped[float] = mapped_column(Float)
    liquidation_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    leverage: Mapped[int] = mapped_column(Integer)
    margin_type: Mapped[str] = mapped_column(String(20), default="isolated")
    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0)
    is_open: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class Signal(Base, TimestampMixin):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(30), index=True)
    timeframe: Mapped[str] = mapped_column(String(10), default="15m")
    direction: Mapped[str] = mapped_column(String(10))
    score: Mapped[float] = mapped_column(Float)
    ml_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    price: Mapped[float] = mapped_column(Float)
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    features: Mapped[dict] = mapped_column(JSON, default=dict)
    accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    setup: Mapped[str | None] = mapped_column(String(50), nullable=True, default="none")


class Candle(Base, TimestampMixin):
    __tablename__ = "candles"
    __table_args__ = (UniqueConstraint("symbol", "timeframe", "open_time", name="uq_candle"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(30), index=True)
    timeframe: Mapped[str] = mapped_column(String(10), index=True)
    open_time: Mapped[datetime] = mapped_column(DateTime, index=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)


class Metric(Base, TimestampMixin):
    __tablename__ = "metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(30), index=True)
    timeframe: Mapped[str] = mapped_column(String(10), index=True)
    values: Mapped[dict] = mapped_column(JSON, default=dict)


class BotConfig(Base, TimestampMixin):
    __tablename__ = "configurations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)


class LogEntry(Base, TimestampMixin):
    __tablename__ = "logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    level: Mapped[str] = mapped_column(String(20), default="info", index=True)
    source: Mapped[str] = mapped_column(String(80), default="system")
    message: Mapped[str] = mapped_column(Text)
    context: Mapped[dict] = mapped_column(JSON, default=dict)


class Backtest(Base, TimestampMixin):
    __tablename__ = "backtests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(30), index=True)
    timeframe: Mapped[str] = mapped_column(String(10))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    results: Mapped[dict] = mapped_column(JSON, default=dict)


class RiskEvent(Base, TimestampMixin):
    """Eventos de risco: limites atingidos, bloqueios, alertas."""
    __tablename__ = "risk_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    reason: Mapped[str] = mapped_column(Text)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class ModelFeatures(Base, TimestampMixin):
    """Features de cada trade para treinamento do modelo AI."""
    __tablename__ = "model_features"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("trades.id"), nullable=True, index=True)
    signal_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("signals.id"), nullable=True, index=True)
    symbol: Mapped[str] = mapped_column(String(30), index=True)
    setup: Mapped[str | None] = mapped_column(String(50), nullable=True)
    features: Mapped[dict] = mapped_column(JSON, default=dict)
    outcome: Mapped[float | None] = mapped_column(Float, nullable=True)
    success: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class ModelPrediction(Base, TimestampMixin):
    """Predições do modelo AI por sinal."""
    __tablename__ = "model_predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    signal_id: Mapped[int] = mapped_column(Integer, ForeignKey("signals.id"), index=True)
    model_version: Mapped[str] = mapped_column(String(50), default="v1")
    probability: Mapped[float] = mapped_column(Float)
    features_used: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class DailyPerformance(Base, TimestampMixin):
    __tablename__ = "daily_performance"
    __table_args__ = (UniqueConstraint("day", name="uq_daily_performance_day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[Date] = mapped_column(Date, index=True)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0)
    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0)
    trades_count: Mapped[int] = mapped_column(Integer, default=0)
    wins: Mapped[int] = mapped_column(Integer, default=0)
    losses: Mapped[int] = mapped_column(Integer, default=0)
    max_drawdown: Mapped[float] = mapped_column(Float, default=0)
