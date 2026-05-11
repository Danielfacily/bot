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
        ModelFeatures,
        ModelPrediction,
        Order,
        Position,
        RiskEvent,
        Signal,
        Trade,
    )

    Base.metadata.create_all(bind=engine)

    # Adiciona colunas novas em tabelas existentes (idempotente)
    with engine.connect() as conn:
        migrations = [
            "ALTER TABLE signals ADD COLUMN IF NOT EXISTS setup VARCHAR(50) DEFAULT 'none'",
            "ALTER TABLE trades ADD COLUMN IF NOT EXISTS take_profit_1 FLOAT",
        ]
        for sql in migrations:
            try:
                conn.execute(__import__("sqlalchemy").text(sql))
            except Exception:
                pass
        conn.commit()
