"""KIS WebSocket 실시간 시세 수신 테스트."""

import asyncio
from decimal import Decimal

from scalpy.config import settings
from scalpy.data.stream import MarketDataStream


async def on_tick(symbol: str, price: Decimal, volume: int) -> None:
    print(f"[체결] {symbol} | {price:,}원 | {volume}주")


async def on_orderbook(
    symbol: str,
    asks: list[tuple[Decimal, int]],
    bids: list[tuple[Decimal, int]],
) -> None:
    print(f"[호가] {symbol} | 매도1 {asks[0][0]:,}({asks[0][1]}) | 매수1 {bids[0][0]:,}({bids[0][1]})")


async def main() -> None:
    stream = MarketDataStream(
        app_key=settings.kis_app_key,
        app_secret=settings.kis_app_secret,
        mock=True,
    )
    stream.on_tick(on_tick)
    stream.on_orderbook(on_orderbook)

    symbols = ["005930"]
    await stream.start(symbols)
    print(f"구독 시작: {symbols} (Ctrl+C로 종료)")

    try:
        while stream.is_running:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        await stream.stop()
        print("종료")


if __name__ == "__main__":
    asyncio.run(main())
