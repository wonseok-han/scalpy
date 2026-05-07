import asyncio
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import structlog

logger = structlog.get_logger()

TickCallback = Callable[[str, Decimal, int], Any]
OrderbookCallback = Callable[[str, list[tuple[Decimal, int]], list[tuple[Decimal, int]]], Any]


class MarketDataStream:
    def __init__(self) -> None:
        self._tick_callbacks: list[TickCallback] = []
        self._orderbook_callbacks: list[OrderbookCallback] = []
        self._running = False

    def on_tick(self, callback: TickCallback) -> None:
        self._tick_callbacks.append(callback)

    def on_orderbook(self, callback: OrderbookCallback) -> None:
        self._orderbook_callbacks.append(callback)

    async def emit_tick(self, symbol: str, price: Decimal, volume: int) -> None:
        for cb in self._tick_callbacks:
            result = cb(symbol, price, volume)
            if asyncio.iscoroutine(result):
                await result

    async def emit_orderbook(
        self,
        symbol: str,
        asks: list[tuple[Decimal, int]],
        bids: list[tuple[Decimal, int]],
    ) -> None:
        for cb in self._orderbook_callbacks:
            result = cb(symbol, asks, bids)
            if asyncio.iscoroutine(result):
                await result

    async def start(self, symbols: list[str]) -> None:
        self._running = True
        logger.info("market_data_stream.started", symbols=symbols)

    async def stop(self) -> None:
        self._running = False
        logger.info("market_data_stream.stopped")

    @property
    def is_running(self) -> bool:
        return self._running
