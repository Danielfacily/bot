from dataclasses import dataclass, field
from datetime import datetime
from threading import Lock


@dataclass
class RuntimeState:
    """
    Estado global do bot em memória.

    Campos de controle:
      running        — bot está processando sinais e abrindo posições
      kill_switch    — para imediatamente toda atividade (sobrepõe running)
      hot_coins      — lista de moedas quentes do scanner (atualizada periodicamente)
      balance        — saldo disponível atual (USDT)

    Rastreamento diário (reiniciado a meia-noite UTC):
      daily_pnl         — PnL realizado acumulado no dia (USDT)
      daily_trades      — número de trades abertos no dia
      daily_halt        — True quando um limite diário foi atingido
      balance_day_start — saldo no início do dia (base para cálculo de drawdown)
      _current_day      — data atual no formato YYYY-MM-DD (controle interno)
    """

    running: bool = False
    kill_switch: bool = False
    hot_coins: list[dict] = field(default_factory=list)
    balance: float = 10_000.0
    balance_day_start: float = 10_000.0
    last_scan_at: datetime | None = None
    trailing_peak_roi: dict[int, float] = field(default_factory=dict)
    lock: Lock = field(default_factory=Lock)

    # Rastreamento diário
    daily_pnl: float = 0.0
    daily_trades: int = 0
    daily_halt: bool = False
    _current_day: str = ""

    # Controle de sumário diário (evita imprimir múltiplas vezes)
    _daily_summary_printed: bool = False

    def update_hot_coins(self, coins: list[dict]) -> None:
        with self.lock:
            self.hot_coins = coins
            self.last_scan_at = datetime.utcnow()

    def check_new_day(self) -> bool:
        """
        Verifica se virou o dia (UTC) e reinicia os contadores diários.
        Deve ser chamado no início de cada ciclo do strategy_loop.
        Retorna True se o dia mudou.
        """
        today = datetime.utcnow().strftime("%Y-%m-%d")
        if today != self._current_day:
            with self.lock:
                self._current_day = today
                self.daily_pnl = 0.0
                self.daily_trades = 0
                self.daily_halt = False
                self.balance_day_start = self.balance
                self._daily_summary_printed = False
            return True
        return False

    def record_trade_opened(self) -> None:
        """Registra a abertura de um novo trade no contador diário."""
        with self.lock:
            self.daily_trades += 1

    def record_trade_closed(self, pnl: float) -> None:
        """
        Registra o fechamento de um trade:
          - Atualiza o PnL diário
          - Atualiza o saldo disponível
        """
        with self.lock:
            self.daily_pnl += pnl
            self.balance = max(0.0, self.balance + pnl)

    def is_daily_halted(self, max_loss_pct: float, max_trades: int) -> tuple[bool, str]:
        """
        Verifica se o bot deve parar de abrir novas posições por ter atingido
        algum limite diário.

        Verifica:
          1. Halt já ativo (de verificação anterior)
          2. Número máximo de trades por dia
          3. Drawdown diário máximo (% do saldo inicial do dia)

        Retorna: (halt: bool, motivo: str)
        """
        if self.daily_halt:
            return True, "Bot em pausa diária — limite já atingido anteriormente."

        if self.daily_trades >= max_trades:
            with self.lock:
                self.daily_halt = True
            return True, f"Limite diário de {max_trades} trades atingido — bot pausado até meia-noite UTC."

        if self.balance_day_start > 0 and self.daily_pnl < 0:
            drawdown_pct = (-self.daily_pnl / self.balance_day_start) * 100
            if drawdown_pct >= max_loss_pct:
                with self.lock:
                    self.daily_halt = True
                return (
                    True,
                    f"Drawdown diário de {drawdown_pct:.2f}% atingiu o limite de {max_loss_pct:.1f}% — "
                    f"bot pausado até meia-noite UTC.",
                )

        return False, ""

    @property
    def daily_drawdown_pct(self) -> float:
        """Drawdown do dia em % (sempre positivo quando há perda)."""
        if self.balance_day_start <= 0:
            return 0.0
        return max(0.0, (-self.daily_pnl / self.balance_day_start) * 100)

    @property
    def daily_profit_pct(self) -> float:
        """Lucro do dia em % (positivo quando lucrativo)."""
        if self.balance_day_start <= 0:
            return 0.0
        return (self.daily_pnl / self.balance_day_start) * 100


runtime_state = RuntimeState()
