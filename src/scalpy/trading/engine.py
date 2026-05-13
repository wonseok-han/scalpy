import asyncio
import time
import zoneinfo
from datetime import datetime
from datetime import time as dt_time
from decimal import Decimal
from typing import Any

import structlog

from scalpy.broker.base import BaseBroker
from scalpy.core.enums import OrderStatus, Side
from scalpy.core.models import Position, Signal
from scalpy.events.bus import EventBus
from scalpy.strategy.registry import StrategyRegistry
from scalpy.trading.order import OrderManager
from scalpy.trading.performance import PerformanceTracker
from scalpy.trading.position import PositionManager
from scalpy.trading.risk import RiskManager

logger = structlog.get_logger()

_BALANCE_CACHE_TTL = 10
_SYNC_INTERVAL = 10
_RISK_CHECK_INTERVAL = 10
_MIN_CONFIDENCE = 0.5
_REJECTED_COOLDOWN = 60
_CLOSE_COOLDOWN = 1800
_SPLIT_SELL_DELAY = 1.0
_UNFILLED_CANCEL_INTERVAL = 60
_MIN_PROFIT_RATIO = Decimal("0.005")
_KST = zoneinfo.ZoneInfo("Asia/Seoul")
_CUTOFF_BUY = dt_time(15, 15)
_CUTOFF_CLOSE = dt_time(15, 18)
_MARKET_END = dt_time(15, 30)


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
        self._orders = OrderManager(broker)
        self._running = False
        self._bus: EventBus | None = None
        self._cached_balance: Decimal = Decimal("0")
        self._balance_fetched_at: float = 0
        self._market_close_done = False
        self._last_sync_at: float = 0
        self._rejected_symbols: dict[str, float] = {}
        self._closed_symbols: dict[str, float] = {}
        self._untradeable: set[str] = set()
        self._risk_loop_task: asyncio.Task[None] | None = None
        self._sync_loop_task: asyncio.Task[None] | None = None
        self._sync_running = False
        self._active_symbols: set[str] = set()
        self._performance = PerformanceTracker()
        self._trade_repo: Any = None
        self._pending_buy_cost: Decimal = Decimal("0")
        self._last_unfilled_cancel: float = 0

    def set_trade_repo(self, repo: Any) -> None:
        self._trade_repo = repo

    def set_event_bus(self, bus: EventBus) -> None:
        self._bus = bus

    @property
    def positions(self) -> PositionManager:
        return self._broker.positions

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
        try:
            count = await self._broker.sync_positions()
        except Exception as e:
            logger.warning("engine.sync_failed", error=str(e))
            return 0

        now = time.monotonic()
        skip = self._untradeable | {
            s for s, t in self._rejected_symbols.items() if now - t < _REJECTED_COOLDOWN
        }
        for sym in skip:
            self.positions.remove(sym)

        self._last_sync_at = time.monotonic()

        if self._trade_repo:
            try:
                db_times = self._trade_repo.get_open_position_times()
                for pos in self.positions.all():
                    if pos.symbol in db_times:
                        pos.opened_at = db_times[pos.symbol]
            except Exception:
                pass

        if self._running:
            for pos in self.positions.all():
                await self._check_risk(pos.symbol)

        return count

    def prefill_strategies(self, symbol: str, candles: list[dict]) -> None:
        if not candles:
            return
        for strategy in self._registry.all():
            strategy.prefill(symbol, candles)
        logger.info("engine.prefilled", symbol=symbol, candles=len(candles))

    async def update_symbols(self, symbols: list[str]) -> None:
        held = {p.symbol for p in self.positions.all()}
        self._active_symbols = set(symbols) | held
        logger.info("engine.symbols_updated", symbols=list(self._active_symbols))

    async def start(self) -> None:
        await self._broker.connect()
        self._running = True
        self.start_background_loops()
        logger.info("engine.started")
        if self._bus:
            await self._bus.emit("engine.started")

    async def stop(self) -> None:
        self._running = False
        self.stop_background_loops()
        self.stop_sync_loop()
        await self._broker.disconnect()
        logger.info("engine.stopped")
        if self._bus:
            await self._bus.emit("engine.stopped")

    def start_sync_loop(self) -> None:
        self._sync_running = True
        if not self._sync_loop_task or self._sync_loop_task.done():
            self._sync_loop_task = asyncio.create_task(self._sync_loop())

    def stop_sync_loop(self) -> None:
        self._sync_running = False
        if self._sync_loop_task and not self._sync_loop_task.done():
            self._sync_loop_task.cancel()
        self._sync_loop_task = None

    def start_background_loops(self) -> None:
        if not self._risk_loop_task or self._risk_loop_task.done():
            self._risk_loop_task = asyncio.create_task(self._risk_check_loop())
        self.start_sync_loop()

    def stop_background_loops(self) -> None:
        if self._risk_loop_task and not self._risk_loop_task.done():
            self._risk_loop_task.cancel()
        self._risk_loop_task = None

    async def _risk_check_loop(self) -> None:
        while self._running:
            await asyncio.sleep(_RISK_CHECK_INTERVAL)
            if not self._running:
                break
            for pos in self.positions.all():
                await self._check_risk(pos.symbol)

    async def _sync_loop(self) -> None:
        while self._sync_running:
            await asyncio.sleep(_SYNC_INTERVAL)
            if not self._sync_running:
                break
            try:
                await self.sync_positions()
                now = time.monotonic()
                if now - self._last_unfilled_cancel >= _UNFILLED_CANCEL_INTERVAL:
                    cancelled = await self._broker.cancel_all_orders()
                    if cancelled > 0:
                        logger.info("engine.unfilled_cancelled", count=cancelled)
                    self._last_unfilled_cancel = now
                if self._bus:
                    await self._bus.emit("position.updated", {})
            except Exception as e:
                logger.warning("engine.sync_loop_failed", error=str(e))

    async def on_tick(self, symbol: str, price: Decimal, volume: int) -> None:
        if not self._running:
            return

        self.positions.update_price(symbol, price)
        if self._bus:
            await self._bus.emit(
                "tick.received",
                {"symbol": symbol, "price": str(price), "volume": volume},
            )
            pos = self.positions.get(symbol)
            if pos:
                await self._bus.emit(
                    "position.updated", {"symbol": symbol, "current_price": str(price)}
                )
        await self._check_risk(symbol)
        await self._check_market_close()

        for strategy in self._registry.enabled():
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

        for strategy in self._registry.enabled():
            signal = await strategy.on_orderbook(symbol, asks, bids)
            if signal is not None:
                await self._process_signal(signal)

    async def on_fill_notice(self, data: dict[str, Any]) -> None:
        symbol = data["symbol"]
        if data.get("is_rejected"):
            self._rejected_symbols[symbol] = time.monotonic()
            logger.warning(
                "engine.ws_order_rejected", symbol=symbol, order_no=data.get("order_no")
            )
            return
        if not data.get("is_fill"):
            return

        side = data["side"]
        qty = data["quantity"]
        price = Decimal(str(data["price"]))
        strategy = "ws_fill"

        if side == "buy":
            pos = self.positions.get(symbol)
            if pos:
                strategy = pos.strategy
                total_qty = pos.quantity + qty
                pos.avg_price = (pos.avg_price * pos.quantity + price * qty) / total_qty
                pos.quantity = total_qty
                pos.current_price = price
            else:
                self.positions._positions[symbol] = Position(
                    symbol=symbol,
                    side=Side.BUY,
                    quantity=qty,
                    avg_price=price,
                    current_price=price,
                    strategy="ws_fill",
                )
            logger.info("engine.ws_fill_buy", symbol=symbol, qty=qty, price=str(price))
        else:
            pos = self.positions.get(symbol)
            if pos:
                strategy = pos.strategy
                remaining = pos.quantity - qty
                if remaining <= 0:
                    self.positions.remove(symbol)
                    self._closed_symbols[symbol] = time.monotonic()
                else:
                    pos.quantity = remaining
                    pos.current_price = price
            logger.info("engine.ws_fill_sell", symbol=symbol, qty=qty, price=str(price))

        if self._bus:
            await self._bus.emit(
                "order.filled",
                {
                    "symbol": symbol,
                    "side": side,
                    "price": str(price),
                    "qty": qty,
                    "strategy": strategy,
                },
            )

    async def on_vi_event(self, symbol: str, triggered: bool) -> None:
        if triggered:
            self._untradeable.add(symbol)
            pos = self.positions.get(symbol)
            if pos:
                logger.warning("engine.vi_hold", symbol=symbol)
        else:
            self._untradeable.discard(symbol)

    async def _process_signal(self, signal: Signal) -> None:
        if not self._running:
            return
        if signal.confidence < _MIN_CONFIDENCE:
            return
        if self._orders.has_pending_for(signal.symbol):
            return

        if signal.symbol in self._untradeable:
            return

        if signal.side == Side.BUY:
            closed_at = self._closed_symbols.get(signal.symbol)
            if closed_at and time.monotonic() - closed_at < _CLOSE_COOLDOWN:
                return
            rejected_at = self._rejected_symbols.get(signal.symbol)
            if rejected_at and time.monotonic() - rejected_at < _REJECTED_COOLDOWN:
                return
            now_kst = datetime.now(_KST).time()
            if _CUTOFF_BUY <= now_kst <= _MARKET_END:
                logger.info("engine.buy_blocked_market_closing", symbol=signal.symbol)
                return
            if self.positions.get(signal.symbol) is not None:
                return
            if len(self.positions.all()) >= self._risk.max_open_positions:
                return

        balance = await self.get_cached_balance()
        available = balance - self._pending_buy_cost
        if available <= 0 and signal.side == Side.BUY:
            return
        positions_value = sum(
            p.current_price * p.quantity for p in self.positions.all()
        )
        total_asset = balance + positions_value
        qty = self._risk.get_max_position_size(
            signal.symbol, available, signal.price, total_asset=total_asset,
        )

        sell_pos: Position | None = None
        if signal.side == Side.SELL:
            pos = self.positions.get(signal.symbol)
            if pos is None or pos.quantity == 0:
                return
            if pos.strategy != "synced" and pos.strategy != signal.strategy:
                return
            gain = (pos.current_price - pos.avg_price) / pos.avg_price if pos.avg_price > 0 else Decimal("0")
            if Decimal("0") <= gain < _MIN_PROFIT_RATIO:
                return
            sell_pos = pos
            qty = pos.quantity

        if qty <= 0:
            return

        order = self._orders.signal_to_order(signal, qty)

        if signal.side == Side.BUY and not self._risk.validate_order(order, available):
            return

        if self._bus:
            await self._bus.emit(
                "signal.generated",
                {
                    "symbol": signal.symbol,
                    "side": signal.side.value,
                    "strategy": signal.strategy,
                    "price": str(signal.price),
                    "confidence": signal.confidence,
                },
            )

        buy_cost = order.price * order.quantity if signal.side == Side.BUY else Decimal("0")
        self._pending_buy_cost += buy_cost
        result = await self._orders.submit(order)
        self._pending_buy_cost -= buy_cost
        if result.status == OrderStatus.REJECTED:
            if "매매불가" in result.reject_reason or "잔고" in result.reject_reason:
                self._untradeable.add(signal.symbol)
                logger.warning("engine.untradeable", symbol=signal.symbol)
            else:
                self._rejected_symbols[signal.symbol] = time.monotonic()
            if signal.side == Side.SELL:
                self.positions.remove(signal.symbol)
                logger.info("engine.stale_position_removed", symbol=signal.symbol)
            return
        if result.status == OrderStatus.FILLED:
            self.positions.update_on_fill(result)
            if self._bus:
                await self._bus.emit(
                    "order.filled",
                    {
                        "symbol": result.symbol,
                        "side": result.side.value,
                        "price": str(result.price),
                        "qty": result.quantity,
                        "strategy": result.strategy,
                    },
                )
                if result.side == Side.BUY:
                    if self._trade_repo:
                        try:
                            self._trade_repo.save_position_open(result.symbol, result.strategy)
                        except Exception:
                            pass
                    await self._bus.emit(
                        "position.opened",
                        {
                            "symbol": result.symbol,
                            "qty": result.quantity,
                            "avg_price": str(result.price),
                            "strategy": result.strategy,
                        },
                    )
                elif result.side == Side.SELL:
                    self._closed_symbols[result.symbol] = time.monotonic()
                    if sell_pos:
                        pnl = (result.price - sell_pos.avg_price) * result.quantity
                        self._performance.record_trade(result.strategy, pnl, symbol=result.symbol)
                    if self._trade_repo:
                        try:
                            self._trade_repo.close_position(result.symbol)
                        except Exception:
                            pass
                    await self._bus.emit(
                        "position.closed",
                        {
                            "symbol": result.symbol,
                            "qty": result.quantity,
                            "reason": "signal",
                        },
                    )

    async def _check_market_close(self) -> None:
        now_kst = datetime.now(_KST).time()
        if now_kst < _CUTOFF_CLOSE or now_kst > _MARKET_END:
            self._market_close_done = False
            return
        if self._market_close_done:
            return

        from scalpy.config import settings
        if not settings.get("trading.market_close_liquidate", True):
            self._market_close_done = True
            logger.info("engine.market_close_hold", count=len(self.positions.all()))
            return

        positions = list(self.positions.all())
        if not positions:
            return
        logger.warning("engine.market_close_liquidation", count=len(positions))
        for pos in positions:
            await self._force_close(pos, reason="market_close")
        self._running = False
        self.stop_background_loops()
        self._market_close_done = True
        logger.info("engine.auto_stopped_market_close")
        if self._bus:
            await self._bus.emit("engine.stopped")

    def _get_strategy_risk(self, strategy_name: str) -> tuple[Decimal | None, Decimal | None]:
        strategy = self._registry.get(strategy_name)
        if strategy is None:
            return None, None
        sl = Decimal(str(strategy.stop_loss_ratio)) if strategy.stop_loss_ratio is not None else None
        tp = Decimal(str(strategy.take_profit_ratio)) if strategy.take_profit_ratio is not None else None
        return sl, tp

    async def _check_risk(self, symbol: str) -> None:
        pos = self.positions.get(symbol)
        if pos is None:
            return

        sl_ratio, tp_ratio = self._get_strategy_risk(pos.strategy)

        if self._risk.check_stop_loss(pos, sl_ratio):
            await self._force_close(pos, reason="stop_loss")
        elif self._risk.check_take_profit(pos, tp_ratio):
            await self._force_close(pos, reason="take_profit")
        elif self._risk.check_stagnation(pos):
            await self._force_close(pos, reason="stagnation")

    async def _force_close(self, pos: Position, reason: str = "") -> None:
        from scalpy.config import settings
        if reason == "stop_loss" or not self._trade_repo:
            splits = 1
        else:
            splits = max(1, settings.get("trading.force_close_splits", 1))
        remaining = pos.quantity
        total_pnl = Decimal("0")
        total_sold = 0

        for i in range(splits):
            if remaining <= 0:
                break
            chunk = remaining // (splits - i)
            if chunk <= 0:
                continue

            signal = Signal(
                symbol=pos.symbol,
                side=Side.SELL,
                strategy=pos.strategy,
                price=pos.current_price,
                quantity=chunk,
                confidence=1.0,
                timestamp=datetime.now(),
            )
            order = self._orders.signal_to_order(signal, chunk)
            result = await self._orders.submit(order)

            if result.status == OrderStatus.REJECTED:
                if total_sold == 0:
                    self.positions.remove(pos.symbol)
                if "잔고" in result.reject_reason or "매매불가" in result.reject_reason:
                    self._untradeable.add(pos.symbol)
                    logger.warning(
                        "engine.ghost_position_blocked", symbol=pos.symbol, reason=reason
                    )
                else:
                    self._rejected_symbols[pos.symbol] = time.monotonic()
                    logger.warning(
                        "engine.force_close_rejected", symbol=pos.symbol, reason=reason
                    )
                break

            if result.status == OrderStatus.FILLED:
                self.positions.update_on_fill(result)
                total_pnl += (result.price - pos.avg_price) * result.quantity
                total_sold += result.quantity
                remaining -= result.quantity
                if self._bus:
                    await self._bus.emit(
                        "order.filled",
                        {
                            "symbol": result.symbol,
                            "side": result.side.value,
                            "price": str(result.price),
                            "qty": result.quantity,
                            "strategy": reason or result.strategy,
                        },
                    )

            if remaining > 0 and i < splits - 1:
                await asyncio.sleep(_SPLIT_SELL_DELAY)

        if total_sold > 0:
            self._closed_symbols[pos.symbol] = time.monotonic()
            self._performance.record_trade(pos.strategy, total_pnl, symbol=pos.symbol)
            if self._trade_repo:
                try:
                    self._trade_repo.close_position(pos.symbol)
                except Exception:
                    pass
            logger.info(
                "engine.position_force_closed",
                symbol=pos.symbol, reason=reason,
                splits=splits, sold=total_sold,
            )
            if self._bus:
                await self._bus.emit(
                    "signal.generated",
                    {
                        "symbol": pos.symbol,
                        "side": "sell",
                        "strategy": reason or pos.strategy,
                        "price": str(pos.current_price),
                        "confidence": 1.0,
                    },
                )
                await self._bus.emit(
                    "position.closed",
                    {
                        "symbol": pos.symbol,
                        "qty": total_sold,
                        "reason": reason,
                    },
                )
