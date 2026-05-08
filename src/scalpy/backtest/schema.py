from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase

from scalpy.config import settings


class Base(DeclarativeBase):
    pass


class Candle(Base):
    __tablename__ = "candles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(10), nullable=False)
    dt = Column(DateTime, nullable=False)
    open = Column(Numeric, nullable=False)
    high = Column(Numeric, nullable=False)
    low = Column(Numeric, nullable=False)
    close = Column(Numeric, nullable=False)
    volume = Column(BigInteger, nullable=False)

    __table_args__ = (
        Index("idx_candles_symbol_dt", "symbol", "dt", unique=True),
    )


def get_engine():
    url = settings.get("database_url")
    if not url:
        raise RuntimeError("database_url 설정이 필요합니다 (settings.toml)")
    return create_engine(url)


def init_db():
    engine = get_engine()
    Base.metadata.create_all(engine)
    return engine
