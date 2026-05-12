import asyncio
from datetime import datetime
from decimal import Decimal

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from scalpy.broker.mock import MockBroker
from scalpy.data.ohlcv import OhlcvRepository
from scalpy.data.schema import OhlcvRow
from scalpy.main import build_registry
from scalpy.trading.engine import TradingEngine
from scalpy.trading.risk import RiskManager

logger = structlog.get_logger()

_QUANT_STRATEGIES = {"momentum", "mean_reversion", "factor"}


def _load_ohlcv(
    db_url: str,
    symbols: list[str],
    interval: str = "1d",
    start_date: datetime | None = None,
    end_date: datetime | None = None,
) -> list[OhlcvRow]:
    from sqlalchemy import create_engine

    engine = create_engine(db_url)
    with Session(engine) as session:
        stmt = (
            select(OhlcvRow)
            .where(OhlcvRow.symbol.in_(symbols), OhlcvRow.interval == interval)
        )
        if start_date:
            stmt = stmt.where(OhlcvRow.dt >= start_date)
        if end_date:
            stmt = stmt.where(OhlcvRow.dt <= end_date)
        stmt = stmt.order_by(OhlcvRow.dt)
        return list(session.scalars(stmt).all())


async def run_quant_backtest(
    symbols: list[str],
    db_url: str,
    initial_balance: int = 1_000_000,
    interval: str = "1d",
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    stop_loss_ratio: float = 0.03,
    take_profit_ratio: float = 0.05,
    max_position_size: int = 200,
    max_open_positions: int = 5,
    enabled_strategies: list[str] | None = None,
    strategy_params: dict[str, dict] | None = None,
) -> dict:
    candles = _load_ohlcv(db_url, symbols, interval, start_date, end_date)
    if not candles:
        return {"error": "OHLCV 데이터가 없습니다. 먼저 데이터를 수집하세요."}

    broker = MockBroker(initial_balance=Decimal(str(initial_balance)))
    await broker.connect()

    registry = build_registry()
    strategies = enabled_strategies or list(_QUANT_STRATEGIES)
    for s in registry.all():
        s.enabled = s.name in strategies
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

    ohlcv_repo = OhlcvRepository(db_url)
    for sym in symbols:
        prefill = ohlcv_repo.get_candles(sym, interval=interval, limit=60)
        if prefill:
            engine.prefill_strategies(sym, prefill)

    total_candles = len(candles)

    logger.info(
        "quant_backtest.started",
        symbols=symbols,
        candles=total_candles,
        interval=interval,
        period=f"{candles[0].dt} ~ {candles[-1].dt}",
    )

    for i, candle in enumerate(candles):
        await engine.on_tick(
            candle.symbol,
            Decimal(str(candle.close)),
            int(candle.volume),
        )
        if (i + 1) % 200 == 0:
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
            b for b in buy_orders
            if b.symbol == sell.symbol and b.filled_at and sell.filled_at and b.filled_at < sell.filled_at
        ]
        if matching_buys:
            if sell.price > matching_buys[-1].price:
                wins += 1
            else:
                losses += 1

    win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0

    perf = engine._performance.all_stats()

    result = {
        "period": f"{candles[0].dt} ~ {candles[-1].dt}",
        "interval": interval,
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
        "open_positions": len(engine.positions.all()),
        "strategies": [s.name for s in registry.enabled()],
        "strategy_performance": perf,
    }

    logger.info("quant_backtest.complete", **{k: v for k, v in result.items() if k != "strategy_performance"})
    await broker.disconnect()
    return result
