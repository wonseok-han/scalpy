import asyncio
import json
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import requests
import structlog

from scalpy.broker.base import BaseBroker
from scalpy.core.enums import OrderStatus, Side
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
        self._app_key = app_key
        self._app_secret = app_secret
        self._account_no = account_no
        self._mock = mock
        self._connected = False
        self._api: Any = None

    async def connect(self) -> None:
        try:
            from pykis import Api, DomainInfo
        except ImportError as e:
            raise AuthenticationError("pykis 패키지가 설치되지 않았습니다") from e

        domain = DomainInfo("virtual" if self._mock else "real")
        account_code = self._account_no[:8]
        product_code = self._account_no[8:].lstrip("-")

        self._api = Api(
            key_info={"appkey": self._app_key, "appsecret": self._app_secret},
            domain_info=domain,
            account_info={"account_code": account_code, "product_code": product_code},
        )
        self._load_or_create_token()
        self._connected = True
        mode = "모의투자" if self._mock else "실거래"
        logger.info("kis_broker.connected", mode=mode)

    def _load_or_create_token(self) -> None:
        if _TOKEN_PATH.exists():
            data = json.loads(_TOKEN_PATH.read_text())
            expires = datetime.fromisoformat(data["valid_until"])
            if expires > datetime.now():
                self._api.token.value = data["value"]
                self._api.token.valid_until = expires
                logger.info("kis_broker.token_cached")
                return

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

        try:
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

    async def get_positions(self) -> list[Position]:
        if not self._connected or self._api is None:
            return []

        df = self._api.get_kr_stock_balance()
        positions: list[Position] = []
        for _, row in df.iterrows():
            qty = int(row.get("보유수량", 0))
            if qty == 0:
                continue
            positions.append(
                Position(
                    symbol=str(row.get("종목명", "")),
                    side=Side.BUY,
                    quantity=qty,
                    avg_price=Decimal(str(row.get("매입단가", 0))),
                    current_price=Decimal(str(row.get("현재가", 0))),
                    strategy="manual",
                    opened_at=datetime.now(),
                )
            )
        return positions

    async def get_balance(self) -> Decimal:
        if not self._connected or self._api is None:
            return Decimal("0")

        deposit = self._api.get_kr_deposit()
        return Decimal(str(deposit))

    async def get_top_volume_stocks(self, count: int = 30) -> list[dict[str, Any]]:
        if not self._connected or self._api is None:
            return []

        # 거래량 순위 API는 모의투자 서버 미지원 — 실거래 서버 조회 전용
        base_url = "https://openapi.koreainvestment.com:9443"
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self._api.token.value}",
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
