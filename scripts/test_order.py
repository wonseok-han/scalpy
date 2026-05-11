"""KIS 모의투자 매수/매도 테스트 스크립트."""

import asyncio
from decimal import Decimal

from scalpy.broker.kis import KISBroker
from scalpy.config import settings
from scalpy.core.enums import OrderType, Side
from scalpy.core.models import Order

DELAY = 1.0


async def main() -> None:
    broker = KISBroker(
        settings.kis_app_key,
        settings.kis_app_secret,
        settings.kis_account_no,
        mock=True,
    )
    await broker.connect()

    balance = await broker.get_balance()
    print(f"매수 전 예수금: {balance:,}원")
    await asyncio.sleep(DELAY)

    price = broker._api.get_kr_current_price("005930")
    print(f"삼성전자 현재가: {price:,}원")
    await asyncio.sleep(DELAY)

    buy_order = Order(
        symbol="005930",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        price=Decimal(str(price)),
        quantity=1,
        strategy="test",
    )
    result = await broker.place_order(buy_order)
    print(f"매수 결과: {result.status.value}")
    await asyncio.sleep(DELAY)

    balance = await broker.get_balance()
    print(f"매수 후 예수금: {balance:,}원")
    await asyncio.sleep(DELAY)

    await broker.sync_positions()
    positions = broker.positions.all()
    print(f"보유 종목: {len(positions)}개")
    for p in positions:
        print(f"  {p.symbol} | {p.quantity}주 | 평단 {p.avg_price:,}원 | 현재가 {p.current_price:,}원")

    await broker.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
