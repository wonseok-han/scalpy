from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Any

import structlog

from scalpy.broker.base import BaseBroker
from scalpy.core.enums import OrderStatus, Side
from scalpy.core.models import Order, Position

logger = structlog.get_logger()


_COMMISSION_RATE = Decimal("0.00015")
_SELL_TAX_RATE = Decimal("0.0018")


class MockBroker(BaseBroker):
    """Mock broker for testing and paper trading."""

    def __init__(self, initial_balance: Decimal = Decimal("500000")) -> None:
        self._balance = initial_balance
        self._initial_balance = initial_balance
        self._positions: dict[str, Position] = {}
        self._connected = False
        self._daily_pnl = Decimal("0")
        self._total_fees = Decimal("0")

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
        order.filled_at = datetime.now()
        commission = int(cost * _COMMISSION_RATE)
        if order.side == Side.BUY:
            self._balance -= cost + commission
            self._total_fees += commission
            self._positions[order.symbol] = Position(
                symbol=order.symbol,
                side=Side.BUY,
                quantity=order.quantity,
                avg_price=order.price,
                current_price=order.price,
                strategy=order.strategy,
            )
        else:
            tax = int(cost * _SELL_TAX_RATE)
            fees = commission + tax
            self._total_fees += fees
            pos = self._positions.get(order.symbol)
            if pos:
                realized = (order.price - pos.avg_price) * order.quantity - fees
                self._daily_pnl += realized
            self._balance += cost - fees
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

    async def get_trade_history(self) -> list[dict[str, Any]]:
        return []

    async def get_top_volume_stocks(self, count: int = 30) -> list[dict[str, Any]]:
        return [
            {"symbol": "005930", "name": "삼성전자", "volume": 15_000_000, "price": Decimal("71500"), "change_rate": 2.8, "volume_turnover": 1.5},
            {"symbol": "000660", "name": "SK하이닉스", "volume": 8_000_000, "price": Decimal("183000"), "change_rate": -2.7, "volume_turnover": 1.2},
            {"symbol": "035720", "name": "카카오", "volume": 5_000_000, "price": Decimal("54000"), "change_rate": 5.6, "volume_turnover": 2.1},
            {"symbol": "035420", "name": "NAVER", "volume": 3_000_000, "price": Decimal("208000"), "change_rate": 2.4, "volume_turnover": 0.8},
            {"symbol": "051910", "name": "LG화학", "volume": 2_000_000, "price": Decimal("377000"), "change_rate": 2.6, "volume_turnover": 0.6},
            {"symbol": "006400", "name": "삼성SDI", "volume": 1_500_000, "price": Decimal("417000"), "change_rate": 1.1, "volume_turnover": 0.4},
            {"symbol": "068270", "name": "셀트리온", "volume": 1_200_000, "price": Decimal("174000"), "change_rate": 1.7, "volume_turnover": 0.3},
        ][:count]

    async def subscribe_market_data(
        self, symbols: list[str], callback: Callable[..., Any]
    ) -> None:
        logger.info("mock_broker.subscribed", symbols=symbols)
