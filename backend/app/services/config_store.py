from sqlalchemy.orm import Session
from app.config import get_settings
from app.models.trading import BotConfig


def default_risk_config() -> dict:
    """
    Retorna os valores padrão de risco do perfil scalping/swing:
      - Alavancagem: 10x (padrão), máximo 20x
      - Margem por operação: 5 a 10 USDT
      - Stop Loss: 1.5x ATR
      - TP1 (50%): 2.0x ATR → mover SL para breakeven
      - TP2 (50%): 3.5x ATR → trailing stop ativo
      - Risco por trade: 1% do saldo
      - Drawdown máximo diário: 5%
      - Score mínimo: 70
    """
    settings = get_settings()
    return {
        # ── Risco por trade ────────────────────────────────────────────────────
        "max_risk_per_trade_pct": settings.max_risk_per_trade_pct,  # % do saldo

        # ── Limites diários ────────────────────────────────────────────────────
        "max_daily_loss_pct": settings.max_daily_loss_pct,          # % — bot para se atingir
        "max_daily_profit_pct": settings.max_daily_profit_pct,      # % — bot para ao atingir
        "max_trades_per_day": settings.max_trades_per_day,

        # ── Posições ───────────────────────────────────────────────────────────
        "max_open_positions": settings.max_open_positions,

        # ── Alavancagem ────────────────────────────────────────────────────────
        "leverage": settings.default_leverage,                  # alavancagem fixa
        "auto_leverage_enabled": True,                          # ajustar por score/volatilidade
        "max_auto_leverage": settings.default_leverage,         # cap da alavancagem automática
        "autonomous_risk_enabled": True,                        # usar margem fixa (USDT) por trade

        # ── Margem por operação (USDT) ─────────────────────────────────────────
        "fixed_margin_usdt": settings.max_margin_usdt,         # margem padrão = 10 USDT
        "min_margin_usdt": settings.min_margin_usdt,           # 5 USDT mínimo
        "max_margin_usdt": settings.max_margin_usdt,           # 10 USDT máximo

        # ── Stop Loss e Take Profit (ATR) ──────────────────────────────────────
        "atr_stop_multiplier": settings.atr_stop_multiplier,   # SL = 1.5x ATR
        "atr_tp1_multiplier": settings.atr_tp1_multiplier,     # TP1 = 2.0x ATR (fechar 50%)
        "atr_tp2_multiplier": settings.atr_tp2_multiplier,     # TP2 = 3.5x ATR (fechar restante)
        "tp1_close_pct": settings.tp1_close_pct,               # 50% da posição no TP1
        "min_stop_loss_pct": 0.5,                              # SL mínimo: 0.5% do preço

        # ── Filtros de entrada ─────────────────────────────────────────────────
        "min_signal_score": settings.min_signal_score,         # score mínimo (0-100)
        "multi_timeframe_enabled": True,                       # confirmar sinal no 1h
        "volatility_filter_enabled": True,                     # filtrar mercados flat (ATR baixo)
        "regime_filter_enabled": True,                         # só operar em tendência (ADX >= 25)

        # ── Gestão de saída ────────────────────────────────────────────────────
        "trailing_stop_enabled": settings.trailing_stop_enabled,
        "break_even_enabled": settings.break_even_enabled,
        "ai_exit_enabled": True,                               # usar IA para saída antecipada

        # ── Tolerância a risco ─────────────────────────────────────────────────
        "risk_tolerance": "balanced",                          # conservative / balanced / aggressive
        "ai_exit_min_profit_roi": 4.0,                        # % mínimo de ROI para ativar saída IA
    }


def get_risk_config(db: Session) -> dict:
    """
    Retorna a configuração de risco ativa: padrão + overrides salvos no banco.
    Aplica clamps de segurança em todos os parâmetros críticos.
    """
    settings = get_settings()
    config = default_risk_config()

    saved = db.query(BotConfig).filter(BotConfig.key == "risk").first()
    if saved:
        config.update(saved.value or {})

    # ── Clamps de segurança ──────────────────────────────────────────────────
    config["max_open_positions"] = max(1, min(int(config["max_open_positions"]), 20))
    config["leverage"] = max(1, min(int(config["leverage"]), settings.max_leverage))
    config["max_auto_leverage"] = max(1, min(int(config.get("max_auto_leverage", settings.default_leverage)), settings.max_leverage))
    config["fixed_margin_usdt"] = max(1.0, min(float(config.get("fixed_margin_usdt", 10)), 500.0))
    config["min_margin_usdt"] = max(1.0, float(config.get("min_margin_usdt", settings.min_margin_usdt)))
    config["max_margin_usdt"] = max(
        config["min_margin_usdt"],
        min(float(config.get("max_margin_usdt", settings.max_margin_usdt)), 500.0),
    )
    config["min_stop_loss_pct"] = max(0.1, min(float(config.get("min_stop_loss_pct", 0.5)), 10.0))
    config["min_signal_score"] = max(50.0, min(float(config.get("min_signal_score", 70)), 100.0))
    config["atr_stop_multiplier"] = max(0.5, min(float(config.get("atr_stop_multiplier", 1.5)), 5.0))
    config["atr_tp1_multiplier"] = max(1.0, min(float(config.get("atr_tp1_multiplier", 2.0)), 10.0))
    config["atr_tp2_multiplier"] = max(
        config["atr_tp1_multiplier"],
        min(float(config.get("atr_tp2_multiplier", 3.5)), 15.0),
    )
    config["tp1_close_pct"] = max(0.1, min(float(config.get("tp1_close_pct", 0.5)), 0.9))
    config["max_daily_loss_pct"] = max(0.5, min(float(config.get("max_daily_loss_pct", 5.0)), 50.0))
    config["max_daily_profit_pct"] = max(1.0, min(float(config.get("max_daily_profit_pct", 10.0)), 100.0))
    config["max_trades_per_day"] = max(1, min(int(config.get("max_trades_per_day", 20)), 200))
    config["max_risk_per_trade_pct"] = max(0.1, min(float(config.get("max_risk_per_trade_pct", 1.0)), 5.0))

    if config.get("risk_tolerance") not in {"conservative", "balanced", "aggressive"}:
        config["risk_tolerance"] = "balanced"

    return config


def save_risk_config(db: Session, payload: dict) -> dict:
    """Persiste a configuração de risco no banco após aplicar clamps de segurança."""
    config = get_risk_config(db)
    config.update(payload)
    # Re-aplica clamps após o merge
    config = get_risk_config.__wrapped__(db) if hasattr(get_risk_config, "__wrapped__") else config
    # Aplica clamps manualmente após merge com payload
    settings = get_settings()
    config["max_open_positions"] = max(1, min(int(config.get("max_open_positions", 5)), 20))
    config["leverage"] = max(1, min(int(config.get("leverage", 10)), settings.max_leverage))
    config["max_auto_leverage"] = max(1, min(int(config.get("max_auto_leverage", 10)), settings.max_leverage))
    config["fixed_margin_usdt"] = max(1.0, min(float(config.get("fixed_margin_usdt", 10)), 500.0))
    config["min_stop_loss_pct"] = max(0.1, min(float(config.get("min_stop_loss_pct", 0.5)), 10.0))
    config["min_signal_score"] = max(50.0, min(float(config.get("min_signal_score", 70)), 100.0))
    config["atr_stop_multiplier"] = max(0.5, min(float(config.get("atr_stop_multiplier", 1.5)), 5.0))
    config["atr_tp1_multiplier"] = max(1.0, min(float(config.get("atr_tp1_multiplier", 2.0)), 10.0))
    config["atr_tp2_multiplier"] = max(
        config["atr_tp1_multiplier"],
        min(float(config.get("atr_tp2_multiplier", 3.5)), 15.0),
    )
    config["tp1_close_pct"] = max(0.1, min(float(config.get("tp1_close_pct", 0.5)), 0.9))
    config["max_daily_loss_pct"] = max(0.5, min(float(config.get("max_daily_loss_pct", 5.0)), 50.0))
    config["max_trades_per_day"] = max(1, min(int(config.get("max_trades_per_day", 20)), 200))
    config["max_risk_per_trade_pct"] = max(0.1, min(float(config.get("max_risk_per_trade_pct", 1.0)), 5.0))
    if config.get("risk_tolerance") not in {"conservative", "balanced", "aggressive"}:
        config["risk_tolerance"] = "balanced"

    row = db.query(BotConfig).filter(BotConfig.key == "risk").first()
    if not row:
        row = BotConfig(key="risk", value=config)
        db.add(row)
    else:
        row.value = config
    db.commit()
    return config
