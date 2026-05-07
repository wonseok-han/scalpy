from decimal import Decimal

from scalpy.core.enums import OrderType, Side
from scalpy.core.models import Order
from scalpy.trading.position import PositionManager


class TestPositionManager:
    def setup_method(self) -> None:
        self.pm = PositionManager()

    def test_avg_price_single_buy(self) -> None:
        order = Order(
            symbol="005930",
            side=Side.BUY,
            order_type=OrderType.MARKET,
            price=Decimal("72000"),
            quantity=10,
            strategy="rsi",
        )
        self.pm.update_on_fill(order)
        pos = self.pm.get("005930")
        assert pos is not None
        assert pos.avg_price == Decimal("72000")
        assert pos.quantity == 10

    def test_avg_price_multiple_buys(self) -> None:
        order1 = Order(
            symbol="005930",
            side=Side.BUY,
            order_type=OrderType.MARKET,
            price=Decimal("72000"),
            quantity=10,
            strategy="rsi",
        )
        order2 = Order(
            symbol="005930",
            side=Side.BUY,
            order_type=OrderType.MARKET,
            price=Decimal("73000"),
            quantity=10,
            strategy="rsi",
        )
        self.pm.update_on_fill(order1)
        self.pm.update_on_fill(order2)

        pos = self.pm.get("005930")
        assert pos is not None
        assert pos.avg_price == Decimal("72500")
        assert pos.quantity == 20

    def test_unrealized_pnl(self) -> None:
        order = Order(
            symbol="005930",
            side=Side.BUY,
            order_type=OrderType.MARKET,
            price=Decimal("72000"),
            quantity=10,
            strategy="rsi",
        )
        self.pm.update_on_fill(order)
        self.pm.update_price("005930", Decimal("73000"))

        pos = self.pm.get("005930")
        assert pos is not None
        assert pos.unrealized_pnl == Decimal("10000")  # (73000-72000)*10

    def test_sell_closes_position(self) -> None:
        buy = Order(
            symbol="005930",
            side=Side.BUY,
            order_type=OrderType.MARKET,
            price=Decimal("72000"),
            quantity=10,
            strategy="rsi",
        )
        sell = Order(
            symbol="005930",
            side=Side.SELL,
            order_type=OrderType.MARKET,
            price=Decimal("73000"),
            quantity=10,
            strategy="rsi",
        )
        self.pm.update_on_fill(buy)
        self.pm.update_on_fill(sell)

        assert self.pm.get("005930") is None

    def test_partial_sell_reduces_position(self) -> None:
        buy = Order(
            symbol="005930",
            side=Side.BUY,
            order_type=OrderType.MARKET,
            price=Decimal("72000"),
            quantity=10,
            strategy="rsi",
        )
        sell = Order(
            symbol="005930",
            side=Side.SELL,
            order_type=OrderType.MARKET,
            price=Decimal("73000"),
            quantity=5,
            strategy="rsi",
        )
        self.pm.update_on_fill(buy)
        self.pm.update_on_fill(sell)

        pos = self.pm.get("005930")
        assert pos is not None
        assert pos.quantity == 5
        assert pos.realized_pnl == Decimal("5000")  # (73000-72000)*5
