from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from app.models.trading import (
        Backtest,
        BotConfig,
        Candle,
        DailyPerformance,
        LogEntry,
        Metric,
        Order,
        Position,
        Signal,
        Trade,
    )

    Base.metadata.create_all(bind=engine)
