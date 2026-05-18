"""KIS 해외주식 브로커 — 미국 주식 전용.

KIS Open API의 해외주식 REST/WebSocket 엔드포인트를 사용하며,
기존 KISBroker(국내 전용)를 전혀 수정하지 않는 독립 구현체.
"""

import asyncio
import json
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import requests
import structlog

from scalpy.broker.base import BaseBroker
from scalpy.config import settings
from scalpy.core.enums import OrderStatus, OrderType, Side
from scalpy.core.exceptions import AuthenticationError
from scalpy.core.models import Order, Position

logger = structlog.get_logger()

_TOKEN_PATH = Path(__file__).resolve().parent.parent.parent.parent / "config" / ".token.json"

_EXCHANGE_MAP = {
    "NASD": "NAS",
    "NYSE": "NYS",
    "AMEX": "AMS",
}


class KISOverseasBroker(BaseBroker):
    """한국투자증권 해외주식 API 브로커."""

    def __init__(
        self,
        app_key: str,
        app_secret: str,
        account_no: str,
        *,
        mock: bool = True,
        exchange: str = "NASD",
    ) -> None:
        super().__init__()
        self._app_key = app_key
        self._app_secret = app_secret
        self._account_no = account_no
        self._cano = account_no[:8]
        self._acnt_prdt_cd = account_no[8:].lstrip("-") or "01"
        self._mock = mock
        self._exchange = exchange
        self._connected = False
        self._token: str = ""
        self._token_expires: datetime = datetime.min
        self._last_api_call: float = 0
        self._api_lock = asyncio.Lock()

    def _base_url(self) -> str:
        key = "virtual" if self._mock else "real"
        cfg = settings.get("kis_api.rest_urls", {})
        url = cfg.get(key)
        if not url:
            raise RuntimeError(f"kis_api.rest_urls.{key} 설정 필요")
        return url

    async def _throttle(self) -> None:
        gap = 1.05 if self._mock else 0.15
        async with self._api_lock:
            elapsed = time.monotonic() - self._last_api_call
            if elapsed < gap:
                await asyncio.sleep(gap - elapsed)
            self._last_api_call = time.monotonic()

    def _ensure_token(self) -> str:
        if self._token and self._token_expires > datetime.now() + timedelta(minutes=5):
            return self._token
        self._refresh_token()
        return self._token

    def _refresh_token(self) -> None:
        if _TOKEN_PATH.exists():
            data = json.loads(_TOKEN_PATH.read_text())
            expires = datetime.fromisoformat(data["valid_until"])
            if expires > datetime.now() + timedelta(minutes=5):
                self._token = f"Bearer {data['value']}"
                self._token_expires = expires
                return

        url = f"{self._base_url()}/oauth2/tokenP"
        resp = requests.post(url, json={
            "grant_type": "client_credentials",
            "appkey": self._app_key,
            "appsecret": self._app_secret,
        }, timeout=10)
        resp.raise_for_status()
        body = resp.json()
        token_val = body["access_token"]
        expires = datetime.fromisoformat(body["access_token_token_expired"])
        _TOKEN_PATH.write_text(json.dumps({
            "value": token_val,
            "valid_until": expires.isoformat(),
        }))
        self._token = f"Bearer {token_val}"
        self._token_expires = expires
        logger.info("kis_overseas.token_created")

    def _headers(self, tr_id: str) -> dict[str, str]:
        if self._mock:
            tr_id = "V" + tr_id[1:]
        return {
            "content-type": "application/json; charset=utf-8",
            "authorization": self._ensure_token(),
            "appkey": self._app_key,
            "appsecret": self._app_secret,
            "tr_id": tr_id,
            "custtype": "P",
        }

    def _get(self, path: str, tr_id: str, params: dict) -> dict:
        url = f"{self._base_url()}{path}"
        resp = requests.get(url, headers=self._headers(tr_id), params=params, timeout=10)
        if resp.status_code >= 400:
            body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            msg_cd = body.get("msg_cd", "")
            if "token" in body.get("msg1", "").lower() or msg_cd == "EGW00121":
                self._refresh_token()
                time.sleep(0.5)
                resp = requests.get(url, headers=self._headers(tr_id), params=params, timeout=10)
            elif msg_cd == "EGW00201":
                time.sleep(1)
                resp = requests.get(url, headers=self._headers(tr_id), params=params, timeout=10)
            else:
                resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, tr_id: str, body: dict) -> dict:
        url = f"{self._base_url()}{path}"
        resp = requests.post(url, headers=self._headers(tr_id), json=body, timeout=10)
        if resp.status_code >= 400:
            rj = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            msg_cd = rj.get("msg_cd", "")
            if "token" in rj.get("msg1", "").lower() or msg_cd == "EGW00121":
                self._refresh_token()
                time.sleep(0.5)
                resp = requests.post(url, headers=self._headers(tr_id), json=body, timeout=10)
            else:
                resp.raise_for_status()
        return resp.json()

    async def connect(self) -> None:
        self._refresh_token()
        self._connected = True
        mode = "모의투자" if self._mock else "실거래"
        logger.info("kis_overseas.connected", mode=mode, exchange=self._exchange)

    async def disconnect(self) -> None:
        self._connected = False
        logger.info("kis_overseas.disconnected")

    async def place_order(self, order: Order) -> Order:
        if not self._connected:
            order.status = OrderStatus.REJECTED
            return order

        await self._throttle()
        try:
            if order.side == Side.BUY:
                tr_id = "TTTT1002U"
            else:
                tr_id = "TTTT1006U"

            price_str = f"{float(order.price):.2f}" if order.order_type == OrderType.LIMIT else "0"
            body = {
                "CANO": self._cano,
                "ACNT_PRDT_CD": self._acnt_prdt_cd,
                "OVRS_EXCG_CD": self._exchange,
                "PDNO": order.symbol,
                "ORD_QTY": str(order.quantity),
                "OVRS_ORD_UNPR": price_str,
                "ORD_SVR_DVSN_CD": "0",
                "ORD_DVSN": "00",
            }
            if order.side == Side.SELL:
                body["SLL_TYPE"] = "00"

            data = await asyncio.to_thread(
                self._post, "/uapi/overseas-stock/v1/trading/order", tr_id, body
            )

            if data.get("rt_cd") == "0":
                order.status = OrderStatus.FILLED
                order.filled_at = datetime.now()
                order.order_id = data.get("output", {}).get("ODNO", "")
                logger.info("kis_overseas.order_filled",
                            symbol=order.symbol, side=order.side.value,
                            qty=order.quantity, price=price_str)
            else:
                order.status = OrderStatus.REJECTED
                order.reject_reason = data.get("msg1", "unknown")
                logger.warning("kis_overseas.order_rejected",
                               symbol=order.symbol, msg=data.get("msg1", ""))
        except Exception as e:
            order.status = OrderStatus.REJECTED
            order.reject_reason = str(e)
            logger.warning("kis_overseas.order_error", symbol=order.symbol, error=str(e))

        return order

    async def cancel_order(self, order_id: str) -> bool:
        if not self._connected:
            return False
        await self._throttle()
        try:
            body = {
                "CANO": self._cano,
                "ACNT_PRDT_CD": self._acnt_prdt_cd,
                "OVRS_EXCG_CD": self._exchange,
                "ORGN_ODNO": order_id,
                "RVSE_CNCL_DVSN_CD": "02",
                "ORD_QTY": "0",
                "OVRS_ORD_UNPR": "0",
            }
            data = await asyncio.to_thread(
                self._post, "/uapi/overseas-stock/v1/trading/order-rvsecncl", "TTTT1004U", body
            )
            return data.get("rt_cd") == "0"
        except Exception as e:
            logger.error("kis_overseas.cancel_failed", order_id=order_id, error=str(e))
            return False

    async def cancel_all_orders(self) -> int:
        if not self._connected:
            return 0
        await self._throttle()
        try:
            params = {
                "CANO": self._cano,
                "ACNT_PRDT_CD": self._acnt_prdt_cd,
                "OVRS_EXCG_CD": self._exchange,
                "SORT_SQN": "DS",
                "CTX_AREA_FK200": "",
                "CTX_AREA_NK200": "",
            }
            data = await asyncio.to_thread(
                self._get, "/uapi/overseas-stock/v1/trading/inquire-nccs", "TTTS3018R", params
            )
            orders = data.get("output", [])
            cancelled = 0
            for o in orders:
                odno = o.get("odno", "")
                if odno and await self.cancel_order(odno):
                    cancelled += 1
            return cancelled
        except Exception as e:
            logger.error("kis_overseas.cancel_all_failed", error=str(e))
            return 0

    async def sync_positions(self) -> int:
        if not self._connected:
            return 0

        await self._throttle()
        try:
            params = {
                "CANO": self._cano,
                "ACNT_PRDT_CD": self._acnt_prdt_cd,
                "OVRS_EXCG_CD": self._exchange,
                "TR_CRCY_CD": "USD",
                "CTX_AREA_FK200": "",
                "CTX_AREA_NK200": "",
            }
            data = await asyncio.to_thread(
                self._get, "/uapi/overseas-stock/v1/trading/inquire-balance", "TTTS3012R", params
            )
            items = data.get("output1", [])
            api_positions: dict[str, Position] = {}
            for item in items:
                qty = int(item.get("ovrs_cblc_qty", "0"))
                sellable = int(item.get("ord_psbl_qty", "0"))
                if qty == 0 or sellable == 0:
                    continue
                symbol = item.get("ovrs_pdno", "")
                if not symbol:
                    continue
                name = item.get("ovrs_item_name", symbol)
                self._position_names[symbol] = name
                pnl = Decimal(item.get("frcr_evlu_pfls_amt", "0"))
                pnl_rt = float(item.get("evlu_pfls_rt", "0"))
                api_positions[symbol] = Position(
                    symbol=symbol,
                    side=Side.BUY,
                    quantity=qty,
                    avg_price=Decimal(item.get("pchs_avg_pric", "0")),
                    current_price=Decimal(item.get("now_pric2", "0")),
                    strategy="synced",
                    opened_at=datetime.now(),
                    unrealized_pnl=pnl,
                )
                api_positions[symbol]._pnl_pct = pnl_rt

            existing = self._pm._positions
            for code, api_pos in api_positions.items():
                if code in existing:
                    existing[code].quantity = api_pos.quantity
                    existing[code].avg_price = api_pos.avg_price
                    existing[code].current_price = api_pos.current_price
                    existing[code].unrealized_pnl = api_pos.unrealized_pnl
                    existing[code]._pnl_pct = api_pos._pnl_pct
                else:
                    existing[code] = api_pos

            gone = [s for s in existing if s not in api_positions]
            for s in gone:
                del existing[s]

            logger.info("kis_overseas.positions_synced", count=len(existing))
            return len(existing)
        except Exception as e:
            logger.warning("kis_overseas.sync_failed", error=str(e))
            return 0

    async def get_balance(self) -> Decimal:
        if not self._connected:
            return Decimal("0")
        await self._throttle()
        try:
            params = {
                "CANO": self._cano,
                "ACNT_PRDT_CD": self._acnt_prdt_cd,
                "OVRS_EXCG_CD": self._exchange,
                "TR_CRCY_CD": "USD",
                "CTX_AREA_FK200": "",
                "CTX_AREA_NK200": "",
            }
            data = await asyncio.to_thread(
                self._get, "/uapi/overseas-stock/v1/trading/inquire-balance", "TTTS3012R", params
            )
            out2 = data.get("output2", {})
            total = out2.get("tot_evlu_pfls_amt", "0")
            return Decimal(str(total))
        except Exception as e:
            logger.warning("kis_overseas.balance_failed", error=str(e))
            return Decimal("0")

    async def get_available_cash(self) -> Decimal:
        if not self._connected:
            return Decimal("0")
        await self._throttle()
        try:
            params = {
                "CANO": self._cano,
                "ACNT_PRDT_CD": self._acnt_prdt_cd,
                "OVRS_EXCG_CD": self._exchange,
                "OVRS_ORD_UNPR": "0",
                "ITEM_CD": "",
            }
            data = await asyncio.to_thread(
                self._get, "/uapi/overseas-stock/v1/trading/inquire-psamount", "TTTS3007R", params
            )
            output = data.get("output", {})
            cash = output.get("ovrs_ord_psbl_amt", "0")
            return Decimal(str(cash))
        except Exception as e:
            logger.warning("kis_overseas.available_cash_failed", error=str(e))
            return Decimal("0")

    async def get_buyable_qty(self, symbol: str, price: Decimal) -> int:
        cash = await self.get_available_cash()
        if price <= 0:
            return 0
        return int(cash / price)

    async def get_minute_candles(self, symbol: str, count: int = 60) -> list[dict]:
        if not self._connected:
            return []
        excd = _EXCHANGE_MAP.get(self._exchange, "NAS")
        await self._throttle()
        try:
            params = {
                "AUTH": "",
                "EXCD": excd,
                "SYMB": symbol,
                "NMIN": "1",
                "PINC": "1",
                "NEXT": "",
                "NREC": str(min(count, 120)),
                "FILL": "",
                "KEYB": "",
            }
            data = await asyncio.to_thread(
                self._get,
                "/uapi/overseas-price/v1/quotations/inquire-time-itemchartprice",
                "HHDFS76950200",
                params,
            )
            items = data.get("output2", [])
            result = []
            for item in items:
                result.append({
                    "open": float(item.get("open", 0)),
                    "high": float(item.get("high", 0)),
                    "low": float(item.get("low", 0)),
                    "close": float(item.get("last", 0)),
                    "volume": int(item.get("evol", 0)),
                    "time": item.get("xhms", ""),
                })
            result.sort(key=lambda c: c["time"])
            return result[-count:]
        except Exception as e:
            logger.warning("kis_overseas.minute_candles_failed", symbol=symbol, error=str(e))
            return []

    async def get_trade_history(self) -> list[dict[str, Any]]:
        if not self._connected:
            return []
        await self._throttle()
        try:
            today = datetime.now().strftime("%Y%m%d")
            params = {
                "CANO": self._cano,
                "ACNT_PRDT_CD": self._acnt_prdt_cd,
                "PDNO": "",
                "ORD_STRT_DT": today,
                "ORD_END_DT": today,
                "SLL_BUY_DVSN": "00",
                "CCLD_NCCS_DVSN": "00",
                "OVRS_EXCG_CD": self._exchange,
                "SORT_SQN": "DS",
                "ORD_DT": "",
                "ORD_GNO_BRNO": "",
                "ODNO": "",
                "CTX_AREA_FK200": "",
                "CTX_AREA_NK200": "",
            }
            data = await asyncio.to_thread(
                self._get, "/uapi/overseas-stock/v1/trading/inquire-ccnl", "TTTS3035R", params
            )
            items = data.get("output", [])
            trades = []
            for item in items:
                ft_ccld_qty = int(item.get("ft_ccld_qty", "0"))
                if ft_ccld_qty == 0:
                    continue
                side_cd = item.get("sll_buy_dvsn_cd", "")
                trades.append({
                    "order_no": item.get("odno", ""),
                    "order_date": item.get("ord_dt", ""),
                    "symbol": item.get("pdno", ""),
                    "name": item.get("prdt_name", ""),
                    "side": "sell" if side_cd == "01" else "buy",
                    "ord_qty": int(item.get("ft_ord_qty", "0")),
                    "tot_ccld_qty": ft_ccld_qty,
                    "avg_price": float(item.get("ft_ccld_unpr3", "0")),
                    "tot_ccld_amt": float(item.get("ft_ccld_amt3", "0")),
                })
            return trades
        except Exception as e:
            logger.error("kis_overseas.trade_history_failed", error=str(e))
            return []

    async def get_top_volume_stocks(self, count: int = 30) -> list[dict[str, Any]]:
        if not self._connected:
            return []
        await self._throttle()
        excd = _EXCHANGE_MAP.get(self._exchange, "NAS")
        try:
            params = {
                "AUTH": "",
                "EXCD": excd,
                "SYMB": "",
                "GUBN": "0",
                "BYMD": "",
                "MODP": "0",
                "KEYB": "",
            }
            data = await asyncio.to_thread(
                self._get,
                "/uapi/overseas-price/v1/quotations/inquire-search",
                "HHDFS76410000",
                params,
            )
            items = data.get("output2", [])
            stocks = []
            for item in items[:count]:
                symbol = item.get("symb", "")
                if not symbol:
                    continue
                stocks.append({
                    "symbol": symbol,
                    "name": item.get("name", ""),
                    "volume": int(item.get("tvol", 0)),
                    "price": Decimal(item.get("last", "0")),
                    "change_rate": float(item.get("rate", "0")),
                })
            return stocks
        except Exception as e:
            logger.error("kis_overseas.top_volume_failed", error=str(e))
            return []

    async def get_current_price(self, symbol: str) -> Decimal:
        if not self._connected:
            return Decimal("0")
        excd = _EXCHANGE_MAP.get(self._exchange, "NAS")
        await self._throttle()
        try:
            params = {
                "AUTH": "",
                "EXCD": excd,
                "SYMB": symbol,
            }
            data = await asyncio.to_thread(
                self._get,
                "/uapi/overseas-price/v1/quotations/price",
                "HHDFS00000300",
                params,
            )
            output = data.get("output", {})
            return Decimal(output.get("last", "0"))
        except Exception as e:
            logger.warning("kis_overseas.current_price_failed", symbol=symbol, error=str(e))
            return Decimal("0")

    async def subscribe_market_data(
        self, symbols: list[str], callback: Callable[..., Any]
    ) -> None:
        logger.warning("kis_overseas.subscribe_via_broker_not_supported")
