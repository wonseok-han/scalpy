import asyncio
import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import requests
import structlog
import websockets

logger = structlog.get_logger()

TickCallback = Callable[[str, Decimal, int], Any]
OrderbookCallback = Callable[[str, list[tuple[Decimal, int]], list[tuple[Decimal, int]]], Any]

_WS_URLS = {
    "virtual": "ws://ops.koreainvestment.com:31000",
    "real": "ws://ops.koreainvestment.com:21000",
}
_REST_URLS = {
    "virtual": "https://openapivts.koreainvestment.com:29443",
    "real": "https://openapi.koreainvestment.com:9443",
}


def _get_approval_key(app_key: str, app_secret: str, *, mock: bool = True) -> str:
    url = _REST_URLS["virtual" if mock else "real"]
    resp = requests.post(
        f"{url}/oauth2/Approval",
        headers={"content-type": "application/json"},
        json={
            "grant_type": "client_credentials",
            "appkey": app_key,
            "secretkey": app_secret,
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["approval_key"]


def _subscribe_msg(approval_key: str, tr_id: str, tr_key: str) -> str:
    return json.dumps({
        "header": {
            "approval_key": approval_key,
            "custtype": "P",
            "tr_type": "1",
            "content-type": "utf-8",
        },
        "body": {"input": {"tr_id": tr_id, "tr_key": tr_key}},
    })


def _unsubscribe_msg(approval_key: str, tr_id: str, tr_key: str) -> str:
    return json.dumps({
        "header": {
            "approval_key": approval_key,
            "custtype": "P",
            "tr_type": "2",
            "content-type": "utf-8",
        },
        "body": {"input": {"tr_id": tr_id, "tr_key": tr_key}},
    })


class MarketDataStream:
    def __init__(
        self,
        app_key: str = "",
        app_secret: str = "",
        *,
        mock: bool = True,
    ) -> None:
        self._app_key = app_key
        self._app_secret = app_secret
        self._mock = mock
        self._tick_callbacks: list[TickCallback] = []
        self._orderbook_callbacks: list[OrderbookCallback] = []
        self._running = False
        self._ws: Any = None
        self._subscribed: set[str] = set()
        self._approval_key: str = ""

    def on_tick(self, callback: TickCallback) -> None:
        self._tick_callbacks.append(callback)

    def on_orderbook(self, callback: OrderbookCallback) -> None:
        self._orderbook_callbacks.append(callback)

    async def emit_tick(self, symbol: str, price: Decimal, volume: int) -> None:
        for cb in self._tick_callbacks:
            result = cb(symbol, price, volume)
            if asyncio.iscoroutine(result):
                await result

    async def emit_orderbook(
        self,
        symbol: str,
        asks: list[tuple[Decimal, int]],
        bids: list[tuple[Decimal, int]],
    ) -> None:
        for cb in self._orderbook_callbacks:
            result = cb(symbol, asks, bids)
            if asyncio.iscoroutine(result):
                await result

    async def start(self, symbols: list[str]) -> None:
        if not self._app_key:
            self._running = True
            self._subscribed = set(symbols)
            logger.info("market_data_stream.started_local", symbols=symbols)
            return

        self._approval_key = _get_approval_key(self._app_key, self._app_secret, mock=self._mock)
        ws_url = _WS_URLS["virtual" if self._mock else "real"]

        self._ws = await websockets.connect(ws_url, ping_interval=None)
        self._running = True

        for sym in symbols:
            await self._ws.send(_subscribe_msg(self._approval_key, "H0STCNT0", sym))
            await self._ws.send(_subscribe_msg(self._approval_key, "H0STASP0", sym))

        self._subscribed = set(symbols)
        logger.info("market_data_stream.started", symbols=symbols, mode="websocket")
        asyncio.create_task(self._recv_loop())

    async def _recv_loop(self) -> None:
        reconnect_delay = 1
        while self._running:
            try:
                async for raw in self._ws:
                    if not self._running:
                        return
                    await self._handle_message(raw)
                    reconnect_delay = 1
            except websockets.ConnectionClosed:
                logger.warning("market_data_stream.disconnected")
            except Exception as e:
                logger.error("market_data_stream.error", error=str(e))

            if not self._running:
                return

            delay = min(reconnect_delay, 30)
            logger.info("market_data_stream.reconnecting", delay=delay)
            await asyncio.sleep(delay)
            reconnect_delay = min(reconnect_delay * 2, 30)

            try:
                ws_url = _WS_URLS["virtual" if self._mock else "real"]
                self._ws = await websockets.connect(ws_url, ping_interval=None)
                for sym in self._subscribed:
                    await self._ws.send(_subscribe_msg(self._approval_key, "H0STCNT0", sym))
                    await self._ws.send(_subscribe_msg(self._approval_key, "H0STASP0", sym))
                    await asyncio.sleep(0.05)
                logger.info("market_data_stream.reconnected", symbols=len(self._subscribed))
            except Exception as e:
                logger.error("market_data_stream.reconnect_failed", error=str(e))

    async def _handle_message(self, raw: str) -> None:
        if not self._running:
            return
        if raw[0] in ("0", "1"):
            parts = raw.split("|")
            tr_id = parts[1]
            data = parts[3]

            if tr_id == "H0STCNT0":
                await self._on_execution(data)
            elif tr_id == "H0STASP0":
                await self._on_orderbook_data(data)
        else:
            msg = json.loads(raw)
            tr_id = msg.get("header", {}).get("tr_id", "")
            if tr_id == "PINGPONG":
                await self._ws.send(raw)
            else:
                rt_cd = msg.get("body", {}).get("rt_cd", "")
                msg1 = msg.get("body", {}).get("msg1", "")
                if rt_cd == "0":
                    logger.info("market_data_stream.subscribed", tr_id=tr_id, msg=msg1)
                else:
                    logger.warning("market_data_stream.sub_error", tr_id=tr_id, msg=msg1)

    async def _on_execution(self, data: str) -> None:
        fields = data.split("^")
        symbol = fields[0]
        price = Decimal(fields[2])
        volume = int(fields[12])
        await self.emit_tick(symbol, price, volume)

    async def _on_orderbook_data(self, data: str) -> None:
        fields = data.split("^")
        symbol = fields[0]
        asks = [
            (Decimal(fields[3 + i]), int(fields[23 + i])) for i in range(10)
        ]
        bids = [
            (Decimal(fields[13 + i]), int(fields[33 + i])) for i in range(10)
        ]
        await self.emit_orderbook(symbol, asks, bids)

    async def update_subscriptions(self, new_symbols: list[str]) -> None:
        new_set = set(new_symbols)
        to_remove = self._subscribed - new_set
        to_add = new_set - self._subscribed

        if not to_remove and not to_add:
            return

        if self._ws and self._approval_key:
            for sym in to_remove:
                try:
                    await self._ws.send(_unsubscribe_msg(self._approval_key, "H0STCNT0", sym))
                    await self._ws.send(_unsubscribe_msg(self._approval_key, "H0STASP0", sym))
                except Exception as e:
                    logger.warning("market_data_stream.unsubscribe_failed", symbol=sym, error=str(e))
                await asyncio.sleep(0.05)

            for sym in to_add:
                try:
                    await self._ws.send(_subscribe_msg(self._approval_key, "H0STCNT0", sym))
                    await self._ws.send(_subscribe_msg(self._approval_key, "H0STASP0", sym))
                except Exception as e:
                    logger.warning("market_data_stream.subscribe_failed", symbol=sym, error=str(e))
                await asyncio.sleep(0.05)

        self._subscribed = new_set
        logger.info(
            "market_data_stream.subscriptions_updated",
            removed=list(to_remove),
            added=list(to_add),
            total=len(new_set),
        )

    async def stop(self) -> None:
        self._running = False
        if self._ws:
            try:
                await asyncio.wait_for(self._ws.close(), timeout=3)
            except (asyncio.TimeoutError, Exception):
                pass
            self._ws = None
        logger.info("market_data_stream.stopped")

    @property
    def is_running(self) -> bool:
        return self._running
