from enum import Enum


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(str, Enum):
    PENDING = "pending"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class MarketPhase(str, Enum):
    PRE_MARKET = "pre_market"
    OPEN = "open"
    CLOSE = "close"
    AFTER_HOURS = "after_hours"
