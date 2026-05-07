from decimal import Decimal

import structlog

from scalpy.core.models import Order, Position

logger = structlog.get_logger()


class RiskManager:
    def __init__(
        self,
        stop_loss_ratio: float = 0.02,
        take_profit_ratio: float = 0.03,
        max_position_size: int = 100,
        max_open_positions: int = 3,
    ) -> None:
        self.stop_loss_ratio = Decimal(str(stop_loss_ratio))
        self.take_profit_ratio = Decimal(str(take_profit_ratio))
        self.max_position_size = max_position_size
        self.max_open_positions = max_open_positions

    def check_stop_loss(self, position: Position) -> bool:
        if position.quantity == 0:
            return False
        loss_ratio = (position.avg_price - position.current_price) / position.avg_price
        triggered = loss_ratio >= self.stop_loss_ratio
        if triggered:
            logger.warning(
                "risk.stop_loss_triggered",
                symbol=position.symbol,
                loss_ratio=str(loss_ratio),
            )
        return triggered

    def check_take_profit(self, position: Position) -> bool:
        if position.quantity == 0:
            return False
        gain_ratio = (position.current_price - position.avg_price) / position.avg_price
        triggered = gain_ratio >= self.take_profit_ratio
        if triggered:
            logger.info(
                "risk.take_profit_triggered",
                symbol=position.symbol,
                gain_ratio=str(gain_ratio),
            )
        return triggered

    def validate_order(self, order: Order, balance: Decimal) -> bool:
        if order.quantity > self.max_position_size:
            logger.warning(
                "risk.order_rejected",
                reason="exceeds_max_position_size",
                qty=order.quantity,
                max=self.max_position_size,
            )
            return False

        cost = order.price * order.quantity
        if cost > balance:
            logger.warning(
                "risk.order_rejected",
                reason="insufficient_balance",
                cost=str(cost),
                balance=str(balance),
            )
            return False

        return True

    def get_max_position_size(self, symbol: str, balance: Decimal, price: Decimal) -> int:
        if price <= 0:
            return 0
        affordable = int(balance / price)
        return min(affordable, self.max_position_size)
