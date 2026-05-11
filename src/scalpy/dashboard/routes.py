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
_trade_repo_ref: Any = None
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
    trade_repo: Any = None,
) -> None:
    global _state, _sse, _bus, _engine_ref, _screener_ref, _stream_ref, _registry_ref, _trade_repo_ref
    _state = state
    _sse = sse
    _bus = bus
    _engine_ref = engine
    _screener_ref = screener
    _stream_ref = stream
    _registry_ref = registry
    _trade_repo_ref = trade_repo

    if bus:
        for event in _SSE_EVENTS:
            bus.subscribe(event, _on_state_change)
        bus.subscribe("order.filled", _on_order_filled)

    logger.info("routes.initialized", engine=engine is not None, screener=screener is not None, stream=stream is not None)


def _on_state_change(data: dict[str, Any]) -> None:
    if _sse is None:
        return
    _sse.broadcast("state", _build_sse_state())


def _on_order_filled(data: dict[str, Any]) -> None:
    if not _trade_repo_ref or not _engine_ref:
        return
    asyncio.create_task(_sync_trades_now())


async def _sync_trades_now() -> None:
    try:
        broker = _engine_ref._broker
        broker._last_ccld_first_page = -1
        trades = await broker.get_trade_history()
        if trades:
            _trade_repo_ref.sync_trades(trades)
        if _sse:
            _sse.broadcast("state", _build_sse_state())
    except Exception as e:
        logger.error("routes.trade_sync_failed", error=str(e))


def _build_sse_state() -> dict[str, Any]:
    """SSE 푸시용 — API 호출 없이 메모리 캐시만 사용."""
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

    total_fees = "0"
    trade_count = 0
    if _trade_repo_ref:
        try:
            total_fees = str(_trade_repo_ref.get_daily_fees())
            trade_count = _trade_repo_ref.get_daily_trade_count()
        except Exception:
            pass

    return {
        "status": {
            "running": _engine_ref._running if _engine_ref else False,
            "balance": _state.last_api_balance if _state else "-",
            "prev_balance": _state.last_prev_balance if _state else "",
            "daily_pnl": str(_trade_repo_ref.get_daily_pnl()) if _trade_repo_ref else "0",
            "total_fees": total_fees,
            "trade_count": trade_count,
            "last_tick_at": _state.last_tick_at if _state else "",
            "position_count": len(positions),
            "screening_count": len(_state.screening_symbols) if _state else 0,
        },
        "positions": positions,
        "screening": {
            "symbols": _state.screening_symbols if _state else [],
            "names": _state.symbol_names if _state else {},
        },
    }


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


@router.get("/status")
async def get_status() -> dict[str, Any]:
    """엔진 상태 — 캐시 데이터만, 즉시 반환."""
    mock = settings.get("mock", True)
    strategy_names = {s.name: s.display_name for s in _registry_ref.all()} if _registry_ref else {}
    strategy_enabled = {s.name: s.enabled for s in _registry_ref.all()} if _registry_ref else {}
    pos_count = len(_engine_ref.positions.all()) if _engine_ref else 0
    total_fees = "0"
    trade_count = 0
    if _trade_repo_ref:
        try:
            total_fees = str(_trade_repo_ref.get_daily_fees())
            trade_count = _trade_repo_ref.get_daily_trade_count()
        except Exception:
            pass

    return {
        "running": _engine_ref._running if _engine_ref else False,
        "balance": _state.last_api_balance if _state else "-",
        "prev_balance": _state.last_prev_balance if _state else "",
        "daily_pnl": str(_trade_repo_ref.get_daily_pnl()) if _trade_repo_ref else "0",
        "total_fees": total_fees,
        "trade_count": trade_count,
        "last_tick_at": _state.last_tick_at if _state else "",
        "position_count": pos_count,
        "screening_count": len(_state.screening_symbols) if _state else 0,
        "mock": mock,
        "strategies": strategy_names,
        "strategy_enabled": strategy_enabled,
        "trading_started": _trading_started,
    }


@router.get("/positions")
async def get_positions() -> list[dict[str, Any]]:
    """보유 포지션 — 엔진 메모리에서 즉시 반환."""
    if _engine_ref is None:
        return []
    names = _state.symbol_names if _state else {}
    positions: list[dict[str, Any]] = []
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


@router.get("/screening")
async def get_screening() -> dict[str, Any]:
    """스크리닝 결과 — 캐시 데이터만, 즉시 반환."""
    if not _state:
        return {"symbols": [], "names": {}, "next_scan_at": ""}
    return {
        "symbols": _state.screening_symbols,
        "names": _state.symbol_names,
        "next_scan_at": _state.next_scan_at,
    }


@router.get("/signals")
async def get_signals() -> list[dict[str, Any]]:
    """시그널 목록 — 캐시 데이터만, 즉시 반환."""
    return _state.signals_list() if _state else []


@router.get("/trades")
async def get_trades() -> list[dict[str, Any]]:
    """당일 거래내역 — DB에서 즉시 반환."""
    if not _trade_repo_ref:
        return []
    try:
        trades = _trade_repo_ref.get_trades_today()
        if trades and _state:
            for t in trades:
                name = t.get("name", "")
                if name:
                    _state.symbol_names[t["symbol"]] = name
        return trades
    except Exception as e:
        logger.error("api.trades_failed", error=str(e))
        return []


@router.get("/period-pnl")
async def get_period_pnl() -> list[dict[str, Any]]:
    """기간손익현황 — KIS API (실거래만)."""
    broker = _engine_ref._broker if _engine_ref else None
    if not broker or not broker._connected:
        return []
    try:
        return await broker.get_period_pnl()
    except Exception as e:
        logger.error("api.period_pnl_failed", error=str(e))
        return []


@router.get("/balance")
async def get_balance() -> dict[str, Any]:
    """KIS API 잔고 조회 — 느림."""
    broker = _engine_ref._broker if _engine_ref else None
    if not broker or not broker._connected:
        return {}
    try:
        balance = await asyncio.to_thread(lambda: broker._api._get_kr_total_balance())
        summary = balance.outputs[1][0]
        api_balance = str(int(summary.get("tot_evlu_amt") or summary.get("dnca_tot_amt", "0")))
        prev_balance = str(int(summary.get("bfdy_tot_asst_evlu_amt", "0")))
        if _state:
            _state.last_api_balance = api_balance
            _state.last_prev_balance = prev_balance
        return {"balance": api_balance, "prev_balance": prev_balance}
    except Exception as e:
        logger.error("api.balance_failed", error=str(e))
        return {}


@router.post("/actions/liquidate")
async def liquidate_all() -> dict[str, Any]:
    if _engine_ref is None:
        return {"success": False, "error": "engine not available"}
    try:
        results = []
        for pos in list(_engine_ref.positions.all()):
            try:
                await _engine_ref._force_close(pos)
                removed = _engine_ref.positions.get(pos.symbol) is None
                results.append({"symbol": pos.symbol, "status": "closed" if removed else "pending"})
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


@router.post("/actions/cancel-all-orders")
async def cancel_all_orders() -> dict[str, Any]:
    if _engine_ref is None:
        return {"success": False, "error": "engine not available"}
    broker = _engine_ref._broker
    if not broker._connected:
        return {"success": False, "error": "broker not connected"}
    try:
        count = await broker.cancel_all_orders()
        if count > 0:
            await _engine_ref.sync_positions()
            if _state:
                _state.symbol_names.update(broker._position_names)
        logger.info("dashboard.cancel_all_orders", count=count)
        return {"success": True, "cancelled": count}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/actions/start")
async def start_engine() -> dict[str, Any]:
    global _trading_started
    if _engine_ref is None:
        return {"success": False, "error": "engine not available"}
    if _trading_started:
        return {"success": True}
    if _stream_ref and _stream_ref._stopping:
        return {"success": False, "error": "stop in progress"}
    try:
        if not _engine_ref._broker._connected:
            await _engine_ref._broker.connect()
        await _engine_ref.sync_positions()
        _engine_ref._running = True
        _engine_ref.start_background_loops()

        symbols = list(settings.get("trading.symbols", ["005930"]))
        if _screener_ref:
            held = [p.symbol for p in _engine_ref.positions.all()]
            scanned = await _screener_ref.scan(held_symbols=held)
            if scanned:
                symbols = scanned
            if _bus:
                await _bus.emit("screening.completed", {"symbols": symbols, "names": _screener_ref.symbol_names})

        if _stream_ref:
            held = [p.symbol for p in _engine_ref.positions.all()]
            start_symbols = list(set(symbols) | set(held))
            await _stream_ref.start(start_symbols)

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
    if not _trading_started:
        return {"success": False, "error": "already stopped"}
    if _stream_ref and _stream_ref._stopping:
        return {"success": False, "error": "stop in progress"}
    _engine_ref._running = False
    _engine_ref.stop_background_loops()
    _trading_started = False

    if _stream_ref:
        await _stream_ref.stop()
    if _bus:
        await _bus.emit("engine.stopped")
    logger.info("dashboard.engine_stopped")
    return {"success": True}


@router.post("/actions/rescan")
async def rescan() -> dict[str, Any]:
    if _screener_ref is None:
        return {"success": False, "error": "screener not available"}
    try:
        held = [p.symbol for p in _engine_ref.positions.all()] if _engine_ref else []
        symbols = await _screener_ref.scan(held_symbols=held)
        if _stream_ref and symbols:
            sub_symbols = list(set(symbols) | set(held))
            await _stream_ref.update_subscriptions(sub_symbols)
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
        _sse.broadcast("state", _build_sse_state())
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
