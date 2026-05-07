from decimal import Decimal

from scalpy.broker.mock import MockBroker
from scalpy.core.enums import Side
from scalpy.strategy.registry import StrategyRegistry
from scalpy.strategy.rsi import RSIStrategy
from scalpy.trading.engine import TradingEngine
from scalpy.trading.risk import RiskManager


class TestTradingEngine:
    def setup_method(self) -> None:
        self.broker = MockBroker(initial_balance=Decimal("10000000"))
        self.registry = StrategyRegistry()
        self.registry.register(RSIStrategy())
        self.risk = RiskManager(stop_loss_ratio=0.02, take_profit_ratio=0.03)
        self.engine = TradingEngine(self.broker, self.registry, self.risk)

    async def test_signal_triggers_order(self) -> None:
        await self.engine.start()

        # Feed declining prices to trigger RSI oversold → BUY
        for i in range(16):
            await self.engine.on_tick("005930", Decimal(str(100 - i * 2)), 100)

        orders = self.engine.orders.get_history()
        assert len(orders) > 0
        assert orders[0].side == Side.BUY

        await self.engine.stop()

    async def test_stop_loss_closes_position(self) -> None:
        await self.engine.start()

        # Create a position via RSI signal
        for i in range(16):
            await self.engine.on_tick("005930", Decimal(str(100 - i * 2)), 100)

        assert len(self.engine.positions.all()) > 0

        # Big price drop triggers stop loss
        await self.engine.on_tick("005930", Decimal("50"), 100)

        # Position should be closed, then immediately reopened by RSI signal
        # Verify at least one sell order in history (the stop-loss close)
        sell_orders = [o for o in self.engine.orders.get_history() if o.side == Side.SELL]
        assert len(sell_orders) > 0

        await self.engine.stop()

    async def test_engine_ignores_ticks_when_stopped(self) -> None:
        # Don't start engine
        await self.engine.on_tick("005930", Decimal("100"), 100)
        assert len(self.engine.orders.get_history()) == 0
