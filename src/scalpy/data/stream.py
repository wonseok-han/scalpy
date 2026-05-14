import asyncio
import contextlib
import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import requests
import structlog
import websockets

from scalpy.config import settings

logger = structlog.get_logger()

TickCallback = Callable[[str, Decimal, int], Any]
OrderbookCallback = Callable[[str, list[tuple[Decimal, int]], list[tuple[Decimal, int]]], Any]
FillCallback = Callable[[dict[str, Any]], Any]
VICallback = Callable[[str, bool], Any]

def _get_ws_url(mock: bool) -> str:
    key = "virtual" if mock else "real"
    cfg = settings.get("kis_api.ws_urls", {})
    url = cfg.get(key)
    if not url:
        raise RuntimeError(f"kis_api.ws_urls.{key} 설정이 필요합니다 (settings.toml)")
    return url


def _get_rest_url(mock: bool) -> str:
    key = "virtual" if mock else "real"
    cfg = settings.get("kis_api.rest_urls", {})
    url = cfg.get(key)
    if not url:
        raise RuntimeError(f"kis_api.rest_urls.{key} 설정이 필요합니다 (settings.toml)")
    return url


def _get_approval_key(app_key: str, app_secret: str, *, mock: bool = True) -> str:
    url = _get_rest_url(mock)
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
        hts_id: str = "",
    ) -> None:
        self._app_key = app_key
        self._app_secret = app_secret
        self._mock = mock
        self._hts_id = hts_id
        self._tick_callbacks: list[TickCallback] = []
        self._orderbook_callbacks: list[OrderbookCallback] = []
        self._fill_callbacks: list[FillCallback] = []
        self._vi_callbacks: list[VICallback] = []
        self._running = False
        self._ws: Any = None
        self._subscribed: set[str] = set()
        self._approval_key: str = ""
        self._recv_task: asyncio.Task[None] | None = None
        self._stopping = False

    def on_tick(self, callback: TickCallback) -> None:
        self._tick_callbacks.append(callback)

    def on_orderbook(self, callback: OrderbookCallback) -> None:
        self._orderbook_callbacks.append(callback)

    def on_fill(self, callback: FillCallback) -> None:
        self._fill_callbacks.append(callback)

    def on_vi(self, callback: VICallback) -> None:
        self._vi_callbacks.append(callback)

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

    async def _emit_fill(self, data: dict[str, Any]) -> None:
        for cb in self._fill_callbacks:
            result = cb(data)
            if asyncio.iscoroutine(result):
                await result

    async def _emit_vi(self, symbol: str, triggered: bool) -> None:
        for cb in self._vi_callbacks:
            result = cb(symbol, triggered)
            if asyncio.iscoroutine(result):
                await result

    async def start(self, symbols: list[str]) -> None:
        await self._cleanup_recv_task()
        if self._ws:
            try:
                await asyncio.wait_for(self._ws.close(), timeout=2)
            except (asyncio.TimeoutError, Exception):
                pass
            self._ws = None
        self._subscribed.clear()

        if not self._app_key:
            from scalpy.data.simulator import MarketSimulator

            self._running = True
            self._subscribed = set(symbols)
            sim_cfg = settings.get("simulator", {})
            self._simulator = MarketSimulator(
                self,
                symbols,
                interval=sim_cfg.get("interval", 0.5),
                volatility=sim_cfg.get("volatility", 0.002),
            )
            await self._simulator.start()
            logger.info("market_data_stream.started_simulator", symbols=symbols)
            return

        self._approval_key = _get_approval_key(self._app_key, self._app_secret, mock=self._mock)
        ws_url = _get_ws_url(self._mock)

        self._ws = await websockets.connect(ws_url, ping_interval=None)
        self._running = True

        if self._hts_id:
            cni_tr = "H0STCNI9" if self._mock else "H0STCNI0"
            await self._ws.send(_subscribe_msg(self._approval_key, cni_tr, self._hts_id))
            await asyncio.sleep(0.1)
            logger.info("market_data_stream.fill_subscribed", tr_id=cni_tr)

        for sym in symbols:
            await self._ws.send(_subscribe_msg(self._approval_key, "H0STCNT0", sym))
            await asyncio.sleep(0.1)
            await self._ws.send(_subscribe_msg(self._approval_key, "H0STASP0", sym))
            await asyncio.sleep(0.1)
            if not self._mock:
                await self._ws.send(_subscribe_msg(self._approval_key, "H0STMKO0", sym))
                await asyncio.sleep(0.1)

        self._subscribed = set(symbols)
        logger.info("market_data_stream.started", symbols=symbols, mode="websocket")
        self._recv_task = asyncio.create_task(self._recv_loop())

    async def _recv_loop(self) -> None:
        reconnect_delay = 5
        while self._running:
            try:
                async for raw in self._ws:
                    if not self._running:
                        return
                    if raw[0] in ("0", "1"):
                        reconnect_delay = 5
                    await self._handle_message(raw)
            except websockets.ConnectionClosed:
                logger.warning("market_data_stream.disconnected")
            except Exception as e:
                logger.error("market_data_stream.error", error=str(e))

            if not self._running:
                return

            delay = min(reconnect_delay, 60)
            logger.info("market_data_stream.reconnecting", delay=delay)
            await asyncio.sleep(delay)
            reconnect_delay = min(reconnect_delay * 2, 60)

            try:
                if self._ws:
                    try:
                        await asyncio.wait_for(self._ws.close(), timeout=2)
                    except Exception:
                        pass
                    self._ws = None
                    await asyncio.sleep(3)
                self._approval_key = await asyncio.to_thread(
                    _get_approval_key, self._app_key, self._app_secret, mock=self._mock,
                )
                await asyncio.sleep(1)
                ws_url = _get_ws_url(self._mock)
                self._ws = await websockets.connect(ws_url, ping_interval=None)
                if self._hts_id:
                    cni_tr = "H0STCNI9" if self._mock else "H0STCNI0"
                    await self._ws.send(_subscribe_msg(self._approval_key, cni_tr, self._hts_id))
                    await asyncio.sleep(0.2)
                for sym in self._subscribed:
                    await self._ws.send(_subscribe_msg(self._approval_key, "H0STCNT0", sym))
                    await asyncio.sleep(0.2)
                    await self._ws.send(_subscribe_msg(self._approval_key, "H0STASP0", sym))
                    await asyncio.sleep(0.2)
                    if not self._mock:
                        await self._ws.send(_subscribe_msg(self._approval_key, "H0STMKO0", sym))
                        await asyncio.sleep(0.2)
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
            elif tr_id in ("H0STCNI0", "H0STCNI9"):
                await self._on_fill_notice(data)
            elif tr_id == "H0STMKO0":
                await self._on_market_info(data)
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

    async def _on_fill_notice(self, data: str) -> None:
        fields = data.split("^")
        if len(fields) < 14:
            return
        cntg_yn = fields[13]
        rfus_yn = fields[12]
        symbol = fields[8]
        side_cd = fields[4]
        fill_data: dict[str, Any] = {
            "symbol": symbol,
            "order_no": fields[2],
            "side": "sell" if side_cd == "01" else "buy",
            "quantity": int(fields[9] or "0"),
            "price": int(fields[10] or "0"),
            "time": fields[11],
            "is_fill": cntg_yn == "2",
            "is_rejected": rfus_yn == "1",
            "name": fields[23].strip() if len(fields) > 23 else "",
        }
        if cntg_yn == "2":
            logger.info("ws.fill_notice", symbol=symbol, side=fill_data["side"],
                        qty=fill_data["quantity"], price=fill_data["price"])
        elif rfus_yn == "1":
            logger.warning("ws.order_rejected", symbol=symbol, order_no=fill_data["order_no"])
        await self._emit_fill(fill_data)

    async def _on_market_info(self, data: str) -> None:
        fields = data.split("^")
        if len(fields) < 8:
            return
        symbol = fields[0]
        vi_triggered = fields[7] == "Y"
        halt = fields[1] == "Y"
        if vi_triggered or halt:
            logger.warning("ws.vi_triggered", symbol=symbol, halt=halt)
            await self._emit_vi(symbol, True)
        else:
            await self._emit_vi(symbol, False)

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
                    if not self._mock:
                        await self._ws.send(_unsubscribe_msg(self._approval_key, "H0STMKO0", sym))
                except Exception as e:
                    logger.warning("market_data_stream.unsubscribe_failed", symbol=sym, error=str(e))
                await asyncio.sleep(0.05)

            for sym in to_add:
                try:
                    await self._ws.send(_subscribe_msg(self._approval_key, "H0STCNT0", sym))
                    await self._ws.send(_subscribe_msg(self._approval_key, "H0STASP0", sym))
                    if not self._mock:
                        await self._ws.send(_subscribe_msg(self._approval_key, "H0STMKO0", sym))
                except Exception as e:
                    logger.warning("market_data_stream.subscribe_failed", symbol=sym, error=str(e))
                await asyncio.sleep(0.05)

        self._subscribed = new_set
        if hasattr(self, '_simulator') and self._simulator:
            self._simulator.update_symbols(list(new_set))
        logger.info(
            "market_data_stream.subscriptions_updated",
            removed=list(to_remove),
            added=list(to_add),
            total=len(new_set),
        )

    async def _cleanup_recv_task(self) -> None:
        if self._recv_task and not self._recv_task.done():
            self._recv_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._recv_task
        self._recv_task = None

    async def stop(self) -> None:
        self._stopping = True
        self._running = False
        await self._cleanup_recv_task()
        if hasattr(self, '_simulator') and self._simulator:
            await self._simulator.stop()
            self._simulator = None
        if self._ws:
            try:
                await asyncio.wait_for(self._ws.close(), timeout=3)
            except (asyncio.TimeoutError, Exception):
                pass
            self._ws = None
        self._stopping = False
        logger.info("market_data_stream.stopped")

    @property
    def is_running(self) -> bool:
        return self._running
