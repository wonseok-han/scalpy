import math
from collections import deque
from datetime import datetime
from decimal import Decimal

from scalpy.core.enums import Side
from scalpy.core.models import Signal
from scalpy.strategy.base import BaseStrategy


class BollingerStrategy(BaseStrategy):
    name = "bollinger"
    display_name = "볼린저 밴드"
    description = "Bollinger Band Breakout — buy at lower band, sell at upper band"

    def __init__(self) -> None:
        self.window: int = 20
        self.num_std: float = 2.0
        self._prices: dict[str, deque[Decimal]] = {}

    def _get_prices(self, symbol: str) -> deque[Decimal]:
        if symbol not in self._prices:
            self._prices[symbol] = deque(maxlen=self.window)
        return self._prices[symbol]

    def _bands(self, prices: deque[Decimal]) -> tuple[Decimal, Decimal, Decimal] | None:
        if len(prices) < self.window:
            return None
        recent = [float(p) for p in prices]
        mean = sum(recent) / len(recent)
        variance = sum((x - mean) ** 2 for x in recent) / len(recent)
        std = math.sqrt(variance)
        mid = Decimal(str(mean))
        upper = Decimal(str(mean + self.num_std * std))
        lower = Decimal(str(mean - self.num_std * std))
        return lower, mid, upper

    async def on_tick(self, symbol: str, price: Decimal, volume: int) -> Signal | None:
        prices = self._get_prices(symbol)
        prices.append(price)

        bands = self._bands(prices)
        if bands is None:
            return None

        lower, _mid, upper = bands

        if price <= lower:
            return Signal(symbol, Side.BUY, self.name, price, 0, 0.65, datetime.now())
        if price >= upper:
            return Signal(symbol, Side.SELL, self.name, price, 0, 0.65, datetime.now())

        return None

    async def on_orderbook(
        self,
        symbol: str,
        asks: list[tuple[Decimal, int]],
        bids: list[tuple[Decimal, int]],
    ) -> Signal | None:
        return None
