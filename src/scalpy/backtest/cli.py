import argparse
import sys
from datetime import datetime

import structlog

structlog.configure(
    processors=[
        structlog.dev.ConsoleRenderer(),
    ],
)
logger = structlog.get_logger()


def cmd_fetch(args):
    from scalpy.backtest.fetcher import fetch_and_store, screen_top_volume

    if args.screen:
        stocks = screen_top_volume(args.screen_count)
        if not stocks:
            print("스크리닝 결과가 없습니다.")
            return
        print(f"\n거래량 상위 {len(stocks)}종목:")
        for i, s in enumerate(stocks, 1):
            print(f"  {i:>2}. {s['symbol']} {s['name']:<12} 거래량 {s['volume']:>12,}  {s['change_rate']:+.2f}%")
        symbols = [s["symbol"] for s in stocks]
        print()
    else:
        symbols = [s.strip() for s in args.symbols.split(",")]

    total = fetch_and_store(symbols, days=args.days)
    print(f"\n총 {total}건 저장 완료.")


def cmd_daily(args):
    from scalpy.backtest.fetcher import fetch_and_store, screen_top_volume

    stocks = screen_top_volume(args.screen_count)
    if not stocks:
        print("스크리닝 결과가 없습니다.")
        return
    symbols = [s["symbol"] for s in stocks[:args.top]]
    print(f"\n거래량 상위 {len(symbols)}종목 오늘 데이터 수집 + 백테스트")
    for i, s in enumerate(stocks[:args.top], 1):
        print(f"  {i:>2}. {s['symbol']} {s['name']:<12} 거래량 {s['volume']:>12,}")

    print()
    total = fetch_and_store(symbols, days=1)
    print(f"{total}건 수집 완료.\n")

    from scalpy.backtest.runner import backtest

    result = backtest(
        symbols,
        initial_balance=args.balance,
        stop_loss_ratio=args.stop_loss,
        take_profit_ratio=args.take_profit,
        max_position_size=args.max_qty,
        max_open_positions=args.max_positions,
    )

    if "error" in result:
        print(f"\n오류: {result['error']}")
        sys.exit(1)

    _print_result(result)


def cmd_run(args):
    from scalpy.backtest.runner import backtest

    if args.screen:
        from scalpy.backtest.fetcher import screen_top_volume

        stocks = screen_top_volume(args.screen_count)
        if not stocks:
            print("스크리닝 결과가 없습니다.")
            return
        symbols = [s["symbol"] for s in stocks]
        print(f"\n거래량 상위 {len(symbols)}종목으로 백테스트:")
        for i, s in enumerate(stocks, 1):
            print(f"  {i:>2}. {s['symbol']} {s['name']}")
        print()
    else:
        symbols = [s.strip() for s in args.symbols.split(",")]

    kwargs = {
        "initial_balance": args.balance,
        "stop_loss_ratio": args.stop_loss,
        "take_profit_ratio": args.take_profit,
        "max_position_size": args.max_qty,
        "max_open_positions": args.max_positions,
    }
    if args.start:
        kwargs["start_date"] = datetime.strptime(args.start, "%Y-%m-%d")
    if args.end:
        kwargs["end_date"] = datetime.strptime(args.end, "%Y-%m-%d")

    result = backtest(symbols, **kwargs)

    if "error" in result:
        print(f"\n오류: {result['error']}")
        sys.exit(1)

    _print_result(result)


def _print_result(result):
    print("\n" + "=" * 50)
    print("  백테스트 결과")
    print("=" * 50)
    print(f"  기간        : {result['period']}")
    print(f"  분봉 수     : {result['candles']:,}개")
    print(f"  활성 전략   : {', '.join(result['strategies'])}")
    print("-" * 50)
    print(f"  초기 자금   : {result['initial_balance']:>12,}원")
    print(f"  최종 현금   : {result['final_balance']:>12,}원")
    print(f"  보유 평가   : {result['position_value']:>12,}원")
    print(f"  총 평가     : {result['total_value']:>12,}원")
    pnl_sign = "+" if result["pnl"] >= 0 else ""
    print(f"  손익        : {pnl_sign}{result['pnl']:>11,}원 ({pnl_sign}{result['pnl_pct']}%)")
    print(f"  수수료 합계 : {result['total_fees']:>12,}원")
    print("-" * 50)
    print(f"  총 거래     : {result['total_trades']}건 (매수 {result['buy_count']} / 매도 {result['sell_count']})")
    print(f"  승률        : {result['win_rate']}% ({result['wins']}승 {result['losses']}패)")
    print(f"  미청산      : {result['open_positions']}건")
    print("=" * 50)


def cmd_info(args):
    from sqlalchemy import func, select
    from sqlalchemy.orm import Session

    from scalpy.backtest.schema import Candle, get_engine

    engine = get_engine()
    with Session(engine) as session:
        stmt = select(
            Candle.symbol,
            func.count(Candle.id),
            func.min(Candle.dt),
            func.max(Candle.dt),
        ).group_by(Candle.symbol)
        rows = session.execute(stmt).all()

    if not rows:
        print("저장된 데이터가 없습니다.")
        return

    print("\n" + "=" * 60)
    print("  저장된 분봉 데이터")
    print("=" * 60)
    print(f"  {'종목':>8}  {'건수':>8}  {'시작':>20}  {'종료':>20}")
    print("-" * 60)
    for symbol, count, min_dt, max_dt in rows:
        print(f"  {symbol:>8}  {count:>8,}  {min_dt}  {max_dt}")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Scalpy 백테스트")
    sub = parser.add_subparsers(dest="command")

    fetch = sub.add_parser("fetch", help="KIS API에서 분봉 데이터 수집")
    fetch.add_argument("--symbols", default="005930,000660", help="종목코드 (쉼표 구분)")
    fetch.add_argument("--days", type=int, default=6, help="수집 일수 (기본 6, 네이버 API 최대 ~6거래일)")
    fetch.add_argument("--screen", action="store_true", help="네이버 거래량 상위 종목 자동 선택")
    fetch.add_argument("--screen-count", type=int, default=10, help="스크리닝 종목 수 (기본 10)")

    run = sub.add_parser("run", help="백테스트 실행")
    run.add_argument("--symbols", default="005930,000660", help="종목코드 (쉼표 구분)")
    run.add_argument("--screen", action="store_true", help="거래량 상위 종목으로 실행")
    run.add_argument("--screen-count", type=int, default=10, help="스크리닝 종목 수")
    run.add_argument("--balance", type=int, default=500_000, help="초기 자금")
    run.add_argument("--stop-loss", type=float, default=0.005, help="손절 비율")
    run.add_argument("--take-profit", type=float, default=0.01, help="익절 비율")
    run.add_argument("--max-qty", type=int, default=100, help="종목당 최대 수량")
    run.add_argument("--max-positions", type=int, default=3, help="최대 포지션 수")
    run.add_argument("--start", help="시작일 (YYYY-MM-DD)")
    run.add_argument("--end", help="종료일 (YYYY-MM-DD)")

    daily = sub.add_parser("daily", help="오늘 하루 스크리닝 + 수집 + 백테스트")
    daily.add_argument("--screen-count", type=int, default=50, help="스크리닝 종목 수 (기본 50)")
    daily.add_argument("--top", type=int, default=10, help="상위 N종목만 백테스트 (기본 10)")
    daily.add_argument("--balance", type=int, default=500_000, help="초기 자금")
    daily.add_argument("--stop-loss", type=float, default=0.005, help="손절 비율")
    daily.add_argument("--take-profit", type=float, default=0.01, help="익절 비율")
    daily.add_argument("--max-qty", type=int, default=100, help="종목당 최대 수량")
    daily.add_argument("--max-positions", type=int, default=3, help="최대 포지션 수")

    sub.add_parser("info", help="저장된 데이터 현황 조회")

    args = parser.parse_args()
    if args.command == "fetch":
        cmd_fetch(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "daily":
        cmd_daily(args)
    elif args.command == "info":
        cmd_info(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
