from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from scalpy.core.enums import OrderStatus, OrderType, Side


@dataclass
class Signal:
    symbol: str
    side: Side
    strategy: str
    price: Decimal
    quantity: int
    confidence: float
    timestamp: datetime


@dataclass
class Order:
    symbol: str
    side: Side
    order_type: OrderType
    price: Decimal
    quantity: int
    strategy: str
    id: str = field(default_factory=lambda: str(uuid4()))
    status: OrderStatus = OrderStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    filled_at: datetime | None = None
    reject_reason: str = ""


@dataclass
class Position:
    symbol: str
    side: Side
    quantity: int
    avg_price: Decimal
    current_price: Decimal
    strategy: str
    opened_at: datetime = field(default_factory=datetime.now)
    unrealized_pnl: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    peak_price: Decimal = Decimal("0")


@dataclass
class TradeRecord:
    symbol: str
    side: Side
    price: Decimal
    quantity: int
    strategy: str
    pnl: Decimal
    executed_at: datetime
    id: str = field(default_factory=lambda: str(uuid4()))
