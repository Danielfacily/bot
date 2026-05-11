from datetime import datetime
from pydantic import BaseModel, Field


class BotStatus(BaseModel):
    running: bool
    kill_switch: bool
    mode: str
    exchange: str
    market: str = "USDT-M Futures"
    futures_base_url: str
    mainnet_enabled: bool
    open_positions: int
    paper_open_positions: int = 0
    exchange_open_positions: int = 0
    max_open_positions: int
    daily_pnl: float
    balance: float


class AccountBalance(BaseModel):
    connected: bool
    mode: str
    exchange: str
    asset: str = "USDT"
    wallet_balance: float = 0
    available_balance: float = 0
    unrealized_pnl: float = 0
    message: str | None = None


class ExchangePosition(BaseModel):
    symbol: str
    side: str
    quantity: float
    entry_price: float
    mark_price: float
    unrealized_pnl: float
    leverage: int
    liquidation_price: float | None = None


class BotControl(BaseModel):
    running: bool | None = None
    kill_switch: bool | None = None


class RiskConfig(BaseModel):
    # Risco por trade e limites diários
    max_risk_per_trade_pct: float = Field(default=1.0, ge=0.05, le=5)
    max_daily_loss_pct: float = Field(default=5.0, ge=0.1, le=25)
    max_daily_profit_pct: float = Field(default=10.0, ge=0.1, le=100)
    max_trades_per_day: int = Field(default=20, ge=1, le=200)
    max_open_positions: int = Field(default=5, ge=1, le=20)

    # Alavancagem
    leverage: int = Field(default=10, ge=1, le=20)
    auto_leverage_enabled: bool = True
    max_auto_leverage: int = Field(default=10, ge=1, le=20)
    autonomous_risk_enabled: bool = True

    # Margem por operação (USDT)
    fixed_margin_usdt: float = Field(default=10.0, ge=1, le=500)
    min_margin_usdt: float = Field(default=5.0, ge=1, le=500)
    max_margin_usdt: float = Field(default=10.0, ge=1, le=500)

    # Stop Loss e Take Profit (ATR)
    min_stop_loss_pct: float = Field(default=0.5, ge=0.1, le=10)
    atr_stop_multiplier: float = Field(default=1.5, ge=0.5, le=5.0)
    atr_tp1_multiplier: float = Field(default=2.0, ge=1.0, le=10.0)
    atr_tp2_multiplier: float = Field(default=3.5, ge=1.0, le=15.0)
    tp1_close_pct: float = Field(default=0.5, ge=0.1, le=0.9)

    # Filtros e tolerância
    min_signal_score: float = Field(default=70.0, ge=50.0, le=100.0)
    risk_tolerance: str = "balanced"
    multi_timeframe_enabled: bool = True
    volatility_filter_enabled: bool = True
    regime_filter_enabled: bool = True

    # Gestão de saída
    trailing_stop_enabled: bool = True
    break_even_enabled: bool = True
    ai_exit_enabled: bool = True


class HotCoin(BaseModel):
    symbol: str
    price: float
    price_change_pct: float
    quote_volume: float
    relative_volume: float
    volatility_pct: float
    spread_pct: float
    score: float
    updated_at: datetime


class SignalOut(BaseModel):
    id: int
    symbol: str
    timeframe: str
    direction: str
    score: float
    ml_probability: float | None
    price: float
    reasons: list
    accepted: bool
    rejection_reason: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class TradeOut(BaseModel):
    id: int
    symbol: str
    side: str
    status: str
    entry_price: float
    exit_price: float | None
    quantity: float
    leverage: int
    stop_loss: float
    take_profit: float
    pnl: float
    pnl_pct: float
    mode: str
    created_at: datetime
    closed_at: datetime | None

    class Config:
        from_attributes = True


class BacktestRequest(BaseModel):
    symbol: str = "BTCUSDT"
    timeframe: str = "15m"
    limit: int = Field(default=500, ge=100, le=1500)
    initial_balance: float = Field(default=10_000, gt=0)


class BacktestResult(BaseModel):
    symbol: str
    timeframe: str
    win_rate: float
    drawdown: float
    pnl: float
    average_trade: float
    largest_loss: float
    largest_win: float
    trades_count: int
    by_asset: dict
    by_timeframe: dict
