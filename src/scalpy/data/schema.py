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
    order_no: Mapped[str] = mapped_column(sa.String(30))
    order_date: Mapped[str] = mapped_column(sa.String(8))
    symbol: Mapped[str] = mapped_column(sa.String(20))
    name: Mapped[str] = mapped_column(sa.String(100), default="")
    side: Mapped[str] = mapped_column(sa.String(4))
    ord_qty: Mapped[int] = mapped_column(default=0)
    ord_price: Mapped[int] = mapped_column(default=0)
    ord_time: Mapped[str] = mapped_column(sa.String(10), default="")
    tot_ccld_qty: Mapped[int] = mapped_column(default=0)
    avg_price: Mapped[int] = mapped_column(default=0)
    tot_ccld_amt: Mapped[int] = mapped_column(default=0)
    rmn_qty: Mapped[int] = mapped_column(default=0)
    orgn_order_no: Mapped[str] = mapped_column(sa.String(30), default="")
    ord_dvsn_cd: Mapped[str] = mapped_column(sa.String(4), default="")
    cncl_yn: Mapped[str] = mapped_column(sa.String(1), default="")
    fee: Mapped[int] = mapped_column(default=0)
    pnl: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[sa.DateTime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    updated_at: Mapped[sa.DateTime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )

    __table_args__ = (
        sa.UniqueConstraint("order_no", "order_date", name="uq_trades_order_no_date"),
    )


class PositionRow(Base):
    __tablename__ = "positions"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid.uuid4
    )
    symbol: Mapped[str] = mapped_column(sa.String(20))
    side: Mapped[str] = mapped_column(sa.String(4))
    quantity: Mapped[int]
    avg_price: Mapped[float] = mapped_column(sa.Numeric(15, 2))
    strategy: Mapped[str] = mapped_column(sa.String(50))
    opened_at: Mapped[sa.DateTime] = mapped_column(sa.DateTime(timezone=True))
    closed_at: Mapped[sa.DateTime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    realized_pnl: Mapped[float] = mapped_column(
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
    total_pnl: Mapped[float] = mapped_column(sa.Numeric(15, 2), default=0)
    max_drawdown: Mapped[float] = mapped_column(sa.Numeric(15, 2), default=0)
    win_rate: Mapped[float] = mapped_column(sa.Numeric(5, 2), default=0)
    date: Mapped[sa.Date] = mapped_column(sa.Date)
    created_at: Mapped[sa.DateTime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )


sa.Index("idx_trades_symbol", TradeRow.symbol)
sa.Index("idx_trades_order_date", TradeRow.order_date)
sa.Index("idx_trades_side", TradeRow.side)
sa.Index("idx_positions_symbol", PositionRow.symbol)
sa.Index("idx_strategy_results_date", StrategyResultRow.date)
