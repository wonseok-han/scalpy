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

_TICK_SIZES = [
    (2_000, 1),
    (5_000, 5),
    (20_000, 10),
    (50_000, 50),
    (200_000, 100),
    (500_000, 500),
    (float("inf"), 1_000),
]


def _round_to_tick(price: int) -> int:
    for threshold, tick in _TICK_SIZES:
        if price < threshold:
            return (price // tick) * tick
    return price


class KISBroker(BaseBroker):
    """한국투자증권 Open API broker (pykis).

    Requires KIS_APP_KEY, KIS_APP_SECRET, KIS_ACCOUNT_NO in .secrets.toml.
    """

    def __init__(
        self, app_key: str, app_secret: str, account_no: str, *, mock: bool = True
    ) -> None:
        super().__init__()
        self._app_key = app_key
        self._app_secret = app_secret
        self._account_no = account_no
        self._cano = account_no[:8]
        self._acnt_prdt_cd = account_no[8:].lstrip("-") or "01"
        self._mock = mock
        self._connected = False
        self._api: Any = None
        self._last_api_call: float = 0
        self._api_lock = asyncio.Lock()
        self._last_ccld_first_page: int = -1
        self._last_ccld_has_next: bool = False

    async def _throttle(self) -> None:
        gap = 1.05 if self._mock else 0.15
        async with self._api_lock:
            elapsed = time.monotonic() - self._last_api_call
            if elapsed < gap:
                await asyncio.sleep(gap - elapsed)
            self._last_api_call = time.monotonic()

    async def connect(self) -> None:
        try:
            from pykis import Api, DomainInfo
        except ImportError as e:
            raise AuthenticationError("pykis 패키지가 설치되지 않았습니다") from e

        domain = DomainInfo("virtual" if self._mock else "real")

        self._api = Api(
            key_info={"appkey": self._app_key, "appsecret": self._app_secret},
            domain_info=domain,
            account_info={"account_code": self._cano, "product_code": self._acnt_prdt_cd},
        )
        self._load_or_create_token()
        self._connected = True
        mode = "모의투자" if self._mock else "실거래"
        logger.info("kis_broker.connected", mode=mode)

    def _load_or_create_token(self) -> None:
        if _TOKEN_PATH.exists():
            data = json.loads(_TOKEN_PATH.read_text())
            expires = datetime.fromisoformat(data["valid_until"])
            if expires > datetime.now() + timedelta(minutes=5):
                self._api.token.value = data["value"]
                self._api.token.valid_until = expires
                logger.info("kis_broker.token_cached", expires=expires.isoformat())
                return
            logger.info("kis_broker.token_expiring_soon", expires=expires.isoformat())

        self._refresh_token()

    def _refresh_token(self) -> None:
        self._api.create_token()
        _TOKEN_PATH.write_text(json.dumps({
            "value": self._api.token.value,
            "valid_until": self._api.token.valid_until.isoformat(),
        }))
        logger.info("kis_broker.token_created")

    async def disconnect(self) -> None:
        self._api = None
        self._connected = False
        logger.info("kis_broker.disconnected")

    async def place_order(self, order: Order) -> Order:
        if not self._connected or self._api is None:
            order.status = OrderStatus.REJECTED
            return order

        await self._throttle()
        try:
            if order.order_type == OrderType.MARKET:
                price = 0
            else:
                price = _round_to_tick(int(order.price))
            if order.side == Side.BUY:
                self._api.buy_kr_stock(order.symbol, order.quantity, price)
            else:
                self._api.sell_kr_stock(order.symbol, order.quantity, price)

            order.status = OrderStatus.FILLED
            order.filled_at = datetime.now()
            logger.info(
                "kis_broker.order_filled",
                symbol=order.symbol,
                side=order.side.value,
                quantity=order.quantity,
                price=price,
            )
        except Exception as e:
            order.status = OrderStatus.REJECTED
            order.reject_reason = str(e)
            logger.warning("kis_broker.order_rejected", symbol=order.symbol, error=str(e))

        return order

    async def cancel_order(self, order_id: str) -> bool:
        if not self._connected or self._api is None:
            return False

        try:
            self._api.cancel_kr_order(order_id)
            logger.info("kis_broker.order_cancelled", order_id=order_id)
            return True
        except Exception as e:
            logger.error("kis_broker.cancel_failed", order_id=order_id, error=str(e))
            return False

    async def cancel_all_orders(self) -> int:
        if not self._connected or self._api is None:
            return 0
        await self._throttle()
        try:
            df = await asyncio.to_thread(
                self._retry_on_token_expired, self._api.get_kr_orders
            )
            if df.empty:
                return 0
            await asyncio.to_thread(self._api.cancel_all_kr_orders)
            count = len(df)
            logger.info("kis_broker.all_orders_cancelled", count=count)
            return count
        except Exception as e:
            logger.error("kis_broker.cancel_all_failed", error=str(e))
            return 0

    def _is_token_expired_error(self, e: Exception) -> bool:
        return "만료된 token" in str(e)

    def _retry_on_token_expired(self, func):
        try:
            return func()
        except RuntimeError as e:
            if self._is_token_expired_error(e):
                logger.warning("kis_broker.token_expired_runtime", error=str(e))
                self._refresh_token()
                return func()
            raise

    def _retry_on_token_expired_resp(self, func):
        resp = func()
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except Exception:
                logger.error("kis_broker.api_error", status=resp.status_code, body=resp.text[:500])
                resp.raise_for_status()
                return resp
            msg = body.get("msg1", "")
            msg_cd = body.get("msg_cd", "")
            if resp.status_code == 500 and ("token" in msg.lower() or msg_cd == "EGW00121"):
                logger.warning("kis_broker.token_invalid_rest", msg=msg)
                self._refresh_token()
                time.sleep(1)
                resp2 = func()
                logger.info("kis_broker.token_retry_result", status=resp2.status_code)
                return resp2
            if msg_cd == "EGW00201":
                logger.warning("kis_broker.rate_limited_rest", msg=msg)
                time.sleep(1)
                return func()
            logger.error("kis_broker.api_error", status=resp.status_code, msg_cd=msg_cd, msg=msg)
            resp.raise_for_status()
        return resp

    async def sync_positions(self) -> int:
        if not self._connected or self._api is None:
            return 0

        await self._throttle()
        res = await asyncio.to_thread(
            self._retry_on_token_expired, self._api._get_kr_total_balance
        )
        items = res.outputs[0] if res.outputs else []
        api_positions: dict[str, Position] = {}
        for item in items:
            qty = int(item.get("hldg_qty", 0))
            sellable = int(item.get("ord_psbl_qty", 0))
            if qty == 0 or sellable == 0:
                continue
            code = item.get("pdno", "")
            if not code:
                continue
            name = item.get("prdt_name", code)
            self._position_names[code] = name
            pnl = Decimal(item.get("evlu_pfls_amt", "0"))
            pnl_rt = float(item.get("evlu_pfls_rt", "0"))
            api_positions[code] = Position(
                symbol=code,
                side=Side.BUY,
                quantity=qty,
                avg_price=Decimal(item.get("pchs_avg_pric", "0")),
                current_price=Decimal(item.get("prpr", "0")),
                strategy="synced",
                opened_at=datetime.now(),
                unrealized_pnl=pnl,
            )
            api_positions[code]._pnl_pct = pnl_rt

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

        logger.info("kis_broker.positions_synced", count=len(existing))
        return len(existing)

    async def get_balance(self) -> Decimal:
        if not self._connected or self._api is None:
            return Decimal("0")

        await self._throttle()
        res = self._retry_on_token_expired(self._api._get_kr_total_balance)
        summary = res.outputs[1][0]
        value = summary.get("tot_evlu_amt") or summary.get("dnca_tot_amt", "0")
        return Decimal(str(int(value)))

    async def get_available_cash(self) -> Decimal:
        if not self._connected or self._api is None:
            return Decimal("0")

        await self._throttle()
        value = await asyncio.to_thread(
            self._retry_on_token_expired, self._api.get_kr_buyable_cash
        )
        return Decimal(str(value))

    async def get_buyable_qty(self, symbol: str, price: Decimal) -> int:
        if not self._connected or self._api is None:
            return 0
        await self._throttle()
        from pykis import APIRequestParameter

        def _fetch() -> int:
            params = {
                "CANO": self._cano,
                "ACNT_PRDT_CD": self._acnt_prdt_cd,
                "PDNO": symbol,
                "ORD_UNPR": str(int(price)),
                "ORD_DVSN": "01",
                "CMA_EVLU_AMT_ICLD_YN": "Y",
                "OVRS_ICLD_YN": "N",
            }
            url_path = "/uapi/domestic-stock/v1/trading/inquire-psbl-order"
            tr_id = "TTTC8908R"
            req = APIRequestParameter(url_path, tr_id, params)
            res = self._api._send_get_request(req)
            output = res.outputs[0]
            qty = int(output.get("nrcvb_buy_qty", "0"))
            logger.info("kis_broker.buyable_qty", symbol=symbol, price=str(price), qty=qty)
            return qty

        try:
            return await asyncio.to_thread(self._retry_on_token_expired, _fetch)
        except Exception as e:
            logger.warning("kis_broker.buyable_qty_failed", symbol=symbol, error=str(e))
            return 0

    async def get_minute_candles(self, symbol: str, count: int = 60) -> list[dict]:
        if not self._connected or self._api is None:
            return []
        from pykis import APIRequestParameter

        def _fetch_all() -> list[dict]:
            result: list[dict] = []
            cursor = "153000"
            while len(result) < count:
                params = {
                    "FID_COND_MRKT_DIV_CODE": "J",
                    "FID_INPUT_ISCD": symbol,
                    "FID_INPUT_HOUR_1": cursor,
                    "FID_PW_DATA_INCU_YN": "Y",
                    "FID_ETC_CLS_CODE": "",
                }
                url_path = "/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
                tr_id = "FHKST03010200"
                req = APIRequestParameter(url_path, tr_id, params)
                res = self._api._send_get_request(req)
                items = res.outputs[1] if len(res.outputs) > 1 else []
                if not items:
                    logger.debug("kis_broker.minute_candles_empty_page", symbol=symbol, cursor=cursor, outputs_len=len(res.outputs))
                    break
                for item in items:
                    hour = item.get("stck_cntg_hour", "")
                    if hour < "090000":
                        continue
                    result.append({
                        "open": int(item.get("stck_oprc", 0)),
                        "high": int(item.get("stck_hgpr", 0)),
                        "low": int(item.get("stck_lwpr", 0)),
                        "close": int(item.get("stck_prpr", 0)),
                        "volume": int(item.get("cntg_vol", 0)),
                        "time": hour,
                    })
                earliest = items[-1].get("stck_cntg_hour", "")
                if earliest <= "090000":
                    break
                cursor = earliest
                time.sleep(0.2)
            result.sort(key=lambda c: c["time"])
            return result[-count:]

        try:
            candles = await asyncio.to_thread(self._retry_on_token_expired, _fetch_all)
            logger.info("kis_broker.minute_candles_fetched", symbol=symbol, count=len(candles))
            return candles
        except Exception as e:
            logger.warning("kis_broker.minute_candles_failed", symbol=symbol, error=str(e))
            return []

    async def get_trade_history(self) -> list[dict[str, Any]]:
        if not self._connected or self._api is None:
            return []
        return await self._fetch_daily_ccld()

    async def get_period_pnl(self) -> list[dict[str, Any]]:
        if not self._connected or self._api is None or self._mock:
            return []
        return await self._get_trade_history_profit()

    async def get_daily_profit_summary(self) -> dict[str, Any]:
        if not self._connected or self._api is None or self._mock:
            return {}
        return await self._get_period_profit_summary()

    async def _get_period_profit_summary(self) -> dict[str, Any]:
        """실거래: 기간별손익일별합산조회 TTTC8708R — 당일 실현손익/수수료 요약."""
        rest_urls = settings.get("kis_api.rest_urls", {})
        base_url = rest_urls.get("real")
        if not base_url:
            return {}

        today = datetime.now().strftime("%Y%m%d")
        headers = {
            "content-type": "application/json; charset=utf-8",
            "appkey": self._app_key,
            "appsecret": self._app_secret,
            "tr_id": "TTTC8708R",
            "custtype": "P",
        }
        params = {
            "CANO": self._cano,
            "ACNT_PRDT_CD": self._acnt_prdt_cd,
            "INQR_STRT_DT": today,
            "INQR_END_DT": today,
            "PDNO": "",
            "SORT_DVSN": "00",
            "INQR_DVSN": "00",
            "CBLC_DVSN": "00",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }

        await self._throttle()
        try:
            def _fetch():
                h = {**headers, "authorization": self._api.token.value}
                return requests.get(
                    f"{base_url}/uapi/domestic-stock/v1/trading/inquire-period-profit",
                    headers=h, params=params, timeout=10,
                )

            resp = await asyncio.to_thread(self._retry_on_token_expired_resp, _fetch)
            data = resp.json()
            if data.get("rt_cd") != "0":
                logger.warning("kis_broker.period_profit_error", msg=data.get("msg1", ""), code=data.get("msg_cd", ""))
                return {}

            out2 = data.get("output2", {})
            result = {
                "tot_rlzt_pfls": int(out2.get("tot_rlzt_pfls", "0")),
                "tot_fee": int(out2.get("tot_fee", "0")),
                "tot_tltx": int(out2.get("tot_tltx", "0")),
                "loan_int": int(out2.get("loan_int", "0")),
            }
            logger.info("kis_broker.period_profit_fetched", **result)
            return result
        except Exception as e:
            logger.error("kis_broker.period_profit_failed", error=str(e))
            return {}

    async def _get_trade_history_profit(self) -> list[dict[str, Any]]:
        """실거래: 기간별매매손익현황조회 (수수료/손익 포함)."""
        rest_urls = settings.get("kis_api.rest_urls", {})
        base_url = rest_urls.get("real")
        if not base_url:
            return []

        today = datetime.now().strftime("%Y%m%d")
        headers = {
            "content-type": "application/json; charset=utf-8",
            "appkey": self._app_key,
            "appsecret": self._app_secret,
            "tr_id": "TTTC8715R",
            "custtype": "P",
        }
        params = {
            "CANO": self._cano,
            "ACNT_PRDT_CD": self._acnt_prdt_cd,
            "INQR_STRT_DT": today,
            "INQR_END_DT": today,
            "PDNO": "",
            "SORT_DVSN": "00",
            "CBLC_DVSN": "00",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }

        all_items: list[dict[str, str]] = []
        ctx_fk = ""
        ctx_nk = ""

        await self._throttle()
        try:
            for _ in range(10):
                p = {**params, "CTX_AREA_FK100": ctx_fk, "CTX_AREA_NK100": ctx_nk}
                tr_cont = "" if not ctx_fk else "N"

                def _fetch(p=p, tr_cont=tr_cont):
                    h = {**headers, "authorization": self._api.token.value, "tr_cont": tr_cont}
                    return requests.get(
                        f"{base_url}/uapi/domestic-stock/v1/trading/inquire-period-trade-profit",
                        headers=h, params=p, timeout=10,
                    )

                resp = await asyncio.to_thread(self._retry_on_token_expired_resp, _fetch)
                data = resp.json()
                if data.get("rt_cd") != "0":
                    logger.warning("kis_broker.trade_profit_api_error", msg=data.get("msg1", ""), code=data.get("msg_cd", ""))
                    break

                all_items.extend(data.get("output1", []))

                resp_cont = resp.headers.get("tr_cont", "")
                if resp_cont not in ("F", "M"):
                    break
                ctx_fk = data.get("ctx_area_fk100", "").strip()
                ctx_nk = data.get("ctx_area_nk100", "").strip()
                if not ctx_fk:
                    break
                await self._throttle()

            trades: list[dict[str, Any]] = []
            for item in all_items:
                symbol = item.get("pdno", "")
                if not symbol:
                    continue
                sll_qty = int(item.get("sll_qty", "0"))
                if sll_qty == 0:
                    continue
                fee = int(item.get("fee", "0")) + int(item.get("tl_tax", "0"))
                pnl = item.get("rlzt_pfls", "")

                trades.append({
                    "symbol": symbol,
                    "name": item.get("prdt_name", ""),
                    "side": "sell",
                    "price": int(item.get("sll_pric", "0")),
                    "quantity": sll_qty,
                    "amount": int(item.get("sll_amt", "0")),
                    "buy_amt": int(item.get("buy_amt", "0")),
                    "time": item.get("trad_dt", ""),
                    "fee": fee,
                    "pnl": pnl if pnl and pnl != "0" else "",
                })
            logger.info("kis_broker.trade_profit_fetched", count=len(trades))
            return trades
        except Exception as e:
            logger.error("kis_broker.trade_profit_failed", error=str(e))
            return []

    async def _fetch_daily_ccld(self) -> list[dict[str, Any]]:
        """주식일별주문체결조회 — mock/real 양 모드 지원."""
        rest_urls = settings.get("kis_api.rest_urls", {})
        url_key = "virtual" if self._mock else "real"
        base_url = rest_urls.get(url_key)
        if not base_url:
            return []

        tr_id = "VTTC0081R" if self._mock else "TTTC8001R"
        today = datetime.now().strftime("%Y%m%d")
        headers = {
            "content-type": "application/json; charset=utf-8",
            "appkey": self._app_key,
            "appsecret": self._app_secret,
            "tr_id": tr_id,
            "custtype": "P",
        }
        params = {
            "CANO": self._cano,
            "ACNT_PRDT_CD": self._acnt_prdt_cd,
            "INQR_STRT_DT": today,
            "INQR_END_DT": today,
            "SLL_BUY_DVSN_CD": "00",
            "PDNO": "",
            "ORD_GNO_BRNO": "",
            "ODNO": "",
            "CCLD_DVSN": "00",
            "INQR_DVSN": "00",
            "INQR_DVSN_1": "",
            "INQR_DVSN_3": "00",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }

        all_items: list[dict[str, str]] = []
        ctx_fk = ""
        ctx_nk = ""

        await self._throttle()
        try:
            for page_num in range(10):
                p = {**params, "CTX_AREA_FK100": ctx_fk, "CTX_AREA_NK100": ctx_nk}
                tr_cont = "" if not ctx_fk else "N"

                def _fetch(p=p, tr_cont=tr_cont):
                    h = {**headers, "authorization": self._api.token.value, "tr_cont": tr_cont}
                    return requests.get(
                        f"{base_url}/uapi/domestic-stock/v1/trading/inquire-daily-ccld",
                        headers=h, params=p, timeout=10,
                    )

                resp = await asyncio.to_thread(self._retry_on_token_expired_resp, _fetch)
                data = resp.json()
                if data.get("rt_cd") != "0":
                    logger.warning("kis_broker.trade_history_api_error", msg=data.get("msg1", ""), code=data.get("msg_cd", ""))
                    break

                page_items = data.get("output1", [])
                all_items.extend(page_items)

                resp_cont = resp.headers.get("tr_cont", "")
                has_next = resp_cont in ("F", "M")

                if page_num == 0:
                    if len(page_items) == self._last_ccld_first_page and has_next == self._last_ccld_has_next and not has_next:
                        logger.debug("kis_broker.trade_no_change", count=len(page_items))
                        return []
                    self._last_ccld_first_page = len(page_items)
                    self._last_ccld_has_next = has_next

                if not has_next:
                    break
                ctx_fk_raw = data.get("ctx_area_fk100", "")
                ctx_nk_raw = data.get("ctx_area_nk100", "")
                ctx_fk = ctx_fk_raw.strip()
                ctx_nk = ctx_nk_raw.strip()
                if not ctx_fk and not ctx_nk:
                    break
                await self._throttle()
            trades = self._parse_ccld_trades(all_items)
            logger.info("kis_broker.trade_history_fetched", count=len(trades))
            return trades
        except Exception as e:
            logger.error("kis_broker.trade_history_failed", error=str(e))
            return []

    def _parse_ccld_trades(self, items: list[dict[str, str]]) -> list[dict[str, Any]]:
        trades: list[dict[str, Any]] = []
        for item in items:
            side_cd = item.get("sll_buy_dvsn_cd", "")
            if not side_cd:
                continue
            tot_ccld_qty = int(item.get("tot_ccld_qty", "0"))
            if tot_ccld_qty == 0:
                continue

            trades.append({
                "order_no": item.get("odno", ""),
                "order_date": item.get("ord_dt", ""),
                "symbol": item.get("pdno", ""),
                "name": item.get("prdt_name", ""),
                "side": "sell" if side_cd == "01" else "buy",
                "ord_qty": int(item.get("ord_qty", "0")),
                "ord_price": int(item.get("ord_unpr", "0")),
                "ord_time": item.get("ord_tmd", ""),
                "tot_ccld_qty": tot_ccld_qty,
                "avg_price": int(item.get("avg_prvs", "0")),
                "tot_ccld_amt": int(item.get("tot_ccld_amt", "0")),
                "rmn_qty": int(item.get("rmn_qty", "0")),
                "orgn_order_no": item.get("orgn_odno", ""),
                "ord_dvsn_cd": item.get("ord_dvsn_cd", ""),
                "cncl_yn": item.get("cncl_yn", ""),
            })
        return trades

    async def get_top_volume_stocks(self, count: int = 30) -> list[dict[str, Any]]:
        if not self._connected or self._api is None:
            return []

        rest_urls = settings.get("kis_api.rest_urls", {})
        base_url = rest_urls.get("real")
        if not base_url:
            raise RuntimeError("kis_api.rest_urls.real 설정이 필요합니다 (settings.toml)")
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": self._api.token.value,
            "appkey": self._app_key,
            "appsecret": self._app_secret,
            "tr_id": "FHPST01710000",
            "custtype": "P",
        }
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_COND_SCR_DIV_CODE": "20171",
            "FID_INPUT_ISCD": "0000",
            "FID_DIV_CLS_CODE": "0",
            "FID_BLNG_CLS_CODE": "0",
            "FID_TRGT_CLS_CODE": "111111111",
            "FID_TRGT_EXLS_CLS_CODE": "0000000000",
            "FID_INPUT_PRICE_1": "0",
            "FID_INPUT_PRICE_2": "0",
            "FID_VOL_CNT": "0",
            "FID_INPUT_DATE_1": "",
        }
        for attempt in range(3):
            try:
                await asyncio.sleep(0.1)
                resp = requests.get(
                    f"{base_url}/uapi/domestic-stock/v1/quotations/volume-rank",
                    headers=headers,
                    params=params,
                    timeout=10,
                )
                if resp.status_code == 429:
                    logger.warning("kis_broker.rate_limited", attempt=attempt + 1)
                    await asyncio.sleep(1)
                    continue
                if resp.status_code >= 400:
                    try:
                        body = resp.json()
                        logger.error("kis_broker.api_error", status=resp.status_code, msg_cd=body.get("msg_cd", ""), msg=body.get("msg1", ""))
                    except Exception:
                        logger.error("kis_broker.api_error", status=resp.status_code, body=resp.text[:500])
                    resp.raise_for_status()
                data = resp.json()
                output = data.get("output", [])

                stocks: list[dict[str, Any]] = []
                for item in output[:count]:
                    symbol = item.get("mksc_shrn_iscd", "")
                    if not symbol:
                        continue
                    stocks.append({
                        "symbol": symbol,
                        "name": item.get("hts_kor_isnm", ""),
                        "volume": int(item.get("acml_vol", 0)),
                        "price": Decimal(item.get("stck_prpr", "0")),
                        "change_rate": float(item.get("prdy_ctrt", "0")),
                        "volume_turnover": float(item.get("vol_tnrt", "0")),
                    })
                logger.info("kis_broker.top_volume_fetched", count=len(stocks))
                return stocks
            except Exception as e:
                logger.error("kis_broker.top_volume_failed", error=str(e), attempt=attempt + 1)
                if attempt < 2:
                    await asyncio.sleep(1)
        return []

    async def subscribe_market_data(
        self, symbols: list[str], callback: Callable[..., Any]
    ) -> None:
        logger.warning("kis_broker.websocket_not_supported", note="pykis 0.7 REST only")
