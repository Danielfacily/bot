from dataclasses import dataclass
from sqlalchemy.orm import Session
from app.config import get_settings
from app.models.trading import Trade
from app.services.config_store import get_risk_config


@dataclass
class RiskDecision:
    allowed: bool
    reason: str
    quantity: float = 0
    stop_loss: float = 0
    take_profit: float = 0
    leverage: int = 1
    risk_amount: float = 0
    expected_reward: float = 0


class RiskManager:
    def __init__(self):
        self.settings = get_settings()

    def evaluate(
        self,
        db: Session,
        symbol: str,
        side: str,
        entry_price: float,
        atr_value: float,
        balance: float,
        leverage: int,
        score: float,
        target_move_pct: float | None = None,
        manual_override: bool = False,
    ) -> RiskDecision:
        config = get_risk_config(db)
        autonomous_enabled = config.get("autonomous_risk_enabled", True)
        auto_enabled = config.get("auto_leverage_enabled", True)
        fixed_leverage = min(int(config.get("leverage", leverage)), self.settings.max_leverage)
        leverage = self.recommend_leverage(config, score, entry_price, atr_value) if auto_enabled else fixed_leverage
        mode = self.settings.trading_mode
        open_count = db.query(Trade).filter(Trade.status == "open", Trade.mode == mode).count()
        if open_count >= int(config["max_open_positions"]):
            return RiskDecision(False, "Limite de posições abertas atingido.")
        existing = db.query(Trade).filter(Trade.symbol == symbol, Trade.status == "open", Trade.mode == mode).first()
        if existing:
            return RiskDecision(False, "Já existe posição aberta no mesmo ativo.")
        if score < 65 and not manual_override:
            return RiskDecision(False, "Score abaixo do mínimo operacional.")
        if atr_value <= 0:
            return RiskDecision(False, "ATR inválido para cálculo de stop.")

        stop_distance = self.stop_distance(config, entry_price, atr_value)
        projected_take_distance = entry_price * ((target_move_pct or 0) / 100)
        take_distance = max(projected_take_distance, stop_distance * 1.5)
        take_distance = min(take_distance, stop_distance * 4)
        if take_distance / stop_distance < 1.5:
            return RiskDecision(False, "Risco/retorno menor que 1:1.5.")
        if autonomous_enabled:
            margin_amount = min(float(config.get("fixed_margin_usdt", 10)), balance * 0.20)
            quantity = (margin_amount * leverage) / entry_price
            risk_amount = stop_distance * quantity
        else:
            risk_amount = balance * float(config["max_risk_per_trade_pct"]) / 100
            quantity = risk_amount / stop_distance
        notional = quantity * entry_price
        max_notional = balance * leverage * 0.85
        if notional > max_notional:
            quantity = max_notional / entry_price
        if quantity <= 0:
            return RiskDecision(False, "Tamanho de posição calculado é inválido.")

        if side == "LONG":
            stop_loss = entry_price - stop_distance
            take_profit = entry_price + take_distance
            liquidation_guard = entry_price * (1 - 0.80 / leverage)
            if stop_loss <= liquidation_guard:
                return RiskDecision(False, "Stop fica próximo demais da liquidação.", leverage=leverage)
        else:
            stop_loss = entry_price + stop_distance
            take_profit = entry_price - take_distance
            liquidation_guard = entry_price * (1 + 0.80 / leverage)
            if stop_loss >= liquidation_guard:
                return RiskDecision(False, "Stop fica próximo demais da liquidação.", leverage=leverage)

        return RiskDecision(
            True,
            "Risco aprovado por aceite manual." if manual_override else "Risco aprovado.",
            round(quantity, 6),
            round(stop_loss, 6),
            round(take_profit, 6),
            leverage=leverage,
            risk_amount=round(risk_amount, 4),
            expected_reward=round(take_distance * quantity, 4),
        )

    def recommend_leverage(self, config: dict, score: float, entry_price: float, atr_value: float) -> int:
        max_auto = min(int(config.get("max_auto_leverage", 10)), self.settings.max_leverage)
        if config.get("autonomous_risk_enabled", True):
            return self.autonomous_leverage(config, score, entry_price, atr_value, max_auto)
        fixed = min(int(config.get("leverage", 1)), self.settings.max_leverage)
        if not config.get("auto_leverage_enabled", True):
            return fixed
        volatility_pct = (atr_value / entry_price) * 100 if entry_price else 99
        if volatility_pct <= 0 or volatility_pct > 4.5:
            return 1
        if volatility_pct > 3:
            cap = min(max_auto, 3)
        elif volatility_pct > 1.8:
            cap = min(max_auto, 5)
        elif volatility_pct > 1.0:
            cap = min(max_auto, 8)
        else:
            cap = max_auto
        if score >= 88:
            recommended = cap
        elif score >= 78:
            recommended = max(1, min(cap, 7))
        elif score >= 68:
            recommended = max(1, min(cap, 4))
        else:
            recommended = 1
        return max(1, recommended)

    def autonomous_leverage(self, config: dict, score: float, entry_price: float, atr_value: float, ceiling: int) -> int:
        volatility_pct = (atr_value / entry_price) * 100 if entry_price else 99
        tolerance = config.get("risk_tolerance", "balanced")
        if tolerance == "conservative":
            tiers = (0.35, 0.55, 0.75)
        elif tolerance == "aggressive":
            tiers = (0.60, 0.80, 1.00)
        else:
            tiers = (0.45, 0.65, 0.85)

        if volatility_pct > 4.5:
            leverage = max(1, round(ceiling * tiers[0]))
        elif score >= 88 and volatility_pct <= 1.8:
            leverage = max(1, round(ceiling * tiers[2]))
        elif score >= 75 and volatility_pct <= 3.0:
            leverage = max(1, round(ceiling * tiers[1]))
        else:
            leverage = max(1, round(ceiling * tiers[0]))
        return max(1, min(leverage, ceiling))

    def stop_distance(self, config: dict, entry_price: float, atr_value: float) -> float:
        min_stop_pct = float(config.get("min_stop_loss_pct", 1.0)) / 100
        fixed_stop = entry_price * min_stop_pct
        atr_stop = atr_value * 1.1
        return max(fixed_stop, atr_stop, entry_price * 0.0025)
