from decimal import Decimal

import pytest

from scalpy.core.enums import Side
from scalpy.strategy.bollinger import BollingerStrategy
from scalpy.strategy.ma_cross import MACrossStrategy
from scalpy.strategy.orderbook import OrderbookStrategy
from scalpy.strategy.rsi import RSIStrategy
from scalpy.strategy.vwap import VWAPStrategy


class TestMACross:
    def setup_method(self) -> None:
        self.strategy = MACrossStrategy()

    async def test_golden_cross_buy(self) -> None:
        # 20 flat ticks → prev_short == long_ma == 100
        # Then one big jump → short_ma jumps above long_ma (crossover)
        for _ in range(20):
            await self.strategy.on_tick("005930", Decimal("100"), 100)
        sig = await self.strategy.on_tick("005930", Decimal("200"), 100)
        assert sig is not None
        assert sig.side == Side.BUY

    async def test_dead_cross_sell(self) -> None:
        # 20 flat ticks at 200, then one big drop
        for _ in range(20):
            await self.strategy.on_tick("005930", Decimal("200"), 100)
        sig = await self.strategy.on_tick("005930", Decimal("100"), 100)
        assert sig is not None
        assert sig.side == Side.SELL

    async def test_insufficient_data_returns_none(self) -> None:
        sig = await self.strategy.on_tick("005930", Decimal("100"), 100)
        assert sig is None


class TestRSI:
    def setup_method(self) -> None:
        self.strategy = RSIStrategy()

    async def test_oversold_buy(self) -> None:
        # Declining prices → RSI < 30
        for i in range(16):
            await self.strategy.on_tick("005930", Decimal(str(100 - i * 2)), 100)
        sig = await self.strategy.on_tick("005930", Decimal("66"), 100)
        assert sig is not None
        assert sig.side == Side.BUY

    async def test_overbought_sell(self) -> None:
        # Rising prices → RSI > 70
        for i in range(16):
            await self.strategy.on_tick("005930", Decimal(str(100 + i * 2)), 100)
        sig = await self.strategy.on_tick("005930", Decimal("134"), 100)
        assert sig is not None
        assert sig.side == Side.SELL

    async def test_insufficient_data_returns_none(self) -> None:
        for i in range(5):
            sig = await self.strategy.on_tick("005930", Decimal(str(100 + i)), 100)
        assert sig is None


class TestBollinger:
    def setup_method(self) -> None:
        self.strategy = BollingerStrategy()

    async def test_lower_band_buy(self) -> None:
        # Fill window with stable prices, then drop below lower band
        for i in range(20):
            await self.strategy.on_tick("005930", Decimal("100"), 100)
        sig = await self.strategy.on_tick("005930", Decimal("90"), 100)
        assert sig is not None
        assert sig.side == Side.BUY

    async def test_upper_band_sell(self) -> None:
        for i in range(20):
            await self.strategy.on_tick("005930", Decimal("100"), 100)
        sig = await self.strategy.on_tick("005930", Decimal("110"), 100)
        assert sig is not None
        assert sig.side == Side.SELL

    async def test_within_bands_no_signal(self) -> None:
        # Need price variation to create nonzero std, then stay within bands
        for i in range(20):
            await self.strategy.on_tick("005930", Decimal(str(99 + (i % 3))), 100)
        sig = await self.strategy.on_tick("005930", Decimal("100"), 100)
        assert sig is None


class TestOrderbook:
    def setup_method(self) -> None:
        self.strategy = OrderbookStrategy()

    async def test_bid_imbalance_buy(self) -> None:
        asks = [(Decimal("100"), 100)]
        bids = [(Decimal("99"), 200)]
        sig = await self.strategy.on_orderbook("005930", asks, bids)
        assert sig is not None
        assert sig.side == Side.BUY

    async def test_ask_imbalance_sell(self) -> None:
        asks = [(Decimal("100"), 200)]
        bids = [(Decimal("99"), 100)]
        sig = await self.strategy.on_orderbook("005930", asks, bids)
        assert sig is not None
        assert sig.side == Side.SELL

    async def test_balanced_no_signal(self) -> None:
        asks = [(Decimal("100"), 100)]
        bids = [(Decimal("99"), 100)]
        sig = await self.strategy.on_orderbook("005930", asks, bids)
        assert sig is None

    async def test_on_tick_returns_none(self) -> None:
        sig = await self.strategy.on_tick("005930", Decimal("100"), 100)
        assert sig is None


class TestVWAP:
    def setup_method(self) -> None:
        self.strategy = VWAPStrategy()

    async def test_below_vwap_buy(self) -> None:
        for _ in range(10):
            await self.strategy.on_tick("005930", Decimal("100"), 1000)
        sig = await self.strategy.on_tick("005930", Decimal("94"), 10)
        assert sig is not None
        assert sig.side == Side.BUY

    async def test_above_vwap_sell(self) -> None:
        for _ in range(10):
            await self.strategy.on_tick("005930", Decimal("100"), 1000)
        sig = await self.strategy.on_tick("005930", Decimal("106"), 10)
        assert sig is not None
        assert sig.side == Side.SELL

    async def test_at_vwap_no_signal(self) -> None:
        for _ in range(10):
            await self.strategy.on_tick("005930", Decimal("100"), 1000)
        sig = await self.strategy.on_tick("005930", Decimal("100"), 1000)
        assert sig is None
