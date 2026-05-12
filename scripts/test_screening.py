"""자동 종목 스크리닝 테스트.

Usage:
    python scripts/test_screening.py          # MockBroker (기본)
    python scripts/test_screening.py --real    # KIS 모의투자 API
"""

import asyncio
import sys

from scalpy.config import settings
from scalpy.screening import StockScreener


async def main() -> None:
    use_real = "--real" in sys.argv

    if use_real:
        from scalpy.broker.kis import KISBroker
        print("[스크리닝 테스트] 모드: KIS 모의투자 API")
        broker = KISBroker(
            app_key=settings.kis_app_key,
            app_secret=settings.kis_app_secret,
            account_no=settings.kis_account_no,
            mock=True,
        )
    else:
        from scalpy.broker.mock import MockBroker
        print("[스크리닝 테스트] 모드: MockBroker")
        broker = MockBroker()

    await broker.connect()

    screening_cfg = settings.get("screening", {})
    screener = StockScreener(
        broker=broker,
        max_stocks=screening_cfg.get("max_stocks", 5),
        min_change_rate=screening_cfg.get("min_change_rate", 2.0),
        min_volume=screening_cfg.get("min_volume", 100_000),
    )

    print(f"\n설정: max_stocks={screener._max_stocks}, min_change_rate={screener._min_change_rate}, min_volume={screener._min_volume}")

    print("\n--- 거래량 상위 종목 조회 ---")
    raw_stocks = await broker.get_top_volume_stocks(30)
    for i, s in enumerate(raw_stocks[:10], 1):
        cr = s.get("change_rate", 0.0)
        print(f"  {i:2d}. {s['symbol']} {s['name']:8s} | 거래량 {s['volume']:>12,} | 등락률 {cr:+.2f}% | 현재가 {s['price']:>10,}")

    print("\n--- 스크리닝 결과 ---")
    result = await screener.scan()
    for i, sym in enumerate(result, 1):
        name = next((s["name"] for s in raw_stocks if s["symbol"] == sym), sym)
        print(f"  {i}. {sym} ({name})")

    print(f"\n선별 종목 수: {len(result)}")

    await broker.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
