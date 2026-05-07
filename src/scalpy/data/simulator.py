import asyncio
import random
from decimal import Decimal

import structlog

logger = structlog.get_logger()

_TICK_SIZES = [
    (2_000, 1),
    (5_000, 5),
    (20_000, 10),
    (50_000, 50),
    (200_000, 100),
    (500_000, 500),
    (float("inf"), 1_000),
]

_DEFAULT_PRICES: dict[str, int] = {
    "005930": 71500,
    "000660": 183000,
    "035720": 54000,
    "035420": 208000,
    "051910": 377000,
    "006400": 417000,
    "068270": 174000,
}


def _tick_size(price: int) -> int:
    for threshold, tick in _TICK_SIZES:
        if price < threshold:
            return tick
    return 1000


def _rand_volume() -> int:
    return random.randint(50, 5000)


class MarketSimulator:
    """장 외 시간 테스트용 가상 시세 생성기.

    랜덤 워크로 가격을 변동시키고, stream.emit_tick / emit_orderbook을 호출한다.
    """

    def __init__(
        self,
        stream: "MarketDataStream",
        symbols: list[str],
        *,
        interval: float = 0.5,
        volatility: float = 0.002,
    ) -> None:
        self._stream = stream
        self._symbols = symbols
        self._interval = interval
        self._volatility = volatility
        self._prices: dict[str, int] = {}
        self._running = False
        self._task: asyncio.Task | None = None

        for sym in symbols:
            self._prices[sym] = _DEFAULT_PRICES.get(sym, 100000)

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "simulator.started",
            symbols=self._symbols,
            interval=self._interval,
            volatility=self._volatility,
        )

    async def _loop(self) -> None:
        while self._running:
            for sym in self._symbols:
                if not self._running:
                    return
                price = self._prices[sym]
                tick = _tick_size(price)

                move = random.gauss(0, self._volatility)
                ticks = max(1, int(abs(move) * price / tick))
                if move > 0:
                    price += tick * ticks
                elif move < 0:
                    price -= tick * ticks
                price = max(tick, price)

                self._prices[sym] = price
                volume = _rand_volume()

                await self._stream.emit_tick(sym, Decimal(str(price)), volume)

                orderbook = self._generate_orderbook(price, tick)
                await self._stream.emit_orderbook(sym, orderbook[0], orderbook[1])

            await asyncio.sleep(self._interval)

    def _generate_orderbook(
        self, price: int, tick: int
    ) -> tuple[list[tuple[Decimal, int]], list[tuple[Decimal, int]]]:
        asks = []
        bids = []
        for i in range(10):
            ask_price = price + tick * (i + 1)
            bid_price = price - tick * (i + 1)
            if bid_price <= 0:
                bid_price = tick
            ask_vol = random.randint(100, 10000)
            bid_vol = random.randint(100, 10000)
            asks.append((Decimal(str(ask_price)), ask_vol))
            bids.append((Decimal(str(bid_price)), bid_vol))
        return asks, bids

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("simulator.stopped")

    def update_symbols(self, symbols: list[str]) -> None:
        for sym in symbols:
            if sym not in self._prices:
                self._prices[sym] = _DEFAULT_PRICES.get(sym, 100000)
        self._symbols = symbols
