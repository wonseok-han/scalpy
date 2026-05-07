from collections import deque

import structlog

from scalpy.broker.base import BaseBroker
from scalpy.core.enums import OrderStatus, OrderType
from scalpy.core.models import Order, Signal

logger = structlog.get_logger()


class OrderManager:
    def __init__(self, broker: BaseBroker) -> None:
        self._broker = broker
        self._pending: deque[Order] = deque()
        self._history: list[Order] = []

    def signal_to_order(self, signal: Signal, quantity: int) -> Order:
        return Order(
            symbol=signal.symbol,
            side=signal.side,
            order_type=OrderType.MARKET,
            price=signal.price,
            quantity=quantity,
            strategy=signal.strategy,
        )

    async def submit(self, order: Order) -> Order:
        self._pending.append(order)
        logger.info(
            "order.submitted",
            id=order.id,
            symbol=order.symbol,
            side=order.side.value,
        )
        result = await self._broker.place_order(order)
        self._pending.popleft()
        self._history.append(result)

        if result.status == OrderStatus.FILLED:
            logger.info("order.filled", id=result.id)
        else:
            logger.warning("order.not_filled", id=result.id, status=result.status.value)

        return result

    def get_pending(self) -> list[Order]:
        return list(self._pending)

    def get_history(self) -> list[Order]:
        return list(self._history)

    def has_pending_for(self, symbol: str) -> bool:
        return any(o.symbol == symbol for o in self._pending)
