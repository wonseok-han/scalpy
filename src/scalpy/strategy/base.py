from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any

from scalpy.core.models import Signal


class BaseStrategy(ABC):
    name: str
    description: str

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
        """Inject strategy-specific parameters from config."""
        for key, value in params.items():
            if hasattr(self, key):
                setattr(self, key, value)
