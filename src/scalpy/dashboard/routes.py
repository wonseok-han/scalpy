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

router = APIRouter(prefix="/api")

_state: DashboardState | None = None
_sse: SSEManager | None = None
_bus: EventBus | None = None
_engine_ref: Any = None
_screener_ref: Any = None
_stream_ref: Any = None
_registry_ref: StrategyRegistry | None = None
_trading_started: bool = False

_SSE_EVENTS = [
    "tick.received", "order.filled", "signal.generated",
    "position.opened", "position.closed", "position.updated",
    "screening.completed", "engine.started", "engine.stopped",
]


def init_routes(
    state: DashboardState,
    sse: SSEManager,
    engine: Any,
    bus: EventBus | None = None,
    screener: Any = None,
    stream: Any = None,
    registry: StrategyRegistry | None = None,
) -> None:
    global _state, _sse, _bus, _engine_ref, _screener_ref, _stream_ref, _registry_ref
    _state = state
    _sse = sse
    _bus = bus
    _engine_ref = engine
    _screener_ref = screener
    _stream_ref = stream
    _registry_ref = registry

    if bus:
        for event in _SSE_EVENTS:
            bus.subscribe(event, _on_state_change)

    logger.info("routes.initialized", engine=engine is not None, screener=screener is not None, stream=stream is not None)


def _on_state_change(data: dict[str, Any]) -> None:
    if _sse is None:
        return
    _sse.broadcast("state", _build_realtime_state())


def _build_realtime_state() -> dict[str, Any]:
    """SSE 푸시용 — API 호출 없이 인메모리 데이터만 사용."""
    mock = settings.get("mock", True)
    strategy_names = {s.name: s.display_name for s in _registry_ref.all()} if _registry_ref else {}
    strategy_enabled = {s.name: s.enabled for s in _registry_ref.all()} if _registry_ref else {}
    names = _state.symbol_names if _state else {}

    positions: list[dict[str, Any]] = []
    if _engine_ref is not None:
        for p in _engine_ref.positions.all():
            pnl = p.unrealized_pnl
            pnl_pct = float(pnl / (p.avg_price * p.quantity) * 100) if p.avg_price > 0 and p.quantity > 0 else 0.0
            positions.append({
                "symbol": p.symbol,
                "name": names.get(p.symbol, p.symbol),
                "quantity": p.quantity,
                "avg_price": str(p.avg_price),
                "current_price": str(p.current_price),
                "pnl": str(pnl),
                "pnl_pct": round(pnl_pct, 2),
                "strategy": p.strategy,
            })

    cash_balance = _engine_ref._cached_balance if _engine_ref and _engine_ref._cached_balance else Decimal("0")
    position_value = sum(p.current_price * p.quantity for p in _engine_ref.positions.all()) if _engine_ref else Decimal("0")
    total_balance = cash_balance + position_value
    status: dict[str, Any] = {
        "running": _engine_ref._running if _engine_ref else False,
        "balance": str(total_balance) if _engine_ref else "-",
        "daily_pnl": str(getattr(_engine_ref._broker, '_daily_pnl', 0)) if _engine_ref else "0",
        "last_tick_at": _state.last_tick_at if _state else "",
        "position_count": len(positions),
        "screening_count": len(_state.screening_symbols) if _state else 0,
        "mock": mock,
        "strategies": strategy_names,
        "strategy_enabled": strategy_enabled,
    }

    screening: dict[str, Any] = {"symbols": [], "names": {}, "next_scan_at": ""}
    signals: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    if _state:
        screening = {"symbols": _state.screening_symbols, "names": _state.symbol_names, "next_scan_at": _state.next_scan_at}
        signals = _state.signals_list()
        trades = _state.trades_list()

    return {"status": status, "positions": positions, "screening": screening, "signals": signals, "trades": trades}


@router.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "engine": _engine_ref is not None,
        "bus": _bus is not None,
        "screener": _screener_ref is not None,
        "stream": _stream_ref is not None,
        "trading_started": _trading_started,
    }


@router.get("/dashboard")
async def get_dashboard() -> dict[str, Any]:
    """페이지 로드용 — KIS API 호출로 정확한 데이터 반환."""
    base = _build_realtime_state()

    broker = _engine_ref._broker if _engine_ref else None
    connected = broker and broker._connected
    if not connected:
        return base

    try:
        balance = await asyncio.to_thread(lambda: broker._api._get_kr_total_balance())
        summary = balance.outputs[1][0]
        base["status"]["balance"] = str(int(summary.get("tot_evlu_amt") or summary.get("dnca_tot_amt", "0")))
    except Exception as e:
        logger.error("dashboard.balance_failed", error=str(e))

    try:
        positions = await asyncio.to_thread(broker._api.get_kr_stock_balance)
        pos_list = []
        names = getattr(broker, "_position_names", {})
        for symbol_code, row in positions.iterrows():
            qty = int(row.get("보유수량", 0))
            if qty == 0:
                continue
            code = str(symbol_code)
            name = str(row.get("종목명", code))
            names[code] = name
            avg = float(row.get("매입단가", 0))
            cur = float(row.get("현재가", 0))
            pnl = (cur - avg) * qty
            pnl_pct = (pnl / (avg * qty) * 100) if avg > 0 and qty > 0 else 0.0
            pos_list.append({
                "symbol": code, "name": name, "quantity": qty,
                "avg_price": str(avg), "current_price": str(cur),
                "pnl": str(round(pnl, 2)), "pnl_pct": round(pnl_pct, 2),
                "strategy": "synced",
            })
        base["positions"] = pos_list
        base["status"]["position_count"] = len(pos_list)
        if _state:
            _state.symbol_names.update(names)
    except Exception as e:
        logger.error("dashboard.positions_failed", error=str(e))

    return base


@router.post("/actions/liquidate")
async def liquidate_all() -> dict[str, Any]:
    if _engine_ref is None:
        return {"success": False, "error": "engine not available"}
    try:
        results = []
        for pos in list(_engine_ref.positions.all()):
            try:
                await _engine_ref._force_close(pos)
                results.append({"symbol": pos.symbol, "status": "closed"})
            except Exception as e:
                results.append({"symbol": pos.symbol, "status": "failed", "error": str(e)})
        logger.info("dashboard.liquidate_all", results=results)
        return {"success": True, "results": results}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/actions/liquidate/{symbol}")
async def liquidate_one(symbol: str) -> dict[str, Any]:
    if _engine_ref is None:
        return {"success": False, "error": "engine not available"}
    pos = _engine_ref.positions.get(symbol)
    if pos is None:
        return {"success": False, "error": "position not found"}
    try:
        await _engine_ref._force_close(pos)
        logger.info("dashboard.liquidate_one", symbol=symbol)
        return {"success": True, "symbol": symbol}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/actions/start")
async def start_engine() -> dict[str, Any]:
    global _trading_started
    if _engine_ref is None:
        return {"success": False, "error": "engine not available"}
    if _trading_started:
        return {"success": True}
    try:
        if not _engine_ref._broker._connected:
            await _engine_ref._broker.connect()
        _engine_ref._running = True

        symbols = list(settings.get("trading.symbols", ["005930"]))
        if _screener_ref:
            held = [p.symbol for p in _engine_ref.positions.all()]
            scanned = await _screener_ref.scan(held_symbols=held)
            if scanned:
                symbols = scanned
            if _bus:
                await _bus.emit("screening.completed", {"symbols": symbols, "names": _screener_ref.symbol_names})

        if _stream_ref:
            await _stream_ref.start(symbols)

        if _bus:
            await _bus.emit("engine.started")

        _trading_started = True
        logger.info("dashboard.engine_started", symbols=symbols)
        return {"success": True, "symbols": symbols}
    except Exception as e:
        logger.error("dashboard.start_failed", error=str(e))
        return {"success": False, "error": str(e)}


@router.post("/actions/stop")
async def stop_engine() -> dict[str, Any]:
    global _trading_started
    if _engine_ref is None:
        return {"success": False}
    _engine_ref._running = False
    _trading_started = False

    async def _cleanup() -> None:
        try:
            if _stream_ref:
                await _stream_ref.stop()
            if _bus:
                await _bus.emit("engine.stopped")
            logger.info("dashboard.engine_stopped")
        except Exception as e:
            logger.error("dashboard.stop_cleanup_failed", error=str(e))

    asyncio.create_task(_cleanup())
    return {"success": True}


@router.post("/actions/rescan")
async def rescan() -> dict[str, Any]:
    if _screener_ref is None:
        return {"success": False, "error": "screener not available"}
    try:
        held = [p.symbol for p in _engine_ref.positions.all()] if _engine_ref else []
        symbols = await _screener_ref.scan(held_symbols=held)
        if _stream_ref and symbols:
            await _stream_ref.update_subscriptions(symbols)
        if _engine_ref and symbols:
            await _engine_ref.update_symbols(symbols)
        if _bus and symbols:
            await _bus.emit("screening.completed", {"symbols": symbols, "names": _screener_ref.symbol_names})
        return {"success": True, "symbols": symbols}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/strategies/{name}/toggle")
async def toggle_strategy(name: str) -> dict[str, Any]:
    if _registry_ref is None:
        return {"success": False, "error": "registry not available"}
    result = _registry_ref.toggle(name)
    if result is None:
        return {"success": False, "error": "strategy not found"}
    if _sse:
        _sse.broadcast("state", _build_realtime_state())
    return {"success": True, "name": name, "enabled": result}


@router.get("/events")
async def sse_stream() -> StreamingResponse:
    if _sse is None:
        return StreamingResponse(iter([]), media_type="text/event-stream")
    return StreamingResponse(
        _sse.stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
