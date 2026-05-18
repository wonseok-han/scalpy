"""미장 대시보드 라우트 — 기존 routes.py(국장)를 수정하지 않는 독립 구현체."""

import asyncio
from typing import Any

import structlog
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from scalpy.config import settings
from scalpy.dashboard.sse import SSEManager
from scalpy.dashboard.state import DashboardState
from scalpy.events.bus import EventBus
from scalpy.strategy.registry import StrategyRegistry

logger = structlog.get_logger()

us_router = APIRouter(prefix="/api/us")

_state: DashboardState | None = None
_sse: SSEManager | None = None
_bus: EventBus | None = None
_engine_ref: Any = None
_stream_ref: Any = None
_registry_ref: StrategyRegistry | None = None
_trade_repo_ref: Any = None
_trading_started: bool = False
_initial_start_done: bool = False
_quant_rescan_task: asyncio.Task[None] | None = None
_last_quant_scan: list[dict] = []

_SSE_EVENTS = [
    "tick.received", "order.filled", "signal.generated",
    "position.opened", "position.closed", "position.updated",
    "screening.completed", "engine.started", "engine.stopped",
    "engine.daily_init",
]

_QUANT_STRATEGIES = {"momentum", "mean_reversion", "factor", "ichimoku"}


def init_us_routes(
    state: DashboardState,
    sse: SSEManager,
    engine: Any,
    bus: EventBus | None = None,
    stream: Any = None,
    registry: StrategyRegistry | None = None,
    trade_repo: Any = None,
) -> None:
    global _state, _sse, _bus, _engine_ref, _stream_ref, _registry_ref, _trade_repo_ref
    _state = state
    _sse = sse
    _bus = bus
    _engine_ref = engine
    _stream_ref = stream
    _registry_ref = registry
    _trade_repo_ref = trade_repo

    if engine and trade_repo:
        engine.set_trade_repo(trade_repo)
        engine._performance.set_repo(trade_repo)

    if bus:
        for event in _SSE_EVENTS:
            bus.subscribe(event, _on_state_change)

    logger.info("us_routes.initialized")


def _on_state_change(data: dict[str, Any]) -> None:
    if _sse is None:
        return
    _sse.broadcast("state", _build_sse_state())


def _build_sse_state() -> dict[str, Any]:
    names = _state.symbol_names if _state else {}
    positions: list[dict[str, Any]] = []
    if _engine_ref is not None:
        for p in _engine_ref.positions.all():
            pnl_pct = getattr(p, '_pnl_pct', 0.0)
            positions.append({
                "symbol": p.symbol,
                "name": names.get(p.symbol, p.symbol),
                "quantity": p.quantity,
                "avg_price": str(p.avg_price),
                "current_price": str(p.current_price),
                "pnl": str(p.unrealized_pnl),
                "pnl_pct": round(pnl_pct, 2),
                "strategy": p.strategy,
            })

    trade_count = 0
    daily_pnl = "0"
    if _trade_repo_ref:
        try:
            daily_pnl = str(_trade_repo_ref.get_daily_pnl())
            trade_count = _trade_repo_ref.get_daily_trade_count()
        except Exception:
            pass

    invested = 0
    available_balance = "-"
    if _engine_ref is not None:
        for p in _engine_ref.positions.all():
            invested += int(p.avg_price * p.quantity)
        try:
            cash = _engine_ref._cached_available_cash
            if cash is not None:
                available_balance = str(round(float(cash - _engine_ref._pending_buy_cost), 2))
        except Exception:
            pass

    return {
        "status": {
            "running": _engine_ref._running if _engine_ref else False,
            "balance": _state.last_api_balance if _state else "-",
            "invested": str(invested),
            "available_balance": available_balance,
            "daily_pnl": daily_pnl,
            "trade_count": trade_count,
            "last_tick_at": _state.last_tick_at if _state else "",
            "position_count": len(positions),
            "screening_count": len(_state.screening_symbols) if _state else 0,
            "currency": "USD",
        },
        "positions": positions,
        "screening": {
            "symbols": _state.screening_symbols if _state else [],
            "names": _state.symbol_names if _state else {},
        },
        "market_condition": _state.market_condition if _state else {},
    }


@us_router.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "market": "us",
        "engine": _engine_ref is not None,
        "trading_started": _trading_started,
    }


@us_router.get("/status")
async def get_status() -> dict[str, Any]:
    mock = settings.get("mock", True)
    strategy_names = {s.name: s.display_name for s in _registry_ref.all()} if _registry_ref else {}
    strategy_enabled = {s.name: s.enabled for s in _registry_ref.all()} if _registry_ref else {}
    pos_count = len(_engine_ref.positions.all()) if _engine_ref else 0

    return {
        "running": _engine_ref._running if _engine_ref else False,
        "balance": _state.last_api_balance if _state else "-",
        "last_tick_at": _state.last_tick_at if _state else "",
        "position_count": pos_count,
        "screening_count": len(_state.screening_symbols) if _state else 0,
        "mock": mock,
        "market": "us",
        "currency": "USD",
        "strategies": strategy_names,
        "strategy_enabled": strategy_enabled,
        "trading_started": _trading_started,
        "market_condition": _state.market_condition if _state else {},
    }


@us_router.get("/positions")
async def get_positions() -> list[dict[str, Any]]:
    if _engine_ref is None:
        return []
    names = _state.symbol_names if _state else {}
    positions = []
    for p in _engine_ref.positions.all():
        pnl_pct = getattr(p, '_pnl_pct', 0.0)
        positions.append({
            "symbol": p.symbol,
            "name": names.get(p.symbol, p.symbol),
            "quantity": p.quantity,
            "avg_price": str(p.avg_price),
            "current_price": str(p.current_price),
            "pnl": str(p.unrealized_pnl),
            "pnl_pct": round(pnl_pct, 2),
            "strategy": p.strategy,
        })
    return positions


@us_router.get("/screening")
async def get_screening() -> dict[str, Any]:
    if not _state:
        return {"symbols": [], "names": {}}
    return {
        "symbols": _state.screening_symbols,
        "names": _state.symbol_names,
    }


@us_router.get("/signals")
async def get_signals() -> list[dict[str, Any]]:
    return _state.signals_list() if _state else []


@us_router.get("/trades")
async def get_trades() -> list[dict[str, Any]]:
    if not _trade_repo_ref:
        return []
    try:
        return _trade_repo_ref.get_trades_today()
    except Exception:
        return []


@us_router.post("/actions/start")
async def start_engine() -> dict[str, Any]:
    global _trading_started
    if _engine_ref is None:
        return {"success": False, "error": "engine not available"}
    if _trading_started:
        return {"success": True}
    try:
        if not _engine_ref._broker._connected:
            await _engine_ref._broker.connect()
        cancelled = await _engine_ref._broker.cancel_all_orders()
        if cancelled > 0:
            logger.info("us_dashboard.cleared_orders", count=cancelled)
        await _engine_ref.sync_positions()
        _engine_ref._running = True
        _engine_ref.start_background_loops()
        _trading_started = True

        _apply_strategies()
        quant_on = settings.get("strategies.quant_enabled", [])
        symbols: list[str] = []

        if quant_on:
            quant_symbols = await _quant_start()
            symbols.extend(quant_symbols)

        if not symbols:
            symbols = list(settings.get("us_trading.symbols", ["AAPL"]))

        if _stream_ref:
            held = [p.symbol for p in _engine_ref.positions.all()]
            await _stream_ref.start(list(set(symbols) | set(held)))

        await _engine_ref.update_symbols(symbols)

        if _bus:
            await _bus.emit("engine.started")
        return {"success": True, "symbols": symbols}
    except Exception as e:
        _trading_started = False
        logger.error("us_dashboard.start_failed", error=str(e))
        return {"success": False, "error": str(e)}


@us_router.post("/actions/stop")
async def stop_engine() -> dict[str, Any]:
    global _trading_started, _quant_rescan_task
    if _engine_ref is None:
        return {"success": False}
    if not _trading_started:
        return {"success": False, "error": "already stopped"}
    _engine_ref._running = False
    _engine_ref.stop_background_loops()
    _trading_started = False
    if _quant_rescan_task and not _quant_rescan_task.done():
        _quant_rescan_task.cancel()
    _quant_rescan_task = None
    if _stream_ref:
        await _stream_ref.stop()
    if _bus:
        await _bus.emit("engine.stopped")
    return {"success": True}


@us_router.post("/actions/liquidate")
async def liquidate_all() -> dict[str, Any]:
    if _engine_ref is None:
        return {"success": False}
    results = []
    for pos in list(_engine_ref.positions.all()):
        try:
            await _engine_ref._force_close(pos)
            results.append({"symbol": pos.symbol, "status": "closed"})
        except Exception as e:
            results.append({"symbol": pos.symbol, "status": "failed", "error": str(e)})
    return {"success": True, "results": results}


@us_router.post("/actions/liquidate/{symbol}")
async def liquidate_one(symbol: str) -> dict[str, Any]:
    if _engine_ref is None:
        return {"success": False}
    pos = _engine_ref.positions.get(symbol)
    if pos is None:
        return {"success": False, "error": "not found"}
    try:
        await _engine_ref._force_close(pos)
        return {"success": True, "symbol": symbol}
    except Exception as e:
        return {"success": False, "error": str(e)}


@us_router.post("/strategies/{name}/toggle")
async def toggle_strategy(name: str) -> dict[str, Any]:
    if _registry_ref is None:
        return {"success": False}
    result = _registry_ref.toggle(name)
    if result is None:
        return {"success": False, "error": "not found"}
    quant_on = [s.name for s in _registry_ref.all() if s.enabled and s.name in _QUANT_STRATEGIES]
    settings.set("strategies.quant_enabled", quant_on)
    if _sse:
        _sse.broadcast("state", _build_sse_state())
    return {"success": True, "name": name, "enabled": result}


@us_router.get("/market-condition")
async def get_market_condition_api() -> dict[str, Any]:
    if _state and _state.market_condition:
        return _state.market_condition
    from scalpy.screening.us_screener import get_market_condition
    return get_market_condition()


@us_router.get("/events")
async def sse_stream() -> StreamingResponse:
    if _sse is None:
        return StreamingResponse(iter([]), media_type="text/event-stream")
    return StreamingResponse(
        _sse.stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@us_router.get("/settings")
async def get_settings() -> dict[str, Any]:
    trading = settings.get("us_trading", {})
    risk = {}
    if _engine_ref:
        r = _engine_ref._risk
        risk = {
            "stop_loss_ratio": float(r.stop_loss_ratio),
            "take_profit_ratio": float(r.take_profit_ratio),
            "max_position_size": r.max_position_size,
            "max_open_positions": r.max_open_positions,
        }
    strats = {}
    if _registry_ref:
        for s in _registry_ref.all():
            params = {}
            for k in vars(s):
                if k.startswith("_") or k in ("name", "display_name", "enabled"):
                    continue
                v = getattr(s, k)
                if isinstance(v, (int, float, str, bool)):
                    params[k] = v
            strats[s.name] = {"display_name": s.display_name, "enabled": s.enabled, "params": params}
    return {"trading": dict(trading), "risk": risk, "strategies": strats, "market": "us"}


def _apply_strategies() -> None:
    if not _registry_ref:
        return
    quant_on = set(settings.get("strategies.quant_enabled", []))
    for s in _registry_ref.all():
        s.enabled = s.name in quant_on


async def _quant_start() -> list[str]:
    global _last_quant_scan, _quant_rescan_task
    if not _engine_ref:
        return []

    from scalpy.screening.us_screener import USQuantScreener, scan_us_market

    broker = _engine_ref._broker
    stocks = await scan_us_market(broker, count=50)
    if not stocks:
        return []

    universe = [s["symbol"] for s in stocks]
    names = {s["symbol"]: s.get("name", "") for s in stocks}
    live_data = {
        s["symbol"]: {
            "change_rate": s.get("change_rate", 0.0),
            "volume": s.get("volume", 0),
            "amount": s.get("amount", 0),
        }
        for s in stocks
    }
    if _state and names:
        _state.symbol_names.update({k: v for k, v in names.items() if v})

    from scalpy.screening.us_screener import get_market_condition
    if _state:
        _state.market_condition = get_market_condition()

    screener = USQuantScreener(
        max_stocks=settings.get("quant.max_stocks", 10),
        momentum_days=settings.get("quant.momentum_days", 10),
        min_avg_volume=settings.get("quant.min_avg_volume", 100_000),
        min_momentum=settings.get("quant.min_momentum", 0.0),
    )
    held = [p.symbol for p in _engine_ref.positions.all()]
    selected = screener.scan(universe, held_symbols=held, live_data=live_data)
    _last_quant_scan = screener.get_last_scan()

    return selected
