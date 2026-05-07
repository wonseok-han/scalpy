import asyncio
from collections import defaultdict
from collections.abc import Callable
from typing import Any

import structlog

logger = structlog.get_logger()

Handler = Callable[..., Any]


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: Handler) -> None:
        self._handlers[event_type].append(handler)

    def unsubscribe(self, event_type: str, handler: Handler) -> None:
        self._handlers[event_type].remove(handler)

    async def emit(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        for handler in self._handlers.get(event_type, []):
            try:
                result = handler(data or {})
                if asyncio.iscoroutine(result):
                    asyncio.create_task(result)
            except Exception as e:
                logger.error("event_bus.handler_error", event=event_type, error=str(e))
