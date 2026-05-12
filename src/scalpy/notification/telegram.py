from typing import Any

import httpx
import structlog

from scalpy.events.bus import EventBus

logger = structlog.get_logger()


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str) -> None:
        self._url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self._chat_id = chat_id
        self._client = httpx.AsyncClient(timeout=10)

    def register_handlers(self, bus: EventBus) -> None:
        bus.subscribe("order.filled", self._on_order_filled)
        bus.subscribe("position.closed", self._on_position_closed)
        bus.subscribe("engine.started", self._on_engine_started)
        bus.subscribe("engine.stopped", self._on_engine_stopped)

    async def _send(self, text: str) -> None:
        try:
            await self._client.post(self._url, json={
                "chat_id": self._chat_id,
                "text": text,
                "parse_mode": "HTML",
            })
        except Exception as e:
            logger.warning("telegram.send_failed", error=str(e))

    async def _on_order_filled(self, data: dict[str, Any]) -> None:
        side = data.get("side", "")
        icon = "\U0001f4c8" if side == "buy" else "\U0001f4c9"
        side_kr = "매수" if side == "buy" else "매도"
        text = (
            f"{icon} <b>{side_kr} 체결</b>\n"
            f"종목: {data.get('symbol', '')}\n"
            f"가격: {data.get('price', '')}원 x {data.get('qty', '')}주\n"
            f"전략: {data.get('strategy', '')}"
        )
        await self._send(text)

    async def _on_position_closed(self, data: dict[str, Any]) -> None:
        pnl = data.get("pnl", 0)
        icon = "\U0001f4b0" if float(str(pnl)) >= 0 else "\U0001f53b"
        reason = data.get("reason", "")
        reason_kr = {"stop_loss": "손절", "take_profit": "익절"}.get(reason, reason)
        text = (
            f"{icon} <b>{reason_kr} 청산</b>\n"
            f"종목: {data.get('symbol', '')}\n"
            f"손익: {pnl}원"
        )
        await self._send(text)

    async def _on_engine_started(self, data: dict[str, Any]) -> None:
        await self._send("✅ <b>Scalpy 엔진 시작</b>")

    async def _on_engine_stopped(self, data: dict[str, Any]) -> None:
        await self._send("⛔ <b>Scalpy 엔진 정지</b>")
