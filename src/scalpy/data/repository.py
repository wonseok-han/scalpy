from datetime import datetime
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from scalpy.core.enums import Side
from scalpy.core.models import TradeRecord
from scalpy.data.schema import Base, TradeRow


class TradeRepository:
    def __init__(self, database_url: str) -> None:
        self._engine = create_engine(database_url)

    def create_tables(self) -> None:
        Base.metadata.create_all(self._engine)

    def save_trade(self, trade: TradeRecord) -> None:
        with Session(self._engine) as session:
            row = TradeRow(
                id=trade.id,
                symbol=trade.symbol,
                side=trade.side.value,
                price=trade.price,
                quantity=trade.quantity,
                strategy=trade.strategy,
                pnl=trade.pnl,
                executed_at=trade.executed_at,
            )
            session.add(row)
            session.commit()

    def get_trades(
        self,
        symbol: str | None = None,
        strategy: str | None = None,
        limit: int = 100,
    ) -> list[TradeRecord]:
        with Session(self._engine) as session:
            stmt = select(TradeRow).order_by(TradeRow.executed_at.desc()).limit(limit)
            if symbol:
                stmt = stmt.where(TradeRow.symbol == symbol)
            if strategy:
                stmt = stmt.where(TradeRow.strategy == strategy)
            rows = session.scalars(stmt).all()
            return [
                TradeRecord(
                    id=str(r.id),
                    symbol=r.symbol,
                    side=Side(r.side),
                    price=Decimal(str(r.price)),
                    quantity=r.quantity,
                    strategy=r.strategy,
                    pnl=Decimal(str(r.pnl)) if r.pnl is not None else Decimal("0"),
                    executed_at=datetime.fromisoformat(str(r.executed_at)),
                )
                for r in rows
            ]
