from functools import lru_cache
from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Binance Futures USDT-M Trading Bot"
    environment: str = "local"
    database_url: str = Field(default="postgresql+psycopg://bot:bot@postgres:5432/trading_bot")
    redis_url: str = Field(default="redis://redis:6379/0")

    # Credenciais da exchange
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

    # ── ALAVANCAGEM ─────────────────────────────────────────────────────────────
    # Perfil padrão: scalping/swing curto com 10x a 20x de alavancagem.
    # Para alterar o limite máximo, defina MAX_LEVERAGE no .env (máx recomendado: 20).
    max_leverage: int = 20
    default_leverage: int = 10

    # ── POSIÇÕES E EXPOSIÇÃO ─────────────────────────────────────────────────────
    max_open_positions: int = 5          # máximo de posições simultâneas
    max_daily_loss_pct: float = 5.0      # % do saldo — bot para se atingir esse drawdown no dia
    max_daily_profit_pct: float = 10.0   # % do saldo — bot para ao atingir esse lucro no dia
    max_risk_per_trade_pct: float = 1.0  # risco máximo por trade: 1-2% do saldo total
    max_trades_per_day: int = 20         # número máximo de trades abertos por dia
    isolated_margin: bool = True

    # ── PROTEÇÕES ────────────────────────────────────────────────────────────────
    trailing_stop_enabled: bool = True
    break_even_enabled: bool = True
    dry_run_force: bool = True  # True = nunca envia ordens reais, mesmo em testnet

    # ── TIMEFRAMES ───────────────────────────────────────────────────────────────
    # Operações: 15m (primário) confirmadas no 1h
    primary_timeframe: str = "15m"
    confirmation_timeframe: str = "1h"

    # ── MARGEM POR OPERAÇÃO (USDT) ────────────────────────────────────────────────
    min_margin_usdt: float = 5.0    # margem mínima por trade
    max_margin_usdt: float = 10.0   # margem máxima por trade

    # ── PARÂMETROS DE SINAL ──────────────────────────────────────────────────────
    # Score de confiança mínimo (0-100) para abertura de posição
    min_signal_score: float = 70.0

    # ── GESTÃO DE RISCO — ATR ────────────────────────────────────────────────────
    # Stop Loss dinâmico: 1.5x ATR abaixo da entrada (LONG) ou acima (SHORT)
    atr_stop_multiplier: float = 1.5
    # TP1: fechar 50% da posição aqui e mover SL para breakeven
    atr_tp1_multiplier: float = 2.0
    # TP2: fechar o restante aqui (trailing stop ativo)
    atr_tp2_multiplier: float = 3.5
    # Percentual da posição fechado no TP1
    tp1_close_pct: float = 0.5

    # ── SCANNER E ESTRATÉGIA ─────────────────────────────────────────────────────
    scanner_interval_seconds: int = 20
    strategy_interval_seconds: int = 30
    quote_asset: str = "USDT"
    min_quote_volume: float = 20_000_000
    max_spread_pct: float = 0.12

    # Saldo inicial para modo paper (USDT)
    paper_initial_balance: float = 1_000.0

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("exchange_mode")
    @classmethod
    def validate_exchange_mode(cls, value: str) -> str:
        value = value.lower()
        if value not in {"testnet", "mainnet"}:
            raise ValueError("exchange_mode deve ser testnet ou mainnet")
        return value

    @field_validator("trading_mode")
    @classmethod
    def validate_trading_mode(cls, value: str) -> str:
        value = value.lower()
        if value not in {"paper", "testnet", "live"}:
            raise ValueError("trading_mode deve ser paper, testnet ou live")
        return value

    @field_validator("default_leverage")
    @classmethod
    def validate_default_leverage(cls, value: int) -> int:
        if value < 1:
            raise ValueError("default_leverage deve ser >= 1")
        return value

    @property
    def base_url(self) -> str:
        if self.exchange_mode == "mainnet":
            if not self.enable_mainnet:
                raise RuntimeError(
                    "Mainnet bloqueada. Defina ENABLE_MAINNET=true apenas após validação completa no Testnet."
                )
            return self.binance_mainnet_base_url
        return self.binance_testnet_base_url

    @property
    def real_orders_enabled(self) -> bool:
        return self.trading_mode in {"testnet", "live"} and not self.dry_run_force


@lru_cache
def get_settings() -> Settings:
    return Settings()
