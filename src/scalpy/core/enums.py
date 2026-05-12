from enum import StrEnum


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(StrEnum):
    PENDING = "pending"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class MarketPhase(StrEnum):
    PRE_MARKET = "pre_market"
    OPEN = "open"
    CLOSE = "close"
    AFTER_HOURS = "after_hours"
