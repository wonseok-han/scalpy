from abc import ABC, abstractmethod
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from scalpy.core.models import Order, Position
from scalpy.trading.position import PositionManager


class BaseBroker(ABC):
    def __init__(self) -> None:
        self._pm = PositionManager()
        self._position_names: dict[str, str] = {}

    @property
    def positions(self) -> PositionManager:
        return self._pm

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def place_order(self, order: Order) -> Order: ...

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool: ...

    async def cancel_all_orders(self) -> int:
        return 0

    @abstractmethod
    async def sync_positions(self) -> int:
        """Fetch positions from external source and update internal cache."""
        ...

    @abstractmethod
    async def get_balance(self) -> Decimal: ...

    async def get_available_cash(self) -> Decimal:
        """주문가능금액 (예수금). 기본 구현은 get_balance 위임."""
        return await self.get_balance()

    @abstractmethod
    async def get_trade_history(self) -> list[dict[str, Any]]:
        """당일 체결내역 조회."""

    async def get_period_pnl(self) -> list[dict[str, Any]]:
        """기간손익현황 조회 (실거래만)."""
        return []

    async def get_daily_profit_summary(self) -> dict[str, Any]:
        """당일 실현손익 요약 조회 (실거래만)."""
        return {}

    @abstractmethod
    async def get_top_volume_stocks(self, count: int = 30) -> list[dict[str, Any]]:
        """거래량 상위 종목 조회."""

    @abstractmethod
    async def subscribe_market_data(
        self, symbols: list[str], callback: Callable[..., Any]
    ) -> None: ...
