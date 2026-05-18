from collections import deque
from datetime import datetime
from decimal import Decimal

from scalpy.core.enums import Side
from scalpy.core.models import Signal
from scalpy.strategy.base import BaseStrategy


class _Candle:
    __slots__ = ("open", "high", "low", "close", "volume")

    def __init__(self, price: Decimal, volume: int = 0) -> None:
        self.open = price
        self.high = price
        self.low = price
        self.close = price
        self.volume = volume

    def update(self, price: Decimal, volume: int = 0) -> None:
        if price > self.high:
            self.high = price
        if price < self.low:
            self.low = price
        self.close = price
        self.volume += volume


class VolumeSpikeStrategy(BaseStrategy):
    name = "volume_spike"
    display_name = "거래량폭발"
    description = "Detect volume explosion + rapid price surge for quick momentum entry"

    def __init__(self) -> None:
        self._init_base()
        self.baseline_window: int = 10
        self.spike_ratio: float = 3.0
        self.min_surge_pct: float = 0.005
        self.max_surge_pct: float = 0.08
        self.candle_minutes: int = 1
        self.cooldown_seconds: int = 120
        self.stop_loss_ratio: float | None = 0.015
        self.take_profit_ratio: float | None = None
        self.min_tick_volume: int = 1
        self._candles: dict[str, deque[_Candle]] = {}
        self._current_candle: dict[str, _Candle] = {}
        self._candle_start: dict[str, datetime] = {}

    def reset(self) -> None:
        super().reset()
        self._candles.clear()
        self._current_candle.clear()
        self._candle_start.clear()

    def _get_candles(self, symbol: str) -> deque[_Candle]:
        if symbol not in self._candles:
            self._candles[symbol] = deque(maxlen=self.baseline_window + 5)
        return self._candles[symbol]

    def _rotate_candle(self, symbol: str, price: Decimal, volume: int, now: datetime) -> None:
        candles = self._get_candles(symbol)
        start = self._candle_start.get(symbol)
        interval = self.candle_minutes * 60

        if start is None:
            self._candle_start[symbol] = now
            self._current_candle[symbol] = _Candle(price, volume)
            return

        elapsed = (now - start).total_seconds()
        if elapsed >= interval:
            if symbol in self._current_candle:
                candles.append(self._current_candle[symbol])
            self._candle_start[symbol] = now
            self._current_candle[symbol] = _Candle(price, volume)
        else:
            if symbol in self._current_candle:
                self._current_candle[symbol].update(price, volume)
            else:
                self._current_candle[symbol] = _Candle(price, volume)

    async def on_tick(self, symbol: str, price: Decimal, volume: int) -> Signal | None:
        if volume < self.min_tick_volume:
            return None
        self._advance_tick(symbol)
        now = datetime.now()
        self._rotate_candle(symbol, price, volume, now)

        candles = list(self._get_candles(symbol))
        if len(candles) < self.baseline_window:
            return None

        cur = self._current_candle.get(symbol)
        if cur is None or cur.volume == 0:
            return None

        baseline = candles[-self.baseline_window:]
        avg_vol = sum(c.volume for c in baseline) / len(baseline)
        if avg_vol <= 0:
            return None

        vol_ratio = cur.volume / avg_vol
        if vol_ratio < self.spike_ratio:
            return None

        if cur.open <= 0:
            return None
        surge_pct = float(cur.close - cur.open) / float(cur.open)

        if surge_pct < self.min_surge_pct:
            return None
        if surge_pct > self.max_surge_pct:
            return None

        if not self._check_cooldown(symbol, "BUY"):
            return None

        confidence = min(0.9, 0.5 + (vol_ratio - self.spike_ratio) * 0.05 + surge_pct * 10)
        return Signal(symbol, Side.BUY, self.name, price, 0, confidence, now)

    def prefill(self, symbol: str, candles_data: list[dict]) -> None:
        if not candles_data:
            return
        candles = self._get_candles(symbol)
        for c in candles_data[-(self.baseline_window + 5):]:
            candle = _Candle(Decimal(str(c["close"])))
            if "open" in c:
                candle.open = Decimal(str(c["open"]))
            if "high" in c:
                candle.high = Decimal(str(c["high"]))
            if "low" in c:
                candle.low = Decimal(str(c["low"]))
            if "volume" in c:
                candle.volume = c["volume"]
            candles.append(candle)

    async def on_orderbook(
        self,
        symbol: str,
        asks: list[tuple[Decimal, int]],
        bids: list[tuple[Decimal, int]],
    ) -> Signal | None:
        return None
