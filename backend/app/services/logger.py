from sqlalchemy.orm import Session
from app.models.trading import LogEntry


SENSITIVE_KEYS = {"api_key", "api_secret", "secret", "signature", "x-mbx-apikey"}


def sanitize_context(context: dict | None) -> dict:
    if not context:
        return {}
    clean = {}
    for key, value in context.items():
        if key.lower() in SENSITIVE_KEYS:
            clean[key] = "***"
        else:
            clean[key] = value
    return clean


def log_event(db: Session, level: str, source: str, message: str, context: dict | None = None) -> None:
    entry = LogEntry(level=level, source=source, message=message, context=sanitize_context(context))
    db.add(entry)
    db.commit()
