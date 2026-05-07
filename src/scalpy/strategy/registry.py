from typing import Any

import structlog

from scalpy.strategy.base import BaseStrategy

logger = structlog.get_logger()


class StrategyRegistry:
    def __init__(self) -> None:
        self._strategies: dict[str, BaseStrategy] = {}

    def register(self, strategy: BaseStrategy) -> None:
        self._strategies[strategy.name] = strategy
        logger.info("strategy.registered", name=strategy.name)

    def get(self, name: str) -> BaseStrategy | None:
        return self._strategies.get(name)

    def all(self) -> list[BaseStrategy]:
        return list(self._strategies.values())

    def configure_all(self, config: dict[str, dict[str, Any]]) -> None:
        for name, params in config.items():
            strategy = self.get(name)
            if strategy:
                strategy.configure(params)
