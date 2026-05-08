import asyncio
import contextlib
import signal

import structlog

from scalpy.broker.base import BaseBroker
from scalpy.broker.mock import MockBroker
from scalpy.config import settings
from scalpy.data.stream import MarketDataStream
from scalpy.events import EventBus
from scalpy.strategy.bollinger import BollingerStrategy
from scalpy.strategy.ma_cross import MACrossStrategy
from scalpy.strategy.orderbook import OrderbookStrategy
from scalpy.strategy.registry import StrategyRegistry
from scalpy.strategy.rsi import RSIStrategy
from scalpy.strategy.vwap import VWAPStrategy
from scalpy.trading.engine import TradingEngine
from scalpy.trading.risk import RiskManager

logger = structlog.get_logger()


def build_registry() -> StrategyRegistry:
    registry = StrategyRegistry()
    all_strategies = [
        MACrossStrategy(),
        BollingerStrategy(),
        RSIStrategy(),
        OrderbookStrategy(),
        VWAPStrategy(),
    ]
    enabled = settings.get("strategies.enabled", [s.name for s in all_strategies])
    for s in all_strategies:
        registry.register(s)
        if s.name not in enabled:
            s.enabled = False

    strategy_config = {}
    for s in all_strategies:
        params = settings.get(f"strategies.{s.name}", {})
        if params:
            strategy_config[s.name] = dict(params)
    if strategy_config:
        registry.configure_all(strategy_config)

    return registry


def build_broker() -> BaseBroker:
    mock = settings.get("mock", True)
    app_key = settings.get("kis_app_key", "")

    if not app_key:
        return MockBroker()

    from scalpy.broker.kis import KISBroker

    return KISBroker(
        app_key=app_key,
        app_secret=settings.get("kis_app_secret", ""),
        account_no=settings.get("kis_account_no", ""),
        mock=mock,
    )


def build_engine(registry: StrategyRegistry) -> tuple[TradingEngine, BaseBroker]:
    broker = build_broker()
    trading = settings.get("trading", {})
    risk = RiskManager(
        stop_loss_ratio=trading.get("stop_loss_ratio", 0.02),
        take_profit_ratio=trading.get("take_profit_ratio", 0.03),
        max_position_size=trading.get("max_position_size", 100),
        max_open_positions=trading.get("max_open_positions", 3),
    )
    return TradingEngine(broker, registry, risk), broker


async def _screening_loop(
    screener: "StockScreener",
    engine: TradingEngine,
    stream: MarketDataStream,
    interval_minutes: int,
    stop_event: asyncio.Event,
) -> None:
    from scalpy.screening import StockScreener  # noqa: F811

    while not stop_event.is_set():
        try:
            held = [p.symbol for p in engine.positions.all()]
            new_symbols = await screener.scan(held_symbols=held)
            if new_symbols:
                await stream.update_subscriptions(new_symbols)
                await engine.update_symbols(new_symbols)
        except Exception as e:
            logger.error("screening_loop.error", error=str(e))

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_minutes * 60)
            break
        except asyncio.TimeoutError:
            pass


async def _start_trading(
    engine: TradingEngine,
    broker: BaseBroker,
    stream: MarketDataStream,
    bus: EventBus,
    stop_event: asyncio.Event,
) -> None:
    engine._running = True
    if bus:
        await bus.emit("engine.started")

    screening_cfg = settings.get("screening", {})
    screening_enabled = screening_cfg.get("enabled", False)

    if screening_enabled:
        from scalpy.screening import StockScreener

        screener = StockScreener(
            broker=broker,
            max_stocks=screening_cfg.get("max_stocks", 5),
            min_change_rate=screening_cfg.get("min_change_rate", 2.0),
            min_volume=screening_cfg.get("min_volume", 100_000),
        )
        held = [p.symbol for p in engine.positions.all()]
        symbols = await screener.scan(held_symbols=held)
        if not symbols:
            symbols = settings.get("trading.symbols", ["005930"])
        await stream.start(symbols)

        interval = screening_cfg.get("interval_minutes", 30)
        asyncio.create_task(_screening_loop(screener, engine, stream, interval, stop_event))
        logger.info("scalpy.screening_enabled", interval_minutes=interval)
        if bus:
            await bus.emit("screening.completed", {"symbols": symbols})
    else:
        symbols = settings.get("trading.symbols", ["005930"])
        await stream.start(symbols)

    logger.info("scalpy.trading_started", symbols=symbols)


async def run() -> None:
    registry = build_registry()
    engine, broker = build_engine(registry)
    mock = settings.get("mock", True)
    stream = MarketDataStream(
        app_key=settings.get("kis_app_key", ""),
        app_secret=settings.get("kis_app_secret", ""),
        mock=mock,
    )

    stream.on_tick(engine.on_tick)
    stream.on_orderbook(engine.on_orderbook)

    bus = EventBus()
    engine.set_event_bus(bus)

    await broker.connect()
    await engine.sync_positions()
    await engine.get_cached_balance()

    stop_event = asyncio.Event()
    dashboard_task = None

    trading_cfg = settings.get("trading", {})
    auto_start = trading_cfg.get("auto_start", True)

    # Screening (build reference for dashboard regardless of auto_start)
    screening_cfg = settings.get("screening", {})
    screening_enabled = screening_cfg.get("enabled", False)
    screener_ref = None
    if screening_enabled:
        from scalpy.screening import StockScreener

        screener_ref = StockScreener(
            broker=broker,
            max_stocks=screening_cfg.get("max_stocks", 5),
            min_change_rate=screening_cfg.get("min_change_rate", 2.0),
            min_volume=screening_cfg.get("min_volume", 100_000),
        )

    # Dashboard
    dashboard_cfg = settings.get("dashboard", {})
    if dashboard_cfg.get("enabled", False):
        from scalpy.dashboard.server import start_dashboard_server
        from scalpy.dashboard.state import DashboardState

        dash_state = DashboardState()
        dash_state.register_handlers(bus)
        synced_names = getattr(broker, "_position_names", {})
        if synced_names:
            dash_state.symbol_names.update(synced_names)
        dashboard_task = start_dashboard_server(
            dash_state, bus, engine,
            host=dashboard_cfg.get("host", "0.0.0.0"),
            port=dashboard_cfg.get("port", 8080),
            screener=screener_ref, stream=stream,
            registry=registry,
        )

    # Telegram
    telegram_cfg = settings.get("telegram", {})
    if telegram_cfg.get("enabled", False) and telegram_cfg.get("bot_token"):
        from scalpy.notification import TelegramNotifier

        notifier = TelegramNotifier(
            bot_token=telegram_cfg["bot_token"],
            chat_id=telegram_cfg.get("chat_id", ""),
        )
        notifier.register_handlers(bus)
        logger.info("scalpy.telegram_enabled")

    if auto_start:
        await _start_trading(engine, broker, stream, bus, stop_event)
    else:
        logger.info("scalpy.waiting_for_manual_start")

    logger.info(
        "scalpy.started",
        mock=mock,
        auto_start=auto_start,
        strategies=[s.name for s in registry.all()],
        screening=screening_enabled,
        dashboard=dashboard_cfg.get("enabled", False),
    )

    def _signal_handler() -> None:
        logger.info("scalpy.shutdown_requested")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    await stop_event.wait()

    async def _shutdown() -> None:
        if dashboard_task is not None:
            sse = getattr(dashboard_task, '_sse', None)
            if sse:
                sse.stop()
            server = getattr(dashboard_task, '_uvicorn_server', None)
            if server:
                server.should_exit = True
                try:
                    await asyncio.wait_for(dashboard_task, timeout=3)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    dashboard_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await dashboard_task

        await stream.stop()
        await engine.stop()

    try:
        await asyncio.wait_for(_shutdown(), timeout=5)
    except asyncio.TimeoutError:
        logger.warning("scalpy.shutdown_timeout")

    for task in asyncio.all_tasks():
        if task is not asyncio.current_task() and not task.done():
            task.cancel()

    logger.info("scalpy.stopped")


def main() -> None:
    logger.info("scalpy.initializing", version="0.1.0")
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run())


if __name__ == "__main__":
    main()
