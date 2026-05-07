from collections.abc import Callable
from decimal import Decimal
from typing import Any

import structlog

from scalpy.broker.base import BaseBroker
from scalpy.core.enums import OrderStatus, Side
from scalpy.core.models import Order, Position

logger = structlog.get_logger()


class MockBroker(BaseBroker):
    """Mock broker for testing and paper trading."""

    def __init__(self, initial_balance: Decimal = Decimal("10000000")) -> None:
        self._balance = initial_balance
        self._positions: dict[str, Position] = {}
        self._connected = False

    async def connect(self) -> None:
        self._connected = True
        logger.info("mock_broker.connected")

    async def disconnect(self) -> None:
        self._connected = False
        logger.info("mock_broker.disconnected")

    async def place_order(self, order: Order) -> Order:
        cost = order.price * order.quantity
        if order.side == Side.BUY and cost > self._balance:
            order.status = OrderStatus.REJECTED
            logger.warning("mock_broker.order_rejected", reason="insufficient_balance")
            return order

        order.status = OrderStatus.FILLED
        if order.side == Side.BUY:
            self._balance -= cost
            self._positions[order.symbol] = Position(
                symbol=order.symbol,
                side=Side.BUY,
                quantity=order.quantity,
                avg_price=order.price,
                current_price=order.price,
                strategy=order.strategy,
            )
        else:
            self._balance += cost
            self._positions.pop(order.symbol, None)

        logger.info(
            "mock_broker.order_filled",
            symbol=order.symbol,
            side=order.side.value,
            price=str(order.price),
            qty=order.quantity,
        )
        return order

    async def cancel_order(self, order_id: str) -> bool:
        logger.info("mock_broker.order_cancelled", order_id=order_id)
        return True

    async def get_positions(self) -> list[Position]:
        return list(self._positions.values())

    async def get_balance(self) -> Decimal:
        return self._balance

    async def subscribe_market_data(
        self, symbols: list[str], callback: Callable[..., Any]
    ) -> None:
        logger.info("mock_broker.subscribed", symbols=symbols)
