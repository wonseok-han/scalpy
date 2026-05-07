import time
from datetime import datetime
from decimal import Decimal

import structlog

from scalpy.broker.base import BaseBroker
from scalpy.core.enums import OrderStatus, Side
from scalpy.core.models import Position, Signal
from scalpy.events.bus import EventBus
from scalpy.strategy.registry import StrategyRegistry
from scalpy.trading.order import OrderManager
from scalpy.trading.position import PositionManager
from scalpy.trading.risk import RiskManager

logger = structlog.get_logger()

_BALANCE_CACHE_TTL = 10


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
        self._bus: EventBus | None = None
        self._cached_balance: Decimal = Decimal("0")
        self._balance_fetched_at: float = 0

    def set_event_bus(self, bus: EventBus) -> None:
        self._bus = bus

    @property
    def positions(self) -> PositionManager:
        return self._positions

    @property
    def orders(self) -> OrderManager:
        return self._orders

    async def get_cached_balance(self) -> Decimal:
        now = time.monotonic()
        if now - self._balance_fetched_at > _BALANCE_CACHE_TTL:
            try:
                self._cached_balance = await self._broker.get_balance()
                self._balance_fetched_at = now
            except Exception as e:
                logger.warning("engine.balance_fetch_failed", error=str(e))
        return self._cached_balance

    async def sync_positions(self) -> int:
        broker_positions = await self._broker.get_positions()
        for pos in broker_positions:
            if self._positions.get(pos.symbol) is None:
                pos.unrealized_pnl = (pos.current_price - pos.avg_price) * pos.quantity
                self._positions._positions[pos.symbol] = pos
        count = len(broker_positions)
        if count:
            logger.info("engine.positions_synced", count=count)
        return count

    async def update_symbols(self, symbols: list[str]) -> None:
        held = {p.symbol for p in self._positions.all()}
        self._active_symbols = set(symbols) | held
        logger.info("engine.symbols_updated", symbols=list(self._active_symbols))

    async def start(self) -> None:
        await self._broker.connect()
        self._running = True
        logger.info("engine.started")
        if self._bus:
            await self._bus.emit("engine.started")

    async def stop(self) -> None:
        self._running = False
        await self._broker.disconnect()
        logger.info("engine.stopped")
        if self._bus:
            await self._bus.emit("engine.stopped")

    async def on_tick(self, symbol: str, price: Decimal, volume: int) -> None:
        if not self._running:
            return

        self._positions.update_price(symbol, price)
        if self._bus:
            await self._bus.emit("tick.received", {"symbol": symbol, "price": str(price), "volume": volume})
            pos = self._positions.get(symbol)
            if pos:
                await self._bus.emit("position.updated", {"symbol": symbol, "current_price": str(price)})
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
        if not self._running:
            return
        if self._orders.has_pending_for(signal.symbol):
            return

        balance = await self.get_cached_balance()
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

        if self._bus:
            await self._bus.emit("signal.generated", {
                "symbol": signal.symbol, "side": signal.side.value,
                "strategy": signal.strategy, "price": str(signal.price),
                "confidence": signal.confidence,
            })

        result = await self._orders.submit(order)
        if result.status == OrderStatus.REJECTED and signal.side == Side.SELL:
            self._positions.remove(signal.symbol)
            logger.info("engine.stale_position_removed", symbol=signal.symbol)
            return
        if result.status == OrderStatus.FILLED:
            self._positions.update_on_fill(result)
            if self._bus:
                await self._bus.emit("order.filled", {
                    "symbol": result.symbol, "side": result.side.value,
                    "price": str(result.price), "qty": result.quantity,
                    "strategy": result.strategy,
                })
                if result.side == Side.BUY:
                    await self._bus.emit("position.opened", {
                        "symbol": result.symbol, "qty": result.quantity,
                        "avg_price": str(result.price), "strategy": result.strategy,
                    })

    async def _check_risk(self, symbol: str) -> None:
        pos = self._positions.get(symbol)
        if pos is None:
            return

        if self._risk.check_stop_loss(pos):
            await self._force_close(pos, reason="stop_loss")
        elif self._risk.check_take_profit(pos):
            await self._force_close(pos, reason="take_profit")

    async def _force_close(self, pos: Position, reason: str = "") -> None:
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
            pnl = (result.price - pos.avg_price) * pos.quantity
            self._positions.update_on_fill(result)
            logger.info("engine.position_force_closed", symbol=pos.symbol, reason=reason)
            if self._bus:
                await self._bus.emit("position.closed", {
                    "symbol": pos.symbol, "qty": pos.quantity,
                    "pnl": str(pnl), "reason": reason,
                })
