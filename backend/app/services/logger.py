import logging
import sys
from datetime import date
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.models.trading import LogEntry, Trade


# ── Configuração do logger de terminal ──────────────────────────────────────────
_logger = logging.getLogger("trading_bot")
if not _logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    _handler.setFormatter(_formatter)
    _logger.addHandler(_handler)
    _logger.setLevel(logging.DEBUG)

SENSITIVE_KEYS = {"api_key", "api_secret", "secret", "signature", "x-mbx-apikey"}

_LEVEL_MAP = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}


def sanitize_context(context: dict | None) -> dict:
    if not context:
        return {}
    clean = {}
    for key, value in context.items():
        clean[key] = "***" if key.lower() in SENSITIVE_KEYS else value
    return clean


def log_event(db: Session, level: str, source: str, message: str, context: dict | None = None) -> None:
    """
    Registra um evento no banco de dados E imprime no terminal.
    Use para eventos que precisam ser persistidos e visíveis em tempo real.
    """
    clean = sanitize_context(context)
    entry = LogEntry(level=level, source=source, message=message, context=clean)
    db.add(entry)
    db.commit()
    _log_terminal(level, source, message, clean)


def log_alert(level: str, source: str, message: str, context: dict | None = None) -> None:
    """
    Log apenas no terminal (sem DB). Use para alertas rápidos sem sessão DB disponível,
    ou para evitar commits desnecessários em loops críticos.
    """
    _log_terminal(level, source, message, sanitize_context(context))


def _log_terminal(level: str, source: str, message: str, context: dict) -> None:
    log_level = _LEVEL_MAP.get(level.lower(), logging.INFO)
    suffix = f" | {context}" if context else ""
    _logger.log(log_level, "[%s] %s%s", source.upper(), message, suffix)


def print_daily_summary(db: Session) -> None:
    """
    Imprime no terminal o sumário de performance do dia atual (UTC).
    Chamado uma vez por dia pelo strategy_loop.
    """
    from app.services.state import runtime_state

    today = date.today()
    closed_today = (
        db.query(Trade)
        .filter(Trade.status == "closed", func.date(Trade.closed_at) == today)
        .all()
    )
    open_count = db.query(Trade).filter(Trade.status == "open").count()
    wins = [t for t in closed_today if float(t.pnl or 0) > 0]
    losses = [t for t in closed_today if float(t.pnl or 0) < 0]
    total_pnl = sum(float(t.pnl or 0) for t in closed_today)
    win_rate = (len(wins) / len(closed_today) * 100) if closed_today else 0.0
    gross_profit = sum(float(t.pnl or 0) for t in wins)
    gross_loss = abs(sum(float(t.pnl or 0) for t in losses))
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else None

    sep = "─" * 58
    _logger.info(sep)
    _logger.info("  SUMÁRIO DIÁRIO — %s", today.strftime("%d/%m/%Y"))
    _logger.info(sep)
    _logger.info("  Saldo atual     : %.2f USDT", runtime_state.balance)
    _logger.info("  PnL do dia      : %+.4f USDT  (%.2f%%)", total_pnl, runtime_state.daily_profit_pct)
    _logger.info("  Drawdown do dia : %.2f%%", runtime_state.daily_drawdown_pct)
    _logger.info("  Trades fechados : %d  |  Abertos: %d", len(closed_today), open_count)
    _logger.info("  Vitórias: %d  |  Derrotas: %d  |  Win Rate: %.1f%%", len(wins), len(losses), win_rate)
    if profit_factor is not None:
        _logger.info("  Profit Factor   : %.2f", profit_factor)
    if runtime_state.daily_halt:
        _logger.warning("  ⚠  Bot em PAUSA — limite diário atingido.")
    _logger.info(sep)
