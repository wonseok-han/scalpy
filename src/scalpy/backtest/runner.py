import asyncio
from datetime import datetime
from decimal import Decimal

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from scalpy.backtest.schema import Candle, get_engine
from scalpy.broker.mock import MockBroker
from scalpy.main import build_registry
from scalpy.trading.engine import TradingEngine
from scalpy.trading.risk import RiskManager

logger = structlog.get_logger()


def _load_candles(
    engine,
    symbols: list[str],
    start_date: datetime | None = None,
    end_date: datetime | None = None,
) -> list[Candle]:
    with Session(engine) as session:
        stmt = select(Candle).where(Candle.symbol.in_(symbols))
        if start_date:
            stmt = stmt.where(Candle.dt >= start_date)
        if end_date:
            stmt = stmt.where(Candle.dt <= end_date)
        stmt = stmt.order_by(Candle.dt)
        return list(session.scalars(stmt).all())


async def run_backtest(
    symbols: list[str],
    initial_balance: int = 500_000,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    stop_loss_ratio: float = 0.005,
    take_profit_ratio: float = 0.01,
    max_position_size: int = 100,
    max_open_positions: int = 3,
    enabled_strategies: list[str] | None = None,
    strategy_params: dict[str, dict] | None = None,
) -> dict:
    """DB에 저장된 분봉으로 백테스트 실행.

    Returns: 결과 요약 dict.
    """
    db_engine = get_engine()
    candles = _load_candles(db_engine, symbols, start_date, end_date)
    if not candles:
        logger.warning("backtest.no_data")
        return {"error": "데이터가 없습니다. 먼저 fetch를 실행하세요."}

    broker = MockBroker(initial_balance=Decimal(str(initial_balance)))
    await broker.connect()

    registry = build_registry()
    if enabled_strategies is not None:
        for s in registry.all():
            s.enabled = s.name in enabled_strategies
    if strategy_params:
        registry.configure_all(strategy_params)
    for s in registry.all():
        s._backtest_mode = True
    risk = RiskManager(
        stop_loss_ratio=stop_loss_ratio,
        take_profit_ratio=take_profit_ratio,
        max_position_size=max_position_size,
        max_open_positions=max_open_positions,
    )
    engine = TradingEngine(broker, registry, risk)
    engine._running = True

    total_candles = len(candles)
    trade_count = 0
    prev_order_count = 0

    logger.info(
        "backtest.started",
        symbols=symbols,
        candles=total_candles,
        initial_balance=initial_balance,
        period=f"{candles[0].dt} ~ {candles[-1].dt}",
    )

    for i, candle in enumerate(candles):
        await engine.on_tick(
            candle.symbol,
            Decimal(str(candle.close)),
            int(candle.volume),
        )

        current_orders = len(engine.orders.get_history())
        if current_orders > prev_order_count:
            trade_count += current_orders - prev_order_count
            prev_order_count = current_orders

        if (i + 1) % 500 == 0:
            await asyncio.sleep(0)

    final_balance = await broker.get_balance()
    position_value = sum(
        p.current_price * p.quantity for p in engine.positions.all()
    )
    total_value = final_balance + position_value
    pnl = total_value - Decimal(str(initial_balance))
    pnl_pct = float(pnl / Decimal(str(initial_balance)) * 100)

    orders = engine.orders.get_history()
    buy_orders = [o for o in orders if o.side.value == "buy" and o.status.value == "filled"]
    sell_orders = [o for o in orders if o.side.value == "sell" and o.status.value == "filled"]

    wins = 0
    losses = 0
    for sell in sell_orders:
        matching_buys = [
            b for b in buy_orders if b.symbol == sell.symbol and b.filled_at and sell.filled_at and b.filled_at < sell.filled_at
        ]
        if matching_buys:
            buy = matching_buys[-1]
            if sell.price > buy.price:
                wins += 1
            else:
                losses += 1

    win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0

    open_positions = engine.positions.all()

    result = {
        "period": f"{candles[0].dt} ~ {candles[-1].dt}",
        "candles": total_candles,
        "initial_balance": initial_balance,
        "final_balance": int(final_balance),
        "position_value": int(position_value),
        "total_value": int(total_value),
        "pnl": int(pnl),
        "pnl_pct": round(pnl_pct, 2),
        "total_trades": len(orders),
        "buy_count": len(buy_orders),
        "sell_count": len(sell_orders),
        "wins": wins,
        "losses": losses,
        "win_rate": round(win_rate, 1),
        "total_fees": int(broker._total_fees),
        "open_positions": len(open_positions),
        "strategies": [s.name for s in registry.enabled()],
    }

    logger.info("backtest.complete", **result)
    await broker.disconnect()

    return result


def backtest(
    symbols: list[str],
    **kwargs,
) -> dict:
    return asyncio.run(run_backtest(symbols, **kwargs))
