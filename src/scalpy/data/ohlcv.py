from datetime import datetime, timedelta, timezone

import logging

import structlog
import yfinance as yf
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

logging.getLogger("yfinance").setLevel(logging.CRITICAL)

from scalpy.data.schema import Base, OhlcvRow

logger = structlog.get_logger()

_KST = timezone(timedelta(hours=9))

_INTERVAL_PERIOD = {
    "1m": "5d",
    "5m": "1mo",
    "1d": "1y",
}


def _to_yahoo_ticker(symbol: str) -> str:
    return symbol + ".KS"


def _to_yahoo_ticker_kq(symbol: str) -> str:
    return symbol + ".KQ"


class OhlcvRepository:
    def __init__(self, database_url: str) -> None:
        self._engine = create_engine(database_url)

    def create_tables(self) -> None:
        Base.metadata.create_all(self._engine)

    def recreate_table(self) -> None:
        OhlcvRow.__table__.drop(self._engine, checkfirst=True)
        OhlcvRow.__table__.create(self._engine, checkfirst=True)

    def fetch_and_store(
        self,
        symbol: str,
        interval: str = "1d",
        period: str | None = None,
    ) -> int:
        if not symbol or not symbol[0].isdigit():
            return 0

        if not period:
            period = _INTERVAL_PERIOD.get(interval, "1y")

        ticker = _to_yahoo_ticker(symbol)
        df = yf.download(ticker, period=period, interval=interval, progress=False)
        if df.empty:
            ticker = _to_yahoo_ticker_kq(symbol)
            df = yf.download(ticker, period=period, interval=interval, progress=False)
        if df.empty:
            logger.warning("ohlcv.no_data", symbol=symbol, interval=interval)
            return 0

        if hasattr(df.columns, "levels") and len(df.columns.levels) > 1:
            df.columns = df.columns.droplevel("Ticker")

        count = 0
        with Session(self._engine) as session:
            existing = {
                r[0]
                for r in session.execute(
                    select(OhlcvRow.dt).where(
                        OhlcvRow.symbol == symbol,
                        OhlcvRow.interval == interval,
                    )
                ).all()
            }

            for dt_idx, row in df.iterrows():
                dt = dt_idx.to_pydatetime()
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=_KST)
                if dt in existing:
                    continue
                session.add(
                    OhlcvRow(
                        symbol=symbol,
                        interval=interval,
                        dt=dt,
                        open=int(row["Open"]),
                        high=int(row["High"]),
                        low=int(row["Low"]),
                        close=int(row["Close"]),
                        volume=int(row["Volume"]),
                    )
                )
                count += 1

            if count:
                session.commit()
                logger.info("ohlcv.stored", symbol=symbol, interval=interval, rows=count)
        return count

    def get_candles(
        self,
        symbol: str,
        interval: str = "1d",
        limit: int = 60,
    ) -> list[dict]:
        with Session(self._engine) as session:
            rows = session.scalars(
                select(OhlcvRow)
                .where(OhlcvRow.symbol == symbol, OhlcvRow.interval == interval)
                .order_by(OhlcvRow.dt.desc())
                .limit(limit)
            ).all()
            rows = list(reversed(rows))
            return [
                {
                    "dt": r.dt.isoformat(),
                    "open": r.open,
                    "high": r.high,
                    "low": r.low,
                    "close": r.close,
                    "volume": r.volume,
                }
                for r in rows
            ]

    def get_latest_dt(self, symbol: str, interval: str = "1d") -> datetime | None:
        with Session(self._engine) as session:
            return session.execute(
                select(OhlcvRow.dt)
                .where(OhlcvRow.symbol == symbol, OhlcvRow.interval == interval)
                .order_by(OhlcvRow.dt.desc())
                .limit(1)
            ).scalar()

    def bulk_fetch(
        self,
        symbols: list[str],
        interval: str = "1d",
        period: str | None = None,
    ) -> int:
        total = 0
        for sym in symbols:
            total += self.fetch_and_store(sym, interval=interval, period=period)
        return total
