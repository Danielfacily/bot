from sqlalchemy.orm import Session
from app.config import get_settings
from app.models.trading import BotConfig


def default_risk_config() -> dict:
    settings = get_settings()
    return {
        "max_risk_per_trade_pct": settings.max_risk_per_trade_pct,
        "max_daily_loss_pct": settings.max_daily_loss_pct,
        "max_daily_profit_pct": settings.max_daily_profit_pct,
        "max_open_positions": settings.max_open_positions,
        "leverage": settings.default_leverage,
        "auto_leverage_enabled": True,
        "max_auto_leverage": min(10, settings.max_leverage),
        "autonomous_risk_enabled": True,
        "fixed_margin_usdt": 10,
        "min_stop_loss_pct": 1.0,
        "risk_tolerance": "balanced",
        "trailing_stop_enabled": settings.trailing_stop_enabled,
        "break_even_enabled": settings.break_even_enabled,
    }


def get_risk_config(db: Session) -> dict:
    settings = get_settings()
    config = default_risk_config()
    saved = db.query(BotConfig).filter(BotConfig.key == "risk").first()
    if saved:
        config.update(saved.value or {})
    config["max_open_positions"] = min(int(config["max_open_positions"]), 30)
    config["leverage"] = min(int(config["leverage"]), settings.max_leverage)
    config["max_auto_leverage"] = min(int(config.get("max_auto_leverage", 10)), settings.max_leverage)
    config["fixed_margin_usdt"] = max(1, min(float(config.get("fixed_margin_usdt", 10)), 500))
    config["min_stop_loss_pct"] = max(0.1, min(float(config.get("min_stop_loss_pct", 1)), 10))
    if config.get("risk_tolerance") not in {"conservative", "balanced", "aggressive"}:
        config["risk_tolerance"] = "balanced"
    return config


def save_risk_config(db: Session, payload: dict) -> dict:
    settings = get_settings()
    config = get_risk_config(db)
    config.update(payload)
    config["max_open_positions"] = min(int(config["max_open_positions"]), 30)
    config["leverage"] = min(int(config["leverage"]), settings.max_leverage)
    config["max_auto_leverage"] = min(int(config.get("max_auto_leverage", 10)), settings.max_leverage)
    config["fixed_margin_usdt"] = max(1, min(float(config.get("fixed_margin_usdt", 10)), 500))
    config["min_stop_loss_pct"] = max(0.1, min(float(config.get("min_stop_loss_pct", 1)), 10))
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
