import asyncio
import itertools
from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter
from pydantic import BaseModel

from scalpy.backtest.quant_runner import run_quant_backtest
from scalpy.config import settings

logger = structlog.get_logger()

router = APIRouter(prefix="/api/quant/backtest")

_running = False
_progress: dict = {"status": "idle"}

_QUANT_STRATEGIES = ["momentum", "mean_reversion", "factor"]


class RunRequest(BaseModel):
    symbols: list[str]
    balance: int = 1_000_000
    stop_loss: float = 0.03
    take_profit: float = 0.05
    max_qty: int = 200
    max_positions: int = 5
    interval: str = "1d"
    period: str = "3mo"
    start_date: str | None = None
    end_date: str | None = None
    strategies: list[str] | None = None
    strategy_params: dict[str, dict] | None = None


class OptimizeRequest(BaseModel):
    symbols: list[str]
    balance: int = 1_000_000
    max_qty: int = 200
    interval: str = "1d"
    strategies: list[str] | None = None
    stop_losses: list[float] | None = None
    take_profits: list[float] | None = None
    max_positions_list: list[int] | None = None
    strategy_grids: dict[str, dict[str, list]] | None = None


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
                    k: v
                    for k, v in vars(s).items()
                    if not k.startswith("_")
                    and k not in ("name", "display_name", "description", "enabled", "cooldown_seconds")
                },
            }
            for s in reg.all()
            if s.name in _QUANT_STRATEGIES
        ]
    }


@router.get("/symbols")
async def available_symbols() -> dict:
    db_url = settings.get("database_url", "")
    if not db_url:
        return {"symbols": []}

    from sqlalchemy import create_engine, func, select
    from sqlalchemy.orm import Session

    from scalpy.data.schema import OhlcvRow

    engine = create_engine(db_url)
    with Session(engine) as session:
        rows = session.execute(
            select(
                OhlcvRow.symbol,
                func.count(OhlcvRow.id),
                func.min(OhlcvRow.dt),
                func.max(OhlcvRow.dt),
            )
            .where(OhlcvRow.interval == "1d")
            .group_by(OhlcvRow.symbol)
        ).all()

    return {
        "symbols": [
            {
                "symbol": sym,
                "count": cnt,
                "min_dt": str(min_dt),
                "max_dt": str(max_dt),
            }
            for sym, cnt, min_dt, max_dt in rows
        ]
    }


@router.post("/fetch")
async def fetch_ohlcv(body: dict[str, Any] | None = None) -> dict:
    db_url = settings.get("database_url", "")
    if not db_url:
        return {"error": "database_url not configured"}

    from scalpy.data.ohlcv import OhlcvRepository

    params = body or {}
    symbols = params.get("symbols", [])
    interval = params.get("interval", "1d")
    period = params.get("period", "3mo")

    if not symbols:
        return {"error": "symbols required"}

    repo = OhlcvRepository(db_url)
    repo.create_tables()
    total = repo.bulk_fetch(symbols, interval=interval, period=period)
    return {"success": True, "rows_added": total}


@router.post("/run")
async def run(req: RunRequest) -> dict:
    global _running, _progress
    if _running:
        return {"error": "already running"}

    db_url = settings.get("database_url", "")
    if not db_url:
        return {"error": "database_url not configured"}

    _running = True
    _progress = {"status": "running"}

    from scalpy.data.ohlcv import OhlcvRepository

    repo = OhlcvRepository(db_url)
    repo.create_tables()
    repo.bulk_fetch(req.symbols, interval=req.interval, period=req.period)

    kwargs: dict[str, Any] = {
        "db_url": db_url,
        "initial_balance": req.balance,
        "interval": req.interval,
        "stop_loss_ratio": req.stop_loss,
        "take_profit_ratio": req.take_profit,
        "max_position_size": req.max_qty,
        "max_open_positions": req.max_positions,
    }
    if req.start_date:
        kwargs["start_date"] = datetime.strptime(req.start_date, "%Y-%m-%d")
    if req.end_date:
        kwargs["end_date"] = datetime.strptime(req.end_date, "%Y-%m-%d").replace(
            hour=23, minute=59, second=59
        )
    if req.strategies:
        kwargs["enabled_strategies"] = req.strategies
    if req.strategy_params:
        kwargs["strategy_params"] = req.strategy_params

    try:
        result = await run_quant_backtest(req.symbols, **kwargs)
        _progress = {"status": "done"}
        return result
    except Exception as e:
        _progress = {"status": "error", "error": str(e)}
        return {"error": str(e)}
    finally:
        _running = False


_QUANT_GRIDS_DEFAULT: dict[str, dict[str, list]] = {
    "momentum": {
        "lookback": [20, 30, 50],
        "volume_multiplier": [1.5, 2.0, 3.0],
        "breakout_pct": [0.003, 0.005, 0.01],
    },
    "mean_reversion": {
        "window": [15, 20, 30],
        "num_std": [1.5, 2.0, 2.5],
    },
    "factor": {
        "lookback": [20, 30, 50],
        "buy_threshold": [0.55, 0.65, 0.75],
    },
}


async def _run_optimize(
    symbols: list[str],
    db_url: str,
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
                    "db_url": db_url,
                    "stop_loss_ratio": sl,
                    "take_profit_ratio": tp,
                    "max_open_positions": mp,
                    "enabled_strategies": [strat_name],
                    "strategy_params": sp,
                }
                result = await run_quant_backtest(symbols, **kwargs)
                if "error" not in result:
                    results.append({
                        "strategy": strat_name,
                        "stop_loss": sl,
                        "take_profit": tp,
                        "max_positions": mp,
                        "strategies": {strat_name: strat_param} if strat_param else {},
                        "pnl": result["pnl"],
                        "pnl_pct": result["pnl_pct"],
                        "win_rate": result["win_rate"],
                        "total_trades": result["total_trades"],
                        "total_fees": result["total_fees"],
                    })
                await asyncio.sleep(0)

        results.sort(key=lambda x: x["pnl"], reverse=True)
        seen: set[tuple] = set()
        deduped = []
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

    db_url = settings.get("database_url", "")
    if not db_url:
        return {"error": "database_url not configured"}

    _running = True

    sl_values = req.stop_losses or [0.02, 0.03, 0.04, 0.05]
    tp_values = req.take_profits or [0.03, 0.05, 0.07, 0.10]
    mp_values = req.max_positions_list or [3, 5, 7]

    strategies = req.strategies or _QUANT_STRATEGIES
    strat_grids = req.strategy_grids or {
        k: v for k, v in _QUANT_GRIDS_DEFAULT.items() if k in strategies
    }

    strat_combos: list[tuple[str, dict]] = []
    for name in strategies:
        grid = strat_grids.get(name)
        if not grid:
            strat_combos.append((name, {}))
            continue
        keys = list(grid.keys())
        values = list(grid.values())
        for combo in itertools.product(*values):
            strat_combos.append((name, dict(zip(keys, combo))))

    risk_combos = [
        (sl, tp, mp)
        for sl, tp, mp in itertools.product(sl_values, tp_values, mp_values)
        if tp > sl
    ]
    total_combos = len(risk_combos) * len(strat_combos)

    _progress = {"status": "optimizing", "current": 0, "total": total_combos, "results": []}

    kwargs_base: dict = {
        "initial_balance": req.balance,
        "max_position_size": req.max_qty,
        "interval": req.interval,
    }

    asyncio.create_task(
        _run_optimize(req.symbols, db_url, kwargs_base, strat_combos, risk_combos, total_combos)
    )
    return {"started": True, "total_combos": total_combos}


@router.get("/progress")
async def progress() -> dict:
    return _progress
