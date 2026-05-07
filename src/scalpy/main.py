import asyncio
import contextlib
import signal

import structlog

from scalpy.broker.mock import MockBroker
from scalpy.config import settings
from scalpy.data.stream import MarketDataStream
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
        if s.name in enabled:
            registry.register(s)

    strategy_config = {}
    for name in enabled:
        params = settings.get(f"strategies.{name}", {})
        if params:
            strategy_config[name] = dict(params)
    if strategy_config:
        registry.configure_all(strategy_config)

    return registry


def build_engine(registry: StrategyRegistry) -> TradingEngine:
    broker = MockBroker()
    trading = settings.get("trading", {})
    risk = RiskManager(
        stop_loss_ratio=trading.get("stop_loss_ratio", 0.02),
        take_profit_ratio=trading.get("take_profit_ratio", 0.03),
        max_position_size=trading.get("max_position_size", 100),
    )
    return TradingEngine(broker, registry, risk)


async def run() -> None:
    registry = build_registry()
    engine = build_engine(registry)
    stream = MarketDataStream()

    stream.on_tick(engine.on_tick)
    stream.on_orderbook(engine.on_orderbook)

    symbols = settings.get("trading.symbols", ["005930"])

    await engine.start()
    await stream.start(symbols)

    logger.info(
        "scalpy.started",
        mock=settings.get("mock", True),
        symbols=symbols,
        strategies=[s.name for s in registry.all()],
    )

    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("scalpy.shutdown_requested")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    await stop_event.wait()

    await stream.stop()
    await engine.stop()
    logger.info("scalpy.stopped")


def main() -> None:
    logger.info("scalpy.initializing", version="0.1.0")
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run())


if __name__ == "__main__":
    main()
