from decimal import Decimal

from scalpy.broker.mock import MockBroker
from scalpy.core.enums import OrderStatus, OrderType, Side
from scalpy.core.models import Order
from scalpy.strategy.registry import StrategyRegistry
from scalpy.trading.engine import TradingEngine
from scalpy.trading.risk import RiskManager


class TestBrokerOrderFlow:
    async def test_buy_order_fills_and_updates_balance(self) -> None:
        broker = MockBroker(initial_balance=Decimal("10000000"))
        await broker.connect()

        order = Order(
            symbol="005930",
            side=Side.BUY,
            order_type=OrderType.MARKET,
            price=Decimal("72000"),
            quantity=10,
            strategy="factor",
        )
        result = await broker.place_order(order)
        assert result.status == OrderStatus.FILLED

        balance = await broker.get_balance()
        cost = Decimal("720000")
        commission = int(cost * Decimal("0.000147"))
        assert balance == Decimal("10000000") - cost - commission

        broker.positions.update_on_fill(result)
        positions = broker.positions.all()
        assert len(positions) == 1
        assert positions[0].symbol == "005930"

        await broker.disconnect()

    async def test_sell_order_restores_balance(self) -> None:
        broker = MockBroker(initial_balance=Decimal("10000000"))
        await broker.connect()

        buy = Order("005930", Side.BUY, OrderType.MARKET, Decimal("72000"), 10, "factor")
        buy_result = await broker.place_order(buy)
        broker.positions.update_on_fill(buy_result)

        sell = Order("005930", Side.SELL, OrderType.MARKET, Decimal("73000"), 10, "factor")
        result = await broker.place_order(sell)
        assert result.status == OrderStatus.FILLED
        broker.positions.update_on_fill(result)

        balance = await broker.get_balance()
        buy_cost = Decimal("720000")
        sell_cost = Decimal("730000")
        buy_fee = int(buy_cost * Decimal("0.000147"))
        sell_fee = int(sell_cost * Decimal("0.000147")) + int(sell_cost * Decimal("0.0018"))
        assert balance == Decimal("10000000") - buy_cost - buy_fee + sell_cost - sell_fee

        positions = broker.positions.all()
        assert len(positions) == 0

        await broker.disconnect()

    async def test_insufficient_balance_rejects(self) -> None:
        broker = MockBroker(initial_balance=Decimal("100"))
        await broker.connect()

        order = Order("005930", Side.BUY, OrderType.MARKET, Decimal("72000"), 10, "factor")
        result = await broker.place_order(order)
        assert result.status == OrderStatus.REJECTED

        await broker.disconnect()
