import math
from collections import deque
from datetime import datetime
from decimal import Decimal

from scalpy.core.enums import Side
from scalpy.core.models import Signal
from scalpy.strategy.base import BaseStrategy


class MeanReversionStrategy(BaseStrategy):
    name = "mean_reversion"
    display_name = "평균회귀"
    description = "Buy when price bounces back from Bollinger lower band"

    def __init__(self) -> None:
        self._init_base()
        self.window: int = 20
        self.num_std: float = 2.0
        self.cooldown_seconds: int = 1800
        self.stop_loss_ratio: float | None = 0.025
        self.take_profit_ratio: float | None = 0.04
        self._prices: dict[str, deque[Decimal]] = {}
        self._was_below: dict[str, bool] = {}

    def reset(self) -> None:
        super().reset()
        self._prices.clear()
        self._was_below.clear()

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
        if std == 0:
            return None
        mid = Decimal(str(mean))
        upper = Decimal(str(mean + self.num_std * std))
        lower = Decimal(str(mean - self.num_std * std))
        return lower, mid, upper

    async def on_tick(self, symbol: str, price: Decimal, volume: int) -> Signal | None:
        self._advance_tick(symbol)
        prices = self._get_prices(symbol)
        prices.append(price)

        bands = self._bands(prices)
        if bands is None:
            return None

        lower, mid, upper = bands
        was_below = self._was_below.get(symbol, False)

        if price < lower:
            self._was_below[symbol] = True
            return None

        if was_below and price >= lower:
            self._was_below[symbol] = False
            if self._check_cooldown(symbol, "BUY"):
                dist = float(mid - price) / float(mid) if mid > 0 else 0
                confidence = min(0.85, 0.6 + dist * 5)
                return Signal(symbol, Side.BUY, self.name, price, 0, confidence, datetime.now())

        if price > upper and self._check_cooldown(symbol, "SELL"):
            return Signal(symbol, Side.SELL, self.name, price, 0, 0.7, datetime.now())

        return None

    def prefill(self, symbol: str, candles: list[dict]) -> None:
        prices = self._get_prices(symbol)
        for c in candles[-self.window :]:
            prices.append(Decimal(str(c["close"])))

    async def on_orderbook(
        self,
        symbol: str,
        asks: list[tuple[Decimal, int]],
        bids: list[tuple[Decimal, int]],
    ) -> Signal | None:
        return None
