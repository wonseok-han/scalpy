from decimal import Decimal

from scalpy.broker.mock import MockBroker
from scalpy.core.enums import OrderStatus, OrderType, Side
from scalpy.core.models import Order
from scalpy.data.stream import MarketDataStream
from scalpy.strategy.registry import StrategyRegistry
from scalpy.strategy.rsi import RSIStrategy
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
            strategy="rsi",
        )
        result = await broker.place_order(order)
        assert result.status == OrderStatus.FILLED

        balance = await broker.get_balance()
        assert balance == Decimal("10000000") - Decimal("720000")

        positions = await broker.get_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "005930"

        await broker.disconnect()

    async def test_sell_order_restores_balance(self) -> None:
        broker = MockBroker(initial_balance=Decimal("10000000"))
        await broker.connect()

        buy = Order("005930", Side.BUY, OrderType.MARKET, Decimal("72000"), 10, "rsi")
        await broker.place_order(buy)

        sell = Order("005930", Side.SELL, OrderType.MARKET, Decimal("73000"), 10, "rsi")
        result = await broker.place_order(sell)
        assert result.status == OrderStatus.FILLED

        balance = await broker.get_balance()
        assert balance == Decimal("10000000") - Decimal("720000") + Decimal("730000")

        positions = await broker.get_positions()
        assert len(positions) == 0

        await broker.disconnect()

    async def test_insufficient_balance_rejects(self) -> None:
        broker = MockBroker(initial_balance=Decimal("100"))
        await broker.connect()

        order = Order("005930", Side.BUY, OrderType.MARKET, Decimal("72000"), 10, "rsi")
        result = await broker.place_order(order)
        assert result.status == OrderStatus.REJECTED

        await broker.disconnect()


class TestEndToEndFlow:
    async def test_full_tick_to_order_flow(self) -> None:
        broker = MockBroker(initial_balance=Decimal("10000000"))
        registry = StrategyRegistry()
        registry.register(RSIStrategy())
        risk = RiskManager(stop_loss_ratio=0.02, take_profit_ratio=0.03)

        engine = TradingEngine(broker, registry, risk)
        stream = MarketDataStream()
        stream.on_tick(engine.on_tick)

        await engine.start()
        await stream.start(["005930"])

        # Feed declining prices → RSI oversold → BUY signal → order fill
        for i in range(16):
            await stream.emit_tick("005930", Decimal(str(100 - i * 2)), 100)

        assert len(engine.orders.get_history()) > 0
        assert any(o.status == OrderStatus.FILLED for o in engine.orders.get_history())

        await stream.stop()
        await engine.stop()

    async def test_multi_symbol_processing(self) -> None:
        broker = MockBroker(initial_balance=Decimal("10000000"))
        registry = StrategyRegistry()
        registry.register(RSIStrategy())
        risk = RiskManager(stop_loss_ratio=0.02, take_profit_ratio=0.03)

        engine = TradingEngine(broker, registry, risk)
        await engine.start()

        # Process ticks for two symbols independently
        for i in range(16):
            await engine.on_tick("005930", Decimal(str(100 - i * 2)), 100)
            await engine.on_tick("000660", Decimal(str(200 - i * 3)), 100)

        orders = engine.orders.get_history()
        symbols = {o.symbol for o in orders}
        assert len(symbols) >= 1  # at least one symbol triggered

        await engine.stop()
