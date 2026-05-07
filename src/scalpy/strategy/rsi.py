from collections import deque
from datetime import datetime
from decimal import Decimal

from scalpy.core.enums import Side
from scalpy.core.models import Signal
from scalpy.strategy.base import BaseStrategy


class RSIStrategy(BaseStrategy):
    name = "rsi"
    display_name = "RSI 과매수/과매도"
    description = "RSI Overbought/Oversold — buy below 30, sell above 70"

    def __init__(self) -> None:
        self.window: int = 14
        self.oversold: int = 30
        self.overbought: int = 70
        self._prices: dict[str, deque[Decimal]] = {}

    def _get_prices(self, symbol: str) -> deque[Decimal]:
        if symbol not in self._prices:
            self._prices[symbol] = deque(maxlen=self.window + 2)
        return self._prices[symbol]

    def _calc_rsi(self, prices: deque[Decimal]) -> float | None:
        if len(prices) < self.window + 1:
            return None
        changes = [float(prices[i] - prices[i - 1]) for i in range(1, len(prices))]
        recent = changes[-self.window :]
        gains = [c for c in recent if c > 0]
        losses = [-c for c in recent if c < 0]
        avg_gain = sum(gains) / self.window if gains else 0
        avg_loss = sum(losses) / self.window if losses else 0
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    async def on_tick(self, symbol: str, price: Decimal, volume: int) -> Signal | None:
        prices = self._get_prices(symbol)
        prices.append(price)

        rsi = self._calc_rsi(prices)
        if rsi is None:
            return None

        if rsi < self.oversold:
            return Signal(symbol, Side.BUY, self.name, price, 0, 0.6, datetime.now())
        if rsi > self.overbought:
            return Signal(symbol, Side.SELL, self.name, price, 0, 0.6, datetime.now())

        return None

    async def on_orderbook(
        self,
        symbol: str,
        asks: list[tuple[Decimal, int]],
        bids: list[tuple[Decimal, int]],
    ) -> Signal | None:
        return None
