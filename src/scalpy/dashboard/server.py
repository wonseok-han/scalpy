import asyncio
from pathlib import Path
from typing import Any

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from scalpy.dashboard.routes import init_routes, router
from scalpy.dashboard.sse import SSEManager
from scalpy.dashboard.state import DashboardState
from scalpy.events.bus import EventBus
from scalpy.strategy.registry import StrategyRegistry

logger = structlog.get_logger()

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
_INDEX_HTML = _STATIC_DIR / "index.html"


def create_app(
    state: DashboardState,
    bus: EventBus,
    engine: Any,
    screener: Any = None,
    stream: Any = None,
    registry: StrategyRegistry | None = None,
    trade_repo: Any = None,
) -> FastAPI:
    app = FastAPI(title="Scalpy Dashboard", docs_url=None, redoc_url=None)

    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    sse = SSEManager(bus)
    app.state.sse = sse
    init_routes(state, sse, engine, bus=bus, screener=screener, stream=stream, registry=registry, trade_repo=trade_repo)
    app.include_router(router)

    from scalpy.backtest.routes import router as bt_router
    from scalpy.backtest.quant_routes import router as qbt_router
    app.include_router(bt_router)
    app.include_router(qbt_router)

    @app.get("/")
    async def index() -> HTMLResponse:
        return HTMLResponse(_INDEX_HTML.read_text())

    _scalp_bt_html = _STATIC_DIR / "backtest.html"
    _quant_html = _STATIC_DIR / "quant.html"
    _quant_bt_html = _STATIC_DIR / "quant_backtest.html"

    @app.get("/backtest")
    async def backtest_redirect() -> HTMLResponse:
        return HTMLResponse(_scalp_bt_html.read_text())

    @app.get("/scalping/backtest")
    async def scalping_backtest_page() -> HTMLResponse:
        return HTMLResponse(_scalp_bt_html.read_text())

    @app.get("/quant")
    async def quant_page() -> HTMLResponse:
        return HTMLResponse(_quant_html.read_text())

    @app.get("/quant/backtest")
    async def quant_backtest_page() -> HTMLResponse:
        return HTMLResponse(_quant_bt_html.read_text())

    return app


def start_dashboard_server(
    state: DashboardState,
    bus: EventBus,
    engine: Any,
    host: str = "0.0.0.0",
    port: int = 8080,
    screener: Any = None,
    stream: Any = None,
    registry: StrategyRegistry | None = None,
    trade_repo: Any = None,
) -> asyncio.Task:
    app = create_app(state, bus, engine, screener, stream, registry=registry, trade_repo=trade_repo)

    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None

    task = asyncio.create_task(server.serve())
    task._uvicorn_server = server
    task._sse = app.state.sse
    logger.info("dashboard.started", host=host, port=port, url=f"http://localhost:{port}")
    return task
