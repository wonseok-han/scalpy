import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any

from scalpy.events.bus import EventBus

SSE_EVENTS = [
    "tick.received", "order.filled", "signal.generated",
    "position.opened", "position.closed", "position.updated",
    "screening.completed", "engine.started", "engine.stopped",
]

_EVENT_MAP = {
    "tick.received": "tick",
    "order.filled": "order",
    "signal.generated": "signal",
    "position.opened": "position",
    "position.closed": "position",
    "position.updated": "position",
    "screening.completed": "screening",
    "engine.started": "engine",
    "engine.stopped": "engine",
}


class SSEManager:
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._queues: list[asyncio.Queue[str]] = []
        for event in SSE_EVENTS:
            bus.subscribe(event, self._make_handler(event))

    def _make_handler(self, event_type: str) -> Any:
        sse_name = _EVENT_MAP.get(event_type, event_type)

        def handler(data: dict[str, Any]) -> None:
            safe = _serialize(data)
            msg = f"event: {sse_name}\ndata: {json.dumps(safe)}\n\n"
            for q in self._queues:
                q.put_nowait(msg)

        return handler

    def broadcast(self, event_name: str, data: dict[str, Any]) -> None:
        safe = _serialize(data)
        msg = f"event: {event_name}\ndata: {json.dumps(safe)}\n\n"
        for q in self._queues:
            q.put_nowait(msg)

    async def stream(self) -> AsyncGenerator[str, None]:
        q: asyncio.Queue[str] = asyncio.Queue()
        self._queues.append(q)
        try:
            while True:
                msg = await q.get()
                yield msg
        finally:
            self._queues.remove(q)


def _serialize(data: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in data.items():
        if hasattr(v, "__str__") and not isinstance(v, (str, int, float, bool, list, dict)):
            out[k] = str(v)
        else:
            out[k] = v
    return out
