from collections.abc import Callable
from decimal import Decimal
from typing import Any

import structlog

from scalpy.broker.base import BaseBroker
from scalpy.core.enums import OrderStatus
from scalpy.core.exceptions import AuthenticationError
from scalpy.core.models import Order, Position

logger = structlog.get_logger()


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

    async def connect(self) -> None:
        try:
            from pykis import KoreaInvestment  # noqa: F811
        except ImportError as e:
            raise AuthenticationError("pykis 패키지가 설치되지 않았습니다") from e

        self._kis = KoreaInvestment(
            api_key=self._app_key,
            api_secret=self._app_secret,
            account_no=self._account_no,
            mock_trading=self._mock,
        )
        self._connected = True
        mode = "모의투자" if self._mock else "실거래"
        logger.info("kis_broker.connected", mode=mode)

    async def disconnect(self) -> None:
        self._connected = False
        logger.info("kis_broker.disconnected")

    async def place_order(self, order: Order) -> Order:
        if not self._connected:
            order.status = OrderStatus.REJECTED
            return order

        # TODO: pykis 주문 API 연동 (API 키 발급 후 구현)
        order.status = OrderStatus.REJECTED
        logger.warning("kis_broker.not_implemented", method="place_order")
        return order

    async def cancel_order(self, order_id: str) -> bool:
        logger.warning("kis_broker.not_implemented", method="cancel_order")
        return False

    async def get_positions(self) -> list[Position]:
        logger.warning("kis_broker.not_implemented", method="get_positions")
        return []

    async def get_balance(self) -> Decimal:
        logger.warning("kis_broker.not_implemented", method="get_balance")
        return Decimal("0")

    async def subscribe_market_data(
        self, symbols: list[str], callback: Callable[..., Any]
    ) -> None:
        logger.warning("kis_broker.not_implemented", method="subscribe_market_data")
