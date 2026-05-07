from abc import ABC, abstractmethod
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from scalpy.core.models import Order, Position


class BaseBroker(ABC):
    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def place_order(self, order: Order) -> Order: ...

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool: ...

    @abstractmethod
    async def get_positions(self) -> list[Position]: ...

    @abstractmethod
    async def get_balance(self) -> Decimal: ...

    @abstractmethod
    async def get_top_volume_stocks(self, count: int = 30) -> list[dict[str, Any]]:
        """거래량 상위 종목 조회."""

    @abstractmethod
    async def subscribe_market_data(
        self, symbols: list[str], callback: Callable[..., Any]
    ) -> None: ...
