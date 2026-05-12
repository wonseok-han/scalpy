from collections import deque
from datetime import datetime
from decimal import Decimal

from scalpy.core.enums import Side
from scalpy.core.models import Signal
from scalpy.strategy.base import BaseStrategy


class MACrossStrategy(BaseStrategy):
    name = "ma_cross"
    display_name = "이동평균 교차"
    description = "Moving Average Crossover — short MA crosses long MA"

    def __init__(self) -> None:
        self._init_base()
        self.short_window: int = 5
        self.long_window: int = 20
        self._prices: dict[str, deque[Decimal]] = {}

    def reset(self) -> None:
        super().reset()
        self._prices.clear()

    def _get_prices(self, symbol: str) -> deque[Decimal]:
        if symbol not in self._prices:
            self._prices[symbol] = deque(maxlen=self.long_window + 1)
        return self._prices[symbol]

    def _ma(self, prices: deque[Decimal], window: int) -> Decimal | None:
        if len(prices) < window:
            return None
        recent = list(prices)[-window:]
        return Decimal(sum(recent)) / window

    async def on_tick(self, symbol: str, price: Decimal, volume: int) -> Signal | None:
        self._advance_tick(symbol)
        prices = self._get_prices(symbol)
        prices.append(price)

        short_ma = self._ma(prices, self.short_window)
        long_ma = self._ma(prices, self.long_window)
        if short_ma is None or long_ma is None:
            return None

        prev_prices_len = len(prices)
        if prev_prices_len < self.long_window + 1:
            return None

        prev_short = self._ma(deque(list(prices)[:-1], maxlen=len(prices)), self.short_window)
        if prev_short is None:
            return None

        if prev_short <= long_ma < short_ma:
            if self._check_cooldown(symbol, "BUY"):
                return Signal(symbol, Side.BUY, self.name, price, 0, 0.7, datetime.now())

        if prev_short >= long_ma > short_ma:
            if self._check_cooldown(symbol, "SELL"):
                return Signal(symbol, Side.SELL, self.name, price, 0, 0.7, datetime.now())

        return None

    def prefill(self, symbol: str, candles: list[dict]) -> None:
        prices = self._get_prices(symbol)
        for c in candles[-(self.long_window + 1) :]:
            prices.append(Decimal(str(c["close"])))

    async def on_orderbook(
        self,
        symbol: str,
        asks: list[tuple[Decimal, int]],
        bids: list[tuple[Decimal, int]],
    ) -> Signal | None:
        return None
