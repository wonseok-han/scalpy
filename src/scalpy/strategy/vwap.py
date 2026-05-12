from datetime import datetime
from decimal import Decimal

from scalpy.core.enums import Side
from scalpy.core.models import Signal
from scalpy.strategy.base import BaseStrategy


class VWAPStrategy(BaseStrategy):
    name = "vwap"
    display_name = "VWAP 이탈"
    description = "VWAP Deviation — buy below VWAP, sell above VWAP"

    def __init__(self) -> None:
        self._init_base()
        self.deviation_threshold: float = 0.005
        self._cumulative_volume: dict[str, int] = {}
        self._cumulative_pv: dict[str, Decimal] = {}

    def reset(self) -> None:
        super().reset()
        self._cumulative_volume.clear()
        self._cumulative_pv.clear()

    def _update_vwap(self, symbol: str, price: Decimal, volume: int) -> Decimal | None:
        if volume <= 0:
            return None

        if symbol not in self._cumulative_volume:
            self._cumulative_volume[symbol] = 0
            self._cumulative_pv[symbol] = Decimal("0")

        self._cumulative_volume[symbol] += volume
        self._cumulative_pv[symbol] += price * volume

        total_vol = self._cumulative_volume[symbol]
        if total_vol == 0:
            return None

        return self._cumulative_pv[symbol] / total_vol

    async def on_tick(self, symbol: str, price: Decimal, volume: int) -> Signal | None:
        self._advance_tick(symbol)
        vwap = self._update_vwap(symbol, price, volume)
        if vwap is None:
            return None

        deviation = float((price - vwap) / vwap)

        if deviation < -self.deviation_threshold and self._check_cooldown(symbol, "BUY"):
            return Signal(symbol, Side.BUY, self.name, price, 0, 0.5, datetime.now())

        if deviation > self.deviation_threshold and self._check_cooldown(symbol, "SELL"):
            return Signal(symbol, Side.SELL, self.name, price, 0, 0.5, datetime.now())

        return None

    async def on_orderbook(
        self,
        symbol: str,
        asks: list[tuple[Decimal, int]],
        bids: list[tuple[Decimal, int]],
    ) -> Signal | None:
        return None
