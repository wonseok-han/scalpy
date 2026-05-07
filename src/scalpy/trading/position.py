from decimal import Decimal

import structlog

from scalpy.core.enums import Side
from scalpy.core.models import Order, Position

logger = structlog.get_logger()


class PositionManager:
    def __init__(self) -> None:
        self._positions: dict[str, Position] = {}

    def get(self, symbol: str) -> Position | None:
        return self._positions.get(symbol)

    def all(self) -> list[Position]:
        return list(self._positions.values())

    def update_on_fill(self, order: Order) -> Position | None:
        if order.side == Side.BUY:
            return self._open_or_add(order)
        return self._close_or_reduce(order)

    def update_price(self, symbol: str, price: Decimal) -> None:
        pos = self._positions.get(symbol)
        if pos is None:
            return
        pos.current_price = price
        if pos.side == Side.BUY:
            pos.unrealized_pnl = (price - pos.avg_price) * pos.quantity
        else:
            pos.unrealized_pnl = (pos.avg_price - price) * pos.quantity

    def _open_or_add(self, order: Order) -> Position:
        existing = self._positions.get(order.symbol)
        if existing is None:
            pos = Position(
                symbol=order.symbol,
                side=Side.BUY,
                quantity=order.quantity,
                avg_price=order.price,
                current_price=order.price,
                strategy=order.strategy,
            )
            self._positions[order.symbol] = pos
            logger.info("position.opened", symbol=order.symbol, qty=order.quantity)
            return pos

        total_qty = existing.quantity + order.quantity
        total_cost = existing.avg_price * existing.quantity + order.price * order.quantity
        existing.avg_price = total_cost / total_qty
        existing.quantity = total_qty
        logger.info("position.added", symbol=order.symbol, total_qty=total_qty)
        return existing

    def _close_or_reduce(self, order: Order) -> Position | None:
        existing = self._positions.get(order.symbol)
        if existing is None:
            return None

        realized = (order.price - existing.avg_price) * order.quantity
        existing.realized_pnl += realized

        if order.quantity >= existing.quantity:
            del self._positions[order.symbol]
            logger.info(
                "position.closed",
                symbol=order.symbol,
                pnl=str(realized),
            )
            return None

        existing.quantity -= order.quantity
        logger.info(
            "position.reduced",
            symbol=order.symbol,
            remaining=existing.quantity,
        )
        return existing
