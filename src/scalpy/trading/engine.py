from datetime import datetime
from decimal import Decimal

import structlog

from scalpy.broker.base import BaseBroker
from scalpy.core.enums import OrderStatus, Side
from scalpy.core.models import Position, Signal
from scalpy.strategy.registry import StrategyRegistry
from scalpy.trading.order import OrderManager
from scalpy.trading.position import PositionManager
from scalpy.trading.risk import RiskManager

logger = structlog.get_logger()


class TradingEngine:
    def __init__(
        self,
        broker: BaseBroker,
        registry: StrategyRegistry,
        risk: RiskManager,
    ) -> None:
        self._broker = broker
        self._registry = registry
        self._risk = risk
        self._positions = PositionManager()
        self._orders = OrderManager(broker)
        self._running = False

    @property
    def positions(self) -> PositionManager:
        return self._positions

    @property
    def orders(self) -> OrderManager:
        return self._orders

    async def update_symbols(self, symbols: list[str]) -> None:
        held = {p.symbol for p in self._positions.all()}
        self._active_symbols = set(symbols) | held
        logger.info("engine.symbols_updated", symbols=list(self._active_symbols))

    async def start(self) -> None:
        await self._broker.connect()
        self._running = True
        logger.info("engine.started")

    async def stop(self) -> None:
        self._running = False
        await self._broker.disconnect()
        logger.info("engine.stopped")

    async def on_tick(self, symbol: str, price: Decimal, volume: int) -> None:
        if not self._running:
            return

        self._positions.update_price(symbol, price)
        await self._check_risk(symbol)

        for strategy in self._registry.all():
            signal = await strategy.on_tick(symbol, price, volume)
            if signal is not None:
                await self._process_signal(signal)

    async def on_orderbook(
        self,
        symbol: str,
        asks: list[tuple[Decimal, int]],
        bids: list[tuple[Decimal, int]],
    ) -> None:
        if not self._running:
            return

        for strategy in self._registry.all():
            signal = await strategy.on_orderbook(symbol, asks, bids)
            if signal is not None:
                await self._process_signal(signal)

    async def _process_signal(self, signal: Signal) -> None:
        if self._orders.has_pending_for(signal.symbol):
            return

        balance = await self._broker.get_balance()
        qty = self._risk.get_max_position_size(signal.symbol, balance, signal.price)

        if signal.side == Side.SELL:
            pos = self._positions.get(signal.symbol)
            if pos is None or pos.quantity == 0:
                return
            qty = pos.quantity

        if qty <= 0:
            return

        order = self._orders.signal_to_order(signal, qty)

        if signal.side == Side.BUY and not self._risk.validate_order(order, balance):
            return

        result = await self._orders.submit(order)
        if result.status == OrderStatus.FILLED:
            self._positions.update_on_fill(result)

    async def _check_risk(self, symbol: str) -> None:
        pos = self._positions.get(symbol)
        if pos is None:
            return

        if self._risk.check_stop_loss(pos) or self._risk.check_take_profit(pos):
            await self._force_close(pos)

    async def _force_close(self, pos: Position) -> None:
        signal = Signal(
            symbol=pos.symbol,
            side=Side.SELL,
            strategy=pos.strategy,
            price=pos.current_price,
            quantity=pos.quantity,
            confidence=1.0,
            timestamp=datetime.now(),
        )
        order = self._orders.signal_to_order(signal, pos.quantity)
        result = await self._orders.submit(order)
        if result.status == OrderStatus.FILLED:
            self._positions.update_on_fill(result)
            logger.info("engine.position_force_closed", symbol=pos.symbol)
