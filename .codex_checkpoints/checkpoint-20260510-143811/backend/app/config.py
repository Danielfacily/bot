from functools import lru_cache
from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Binance Futures USDT-M Trading Bot"
    environment: str = "local"
    database_url: str = Field(default="postgresql+psycopg://bot:bot@postgres:5432/trading_bot")
    redis_url: str = Field(default="redis://redis:6379/0")

    binance_api_key: str = ""
    binance_api_secret: str = ""
    binance_recv_window: int = Field(default=60000, validation_alias=AliasChoices("BINANCE_RECV_WINDOW", "RECV_WINDOW"))
    binance_testnet_base_url: str = Field(
        default="https://demo-fapi.binance.com",
        validation_alias=AliasChoices("BINANCE_TESTNET_BASE_URL", "BINANCE_FUTURES_REST_URL"),
    )
    binance_mainnet_base_url: str = "https://fapi.binance.com"
    binance_ws_url: str = Field(
        default="wss://fstream.binancefuture.com",
        validation_alias=AliasChoices("BINANCE_WS_URL", "BINANCE_FUTURES_WS_URL"),
    )
    enable_mainnet: bool = False
    trading_mode: str = "paper"
    exchange_mode: str = "testnet"

    max_leverage: int = 125
    default_leverage: int = 3
    max_open_positions: int = 30
    max_daily_loss_pct: float = 3.0
    max_daily_profit_pct: float = 6.0
    max_risk_per_trade_pct: float = 0.5
    max_trades_per_day: int = 50
    isolated_margin: bool = True
    trailing_stop_enabled: bool = False
    break_even_enabled: bool = True
    dry_run_force: bool = True

    scanner_interval_seconds: int = 20
    strategy_interval_seconds: int = 30
    quote_asset: str = "USDT"
    min_quote_volume: float = 20_000_000
    max_spread_pct: float = 0.12
    paper_initial_balance: float = 10_000

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("exchange_mode")
    @classmethod
    def validate_exchange_mode(cls, value: str) -> str:
        value = value.lower()
        if value not in {"testnet", "mainnet"}:
            raise ValueError("exchange_mode must be testnet or mainnet")
        return value

    @field_validator("trading_mode")
    @classmethod
    def validate_trading_mode(cls, value: str) -> str:
        value = value.lower()
        if value not in {"paper", "testnet", "live"}:
            raise ValueError("trading_mode must be paper, testnet or live")
        return value

    @property
    def base_url(self) -> str:
        if self.exchange_mode == "mainnet":
            if not self.enable_mainnet:
                raise RuntimeError("Mainnet is blocked. Set ENABLE_MAINNET=true only after Testnet validation.")
            return self.binance_mainnet_base_url
        return self.binance_testnet_base_url

    @property
    def real_orders_enabled(self) -> bool:
        return self.trading_mode in {"testnet", "live"} and not self.dry_run_force


@lru_cache
def get_settings() -> Settings:
    return Settings()
