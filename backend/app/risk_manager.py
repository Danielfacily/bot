from dataclasses import dataclass, field
from sqlalchemy.orm import Session
from app.config import get_settings
from app.models.trading import Trade
from app.services.config_store import get_risk_config


@dataclass
class RiskDecision:
    allowed: bool
    reason: str
    quantity: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0      # TP2 — fechar o restante (50%) da posição
    take_profit_1: float = 0.0    # TP1 — fechar os primeiros 50% e mover SL para breakeven
    leverage: int = 1
    risk_amount: float = 0.0
    expected_reward: float = 0.0
    reasons: list = field(default_factory=list)


class RiskManager:
    """
    Gerenciador de risco com as seguintes garantias:
      - Stop Loss dinâmico: 1.5x ATR (configurável)
      - Take Profit escalonado: TP1 (2x ATR) e TP2 (3.5x ATR)
      - Risco por operação: 1-2% do saldo (configurável)
      - Score mínimo: 70 (configurável)
      - Proteção contra liquidação
      - Verificação de limites diários (drawdown e quantidade de trades)
    """

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

        # Verificação de limites diários (drawdown e trades por dia)
        from app.services.state import runtime_state
        halted, halt_reason = runtime_state.is_daily_halted(
            max_loss_pct=float(config.get("max_daily_loss_pct", self.settings.max_daily_loss_pct)),
            max_trades=int(config.get("max_trades_per_day", self.settings.max_trades_per_day)),
        )
        if halted and not manual_override:
            return RiskDecision(False, halt_reason)

        # Alavancagem: autônoma ou fixa
        auto_enabled = config.get("auto_leverage_enabled", True)
        autonomous_enabled = config.get("autonomous_risk_enabled", True)
        fixed_leverage = min(int(config.get("leverage", leverage)), self.settings.max_leverage)
        effective_leverage = (
            self.recommend_leverage(config, score, entry_price, atr_value)
            if auto_enabled
            else fixed_leverage
        )

        mode = self.settings.trading_mode
        open_count = db.query(Trade).filter(Trade.status == "open", Trade.mode == mode).count()
        if open_count >= int(config["max_open_positions"]):
            return RiskDecision(False, "Limite de posições abertas atingido.")

        existing = db.query(Trade).filter(Trade.symbol == symbol, Trade.status == "open", Trade.mode == mode).first()
        if existing:
            return RiskDecision(False, "Já existe posição aberta no mesmo ativo.")

        # Score mínimo de confiança
        min_score = float(config.get("min_signal_score", self.settings.min_signal_score))
        if score < min_score and not manual_override:
            return RiskDecision(False, f"Score {score:.1f} abaixo do mínimo ({min_score:.0f}).")

        if atr_value <= 0:
            return RiskDecision(False, "ATR inválido — impossível calcular stop loss.")

        # Volatilidade extrema: evitar entradas com ATR relativo acima de 6%
        volatility_rel = (atr_value / entry_price) * 100 if entry_price else 99
        if volatility_rel > 6.0 and not manual_override:
            return RiskDecision(False, f"Volatilidade ATR relativa {volatility_rel:.1f}% acima do limite seguro (6%).")

        # ── CÁLCULO DAS DISTÂNCIAS DE SL/TP ─────────────────────────────────────
        stop_dist = self.stop_distance(config, entry_price, atr_value)
        tp1_dist = atr_value * float(config.get("atr_tp1_multiplier", self.settings.atr_tp1_multiplier))
        tp2_dist = atr_value * float(config.get("atr_tp2_multiplier", self.settings.atr_tp2_multiplier))

        # TP2 mínimo: 1.5x o stop (risco:retorno mínimo)
        tp2_dist = max(tp2_dist, stop_dist * 1.5)
        tp2_dist = min(tp2_dist, stop_dist * 5.0)  # evitar alvos irrealistas

        if tp2_dist / stop_dist < 1.5:
            return RiskDecision(False, "Risco/retorno do TP2 menor que 1:1.5 — trade não vale o risco.")

        # ── TAMANHO DA POSIÇÃO ───────────────────────────────────────────────────
        if autonomous_enabled:
            margin_amount = float(config.get("fixed_margin_usdt", self.settings.max_margin_usdt))
            margin_amount = max(
                float(config.get("min_margin_usdt", self.settings.min_margin_usdt)),
                min(margin_amount, float(config.get("max_margin_usdt", self.settings.max_margin_usdt))),
            )
            # Clamp pela disponibilidade de saldo: nunca usar mais de 20% do saldo em uma posição
            margin_amount = min(margin_amount, balance * 0.20)
            quantity = (margin_amount * effective_leverage) / entry_price
            risk_amount = stop_dist * quantity
        else:
            risk_amount = balance * float(config["max_risk_per_trade_pct"]) / 100
            quantity = risk_amount / stop_dist

        # Clamp pelo notional máximo
        notional = quantity * entry_price
        max_notional = balance * effective_leverage * 0.85
        if notional > max_notional:
            quantity = max_notional / entry_price

        if quantity <= 0:
            return RiskDecision(False, "Tamanho de posição calculado é inválido (quantidade <= 0).")

        # ── DIREÇÃO: SL, TP1, TP2 ───────────────────────────────────────────────
        if side == "LONG":
            stop_loss = entry_price - stop_dist
            take_profit_1 = entry_price + tp1_dist
            take_profit_2 = entry_price + tp2_dist
            # Proteção contra liquidação: SL nunca deve ficar abaixo do preço de liquidação
            liquidation_guard = entry_price * (1 - 0.80 / effective_leverage)
            if stop_loss <= liquidation_guard:
                return RiskDecision(
                    False,
                    "Stop loss muito próximo do preço de liquidação — alavancagem incompatível com o ATR atual.",
                    leverage=effective_leverage,
                )
        else:  # SHORT
            stop_loss = entry_price + stop_dist
            take_profit_1 = entry_price - tp1_dist
            take_profit_2 = entry_price - tp2_dist
            liquidation_guard = entry_price * (1 + 0.80 / effective_leverage)
            if stop_loss >= liquidation_guard:
                return RiskDecision(
                    False,
                    "Stop loss muito próximo do preço de liquidação — alavancagem incompatível com o ATR atual.",
                    leverage=effective_leverage,
                )

        reason = "Risco aprovado manualmente." if manual_override else "Risco aprovado."
        return RiskDecision(
            allowed=True,
            reason=reason,
            quantity=round(quantity, 6),
            stop_loss=round(stop_loss, 6),
            take_profit=round(take_profit_2, 6),     # TP2 é o take_profit principal
            take_profit_1=round(take_profit_1, 6),   # TP1: fechar 50% e breakeven
            leverage=effective_leverage,
            risk_amount=round(risk_amount, 4),
            expected_reward=round(tp2_dist * quantity, 4),
        )

    # ── ALAVANCAGEM RECOMENDADA ──────────────────────────────────────────────────

    def recommend_leverage(self, config: dict, score: float, entry_price: float, atr_value: float) -> int:
        max_auto = min(int(config.get("max_auto_leverage", self.settings.default_leverage)), self.settings.max_leverage)
        if config.get("autonomous_risk_enabled", True):
            return self.autonomous_leverage(config, score, entry_price, atr_value, max_auto)
        fixed = min(int(config.get("leverage", self.settings.default_leverage)), self.settings.max_leverage)
        if not config.get("auto_leverage_enabled", True):
            return fixed
        # Auto-leverage baseado em volatilidade
        volatility_pct = (atr_value / entry_price) * 100 if entry_price else 99
        if volatility_pct <= 0 or volatility_pct > 4.5:
            return max(1, min(5, max_auto))
        if volatility_pct > 3:
            cap = min(max_auto, 5)
        elif volatility_pct > 1.8:
            cap = min(max_auto, 10)
        elif volatility_pct > 1.0:
            cap = min(max_auto, 15)
        else:
            cap = max_auto
        if score >= 88:
            recommended = cap
        elif score >= 78:
            recommended = max(1, min(cap, 12))
        elif score >= 70:
            recommended = max(1, min(cap, 8))
        else:
            recommended = max(1, min(cap, 5))
        return max(1, recommended)

    def autonomous_leverage(self, config: dict, score: float, entry_price: float, atr_value: float, ceiling: int) -> int:
        volatility_pct = (atr_value / entry_price) * 100 if entry_price else 99
        tolerance = config.get("risk_tolerance", "balanced")
        if tolerance == "conservative":
            tiers = (0.35, 0.55, 0.70)
        elif tolerance == "aggressive":
            tiers = (0.55, 0.75, 1.00)
        else:  # balanced
            tiers = (0.45, 0.65, 0.85)

        if volatility_pct > 4.5:
            # Mercado muito volátil: alavancagem mínima
            leverage = max(1, round(ceiling * tiers[0]))
        elif score >= 88 and volatility_pct <= 1.8:
            leverage = max(1, round(ceiling * tiers[2]))
        elif score >= 75 and volatility_pct <= 3.0:
            leverage = max(1, round(ceiling * tiers[1]))
        else:
            leverage = max(1, round(ceiling * tiers[0]))
        return max(1, min(leverage, ceiling))

    # ── DISTÂNCIA DO STOP LOSS ───────────────────────────────────────────────────

    def stop_distance(self, config: dict, entry_price: float, atr_value: float) -> float:
        """
        Stop Loss dinâmico baseado em ATR.
        Padrão: 1.5x ATR — nunca menor que 0.5% do preço de entrada.
        """
        atr_mult = float(config.get("atr_stop_multiplier", get_settings().atr_stop_multiplier))
        min_stop_pct = float(config.get("min_stop_loss_pct", 0.5)) / 100
        atr_stop = atr_value * atr_mult
        fixed_stop = entry_price * min_stop_pct
        # Garante pelo menos 0.2% de distância para evitar stop imediato
        return max(atr_stop, fixed_stop, entry_price * 0.002)
