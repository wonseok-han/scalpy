import time
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any

from scalpy.core.models import Signal

_DEFAULT_COOLDOWN = 30


class BaseStrategy(ABC):
    name: str
    display_name: str
    description: str

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

    def _init_base(self) -> None:
        self.enabled: bool = True
        self.cooldown_seconds: int = _DEFAULT_COOLDOWN
        self._last_signal_at: dict[str, float] = {}

    def _check_cooldown(self, symbol: str, side: str) -> bool:
        key = f"{symbol}:{side}"
        now = time.monotonic()
        last = self._last_signal_at.get(key, 0)
        if now - last < self.cooldown_seconds:
            return False
        self._last_signal_at[key] = now
        return True

    @abstractmethod
    async def on_tick(self, symbol: str, price: Decimal, volume: int) -> Signal | None:
        """Called on each trade tick. Return a Signal or None."""

    @abstractmethod
    async def on_orderbook(
        self,
        symbol: str,
        asks: list[tuple[Decimal, int]],
        bids: list[tuple[Decimal, int]],
    ) -> Signal | None:
        """Called on orderbook update. Return a Signal or None."""

    def configure(self, params: dict[str, Any]) -> None:
        for key, value in params.items():
            if hasattr(self, key):
                setattr(self, key, value)
