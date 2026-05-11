import asyncio
import itertools
from datetime import datetime

import structlog
from fastapi import APIRouter
from pydantic import BaseModel

from scalpy.backtest.fetcher import fetch_and_store, get_stock_names, screen_top_volume
from scalpy.backtest.runner import run_backtest
from scalpy.backtest.schema import Candle, get_engine

logger = structlog.get_logger()

router = APIRouter(prefix="/api/backtest")

_running = False
_progress: dict = {"status": "idle"}


class FetchRequest(BaseModel):
    symbols: list[str]
    days: int = 6


class RunRequest(BaseModel):
    symbols: list[str]
    balance: int = 500_000
    stop_loss: float = 0.005
    take_profit: float = 0.01
    max_qty: int = 100
    max_positions: int = 3
    date: str | None = None
    strategies: list[str] | None = None
    strategy_params: dict[str, dict] | None = None


class OptimizeRequest(BaseModel):
    symbols: list[str]
    balance: int = 500_000
    max_qty: int = 100
    date: str | None = None
    strategies: list[str] | None = None
    stop_losses: list[float] | None = None
    take_profits: list[float] | None = None
    max_positions_list: list[int] | None = None
    strategy_grids: dict[str, dict[str, list]] | None = None


@router.get("/screen")
async def screen(count: int = 10, max_price: int = 0) -> dict:
    stocks = await asyncio.to_thread(screen_top_volume, count, 1.0, max_price)
    return {"stocks": stocks}


@router.get("/info")
async def info() -> dict:
    from sqlalchemy import func, select
    from sqlalchemy.orm import Session

    try:
        engine = get_engine()
    except RuntimeError:
        return {"rows": []}

    def _query():
        with Session(engine) as session:
            stmt = select(
                Candle.symbol,
                func.count(Candle.id),
                func.min(Candle.dt),
                func.max(Candle.dt),
            ).group_by(Candle.symbol)
            return session.execute(stmt).all()

    rows = await asyncio.to_thread(_query)
    symbols = [r[0] for r in rows]
    names = await asyncio.to_thread(get_stock_names, symbols) if symbols else {}
    return {
        "rows": [
            {
                "symbol": symbol,
                "name": names.get(symbol, symbol),
                "count": count,
                "min_dt": str(min_dt),
                "max_dt": str(max_dt),
            }
            for symbol, count, min_dt, max_dt in rows
        ]
    }


@router.post("/fetch")
async def fetch(req: FetchRequest) -> dict:
    global _running, _progress
    if _running:
        return {"error": "already running"}
    _running = True
    _progress = {"status": "fetching", "symbols": req.symbols, "total": 0}
    try:
        total = await asyncio.to_thread(fetch_and_store, req.symbols, req.days)
        _progress = {"status": "done", "total": total}
        return {"total": total}
    except Exception as e:
        _progress = {"status": "error", "error": str(e)}
        return {"error": str(e)}
    finally:
        _running = False


@router.post("/run")
async def run(req: RunRequest) -> dict:
    global _running, _progress
    if _running:
        return {"error": "already running"}
    _running = True
    _progress = {"status": "running"}

    kwargs = {
        "initial_balance": req.balance,
        "stop_loss_ratio": req.stop_loss,
        "take_profit_ratio": req.take_profit,
        "max_position_size": req.max_qty,
        "max_open_positions": req.max_positions,
    }
    if req.date:
        d = datetime.strptime(req.date, "%Y-%m-%d")
        kwargs["start_date"] = d
        kwargs["end_date"] = d.replace(hour=23, minute=59, second=59)
    if req.strategies:
        kwargs["enabled_strategies"] = req.strategies
    if req.strategy_params:
        kwargs["strategy_params"] = req.strategy_params

    try:
        result = await run_backtest(req.symbols, **kwargs)
        _progress = {"status": "done"}
        return result
    except Exception as e:
        _progress = {"status": "error", "error": str(e)}
        return {"error": str(e)}
    finally:
        _running = False


_STRATEGY_GRIDS_DEFAULT: dict[str, dict[str, list]] = {
    "ma_cross": {
        "short_window": [3, 5, 7],
        "long_window": [15, 20, 30],
    },
    "bollinger": {
        "window": [15, 20, 25],
        "num_std": [1.5, 2.0, 2.5],
    },
    "rsi": {
        "window": [10, 14, 20],
        "oversold": [25, 30, 35],
        "overbought": [65, 70, 75],
    },
    "vwap": {
        "deviation_threshold": [0.003, 0.005, 0.007, 0.01],
    },
}


def _build_strategy_combos(
    strategies: list[str],
    grids: dict[str, dict[str, list]],
) -> list[tuple[str, dict]]:
    """전략별 파라미터 그리드 → (전략명, 파라미터) 리스트. 전략별 개별 테스트."""
    result: list[tuple[str, dict]] = []
    for name in strategies:
        grid = grids.get(name)
        if not grid:
            result.append((name, {}))
            continue
        keys = list(grid.keys())
        values = list(grid.values())
        for combo in itertools.product(*values):
            result.append((name, dict(zip(keys, combo))))
    return result


@router.get("/strategies")
async def list_strategies() -> dict:
    from scalpy.main import build_registry
    reg = build_registry()
    return {
        "strategies": [
            {
                "name": s.name,
                "display_name": s.display_name,
                "params": {
                    k: v for k, v in vars(s).items()
                    if not k.startswith("_") and k not in ("name", "display_name", "description", "enabled", "cooldown_seconds")
                },
            }
            for s in reg.all()
            if s.name != "orderbook"
        ]
    }


async def _run_optimize(
    symbols: list[str],
    kwargs_base: dict,
    strat_combos: list[tuple[str, dict]],
    risk_combos: list[tuple[float, float, int]],
    total_combos: int,
) -> None:
    global _running, _progress
    results = []
    current = 0
    try:
        for strat_name, strat_param in strat_combos:
            for sl, tp, mp in risk_combos:
                current += 1
                _progress["current"] = current
                sp = {strat_name: strat_param} if strat_param else {}
                kwargs = {
                    **kwargs_base,
                    "stop_loss_ratio": sl,
                    "take_profit_ratio": tp,
                    "max_open_positions": mp,
                    "enabled_strategies": [strat_name],
                    "strategy_params": sp,
                }
                result = await run_backtest(symbols, **kwargs)
                if "error" not in result:
                    strat_summary = {strat_name: {k: round(v, 4) if isinstance(v, float) else v for k, v in strat_param.items()}} if strat_param else {strat_name: {}}
                    results.append({
                        "strategy": strat_name,
                        "stop_loss": sl,
                        "take_profit": tp,
                        "max_positions": mp,
                        "strategies": strat_summary,
                        "pnl": result["pnl"],
                        "pnl_pct": result["pnl_pct"],
                        "win_rate": result["win_rate"],
                        "total_trades": result["total_trades"],
                        "total_fees": result["total_fees"],
                    })
                await asyncio.sleep(0)

        seen = set()
        deduped = []
        results.sort(key=lambda x: x["pnl"], reverse=True)
        for r in results:
            key = (r["strategy"], r["pnl"], r["win_rate"], r["total_trades"])
            if key not in seen:
                seen.add(key)
                deduped.append(r)
        _progress = {"status": "done", "total": total_combos, "results": deduped}
    except Exception as e:
        _progress = {"status": "error", "error": str(e)}
    finally:
        _running = False


@router.post("/optimize")
async def optimize(req: OptimizeRequest) -> dict:
    global _running, _progress
    if _running:
        return {"error": "already running"}
    _running = True

    sl_values = req.stop_losses or [0.003, 0.005, 0.007, 0.01]
    tp_values = req.take_profits or [0.005, 0.007, 0.01, 0.015, 0.02]
    mp_values = req.max_positions_list or [2, 3, 5]

    strategies = req.strategies or ["ma_cross", "bollinger", "rsi", "vwap"]
    strat_grids = req.strategy_grids or {k: v for k, v in _STRATEGY_GRIDS_DEFAULT.items() if k in strategies}
    strat_combos = _build_strategy_combos(strategies, strat_grids)

    risk_combos = [(sl, tp, mp) for sl, tp, mp in itertools.product(sl_values, tp_values, mp_values) if tp > sl]
    total_combos = len(risk_combos) * len(strat_combos)

    _progress = {"status": "optimizing", "current": 0, "total": total_combos, "results": []}

    kwargs_base: dict = {"initial_balance": req.balance, "max_position_size": req.max_qty}
    if req.date:
        d = datetime.strptime(req.date, "%Y-%m-%d")
        kwargs_base["start_date"] = d
        kwargs_base["end_date"] = d.replace(hour=23, minute=59, second=59)

    asyncio.create_task(_run_optimize(
        req.symbols, kwargs_base, strat_combos, risk_combos, total_combos,
    ))
    return {"started": True, "total_combos": total_combos}


@router.get("/progress")
async def progress() -> dict:
    return _progress
