"""KIS API 연결 테스트 스크립트."""

import asyncio

from scalpy.broker.kis import KISBroker
from scalpy.config import settings


async def main() -> None:
    broker = KISBroker(
        settings.kis_app_key,
        settings.kis_app_secret,
        settings.kis_account_no,
        mock=True,
    )

    await broker.connect()
    print("연결 성공")

    balance = await broker.get_balance()
    print(f"모의투자 예수금: {balance:,}원")

    positions = await broker.get_positions()
    print(f"보유 종목: {len(positions)}개")
    for p in positions:
        print(f"  {p.symbol} | {p.quantity}주 | 평단 {p.avg_price:,}원")

    await broker.disconnect()
    print("연결 종료")


if __name__ == "__main__":
    asyncio.run(main())
