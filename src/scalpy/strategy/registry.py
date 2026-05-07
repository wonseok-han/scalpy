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

    def enabled(self) -> list[BaseStrategy]:
        return [s for s in self._strategies.values() if s.enabled]

    def toggle(self, name: str) -> bool | None:
        s = self._strategies.get(name)
        if s is None:
            return None
        s.enabled = not s.enabled
        logger.info("strategy.toggled", name=name, enabled=s.enabled)
        return s.enabled

    def set_enabled(self, name: str, enabled: bool) -> bool | None:
        s = self._strategies.get(name)
        if s is None:
            return None
        s.enabled = enabled
        logger.info("strategy.set_enabled", name=name, enabled=enabled)
        return enabled

    def configure_all(self, config: dict[str, dict[str, Any]]) -> None:
        for name, params in config.items():
            strategy = self.get(name)
            if strategy:
                strategy.configure(params)
