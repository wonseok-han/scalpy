import uuid

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TradeRow(Base):
    __tablename__ = "trades"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid.uuid4
    )
    symbol: Mapped[str] = mapped_column(sa.String(20))
    side: Mapped[str] = mapped_column(sa.String(4))
    price: Mapped[sa.Numeric] = mapped_column(sa.Numeric(15, 2))
    quantity: Mapped[int]
    strategy: Mapped[str] = mapped_column(sa.String(50))
    pnl: Mapped[sa.Numeric | None] = mapped_column(sa.Numeric(15, 2), nullable=True)
    executed_at: Mapped[sa.DateTime] = mapped_column(sa.DateTime(timezone=True))
    created_at: Mapped[sa.DateTime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )


class PositionRow(Base):
    __tablename__ = "positions"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid.uuid4
    )
    symbol: Mapped[str] = mapped_column(sa.String(20))
    side: Mapped[str] = mapped_column(sa.String(4))
    quantity: Mapped[int]
    avg_price: Mapped[sa.Numeric] = mapped_column(sa.Numeric(15, 2))
    strategy: Mapped[str] = mapped_column(sa.String(50))
    opened_at: Mapped[sa.DateTime] = mapped_column(sa.DateTime(timezone=True))
    closed_at: Mapped[sa.DateTime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    realized_pnl: Mapped[sa.Numeric] = mapped_column(
        sa.Numeric(15, 2), default=0
    )
    created_at: Mapped[sa.DateTime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    updated_at: Mapped[sa.DateTime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )


class StrategyResultRow(Base):
    __tablename__ = "strategy_results"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid.uuid4
    )
    strategy: Mapped[str] = mapped_column(sa.String(50))
    symbol: Mapped[str] = mapped_column(sa.String(20))
    total_trades: Mapped[int] = mapped_column(default=0)
    win_count: Mapped[int] = mapped_column(default=0)
    loss_count: Mapped[int] = mapped_column(default=0)
    total_pnl: Mapped[sa.Numeric] = mapped_column(sa.Numeric(15, 2), default=0)
    max_drawdown: Mapped[sa.Numeric] = mapped_column(sa.Numeric(15, 2), default=0)
    win_rate: Mapped[sa.Numeric] = mapped_column(sa.Numeric(5, 2), default=0)
    date: Mapped[sa.Date] = mapped_column(sa.Date)
    created_at: Mapped[sa.DateTime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )


sa.Index("idx_trades_symbol", TradeRow.symbol)
sa.Index("idx_trades_strategy", TradeRow.strategy)
sa.Index("idx_trades_executed_at", TradeRow.executed_at)
sa.Index("idx_positions_symbol", PositionRow.symbol)
sa.Index("idx_strategy_results_date", StrategyResultRow.date)
