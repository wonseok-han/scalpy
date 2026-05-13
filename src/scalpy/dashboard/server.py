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
_MAIN_HTML = _STATIC_DIR / "quant.html"


def create_app(
    state: DashboardState,
    bus: EventBus,
    engine: Any,
    stream: Any = None,
    registry: StrategyRegistry | None = None,
    trade_repo: Any = None,
) -> FastAPI:
    app = FastAPI(title="Scalpy Quant", docs_url=None, redoc_url=None)

    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    sse = SSEManager(bus)
    app.state.sse = sse
    init_routes(state, sse, engine, bus=bus, stream=stream, registry=registry, trade_repo=trade_repo)
    app.include_router(router)

    from scalpy.backtest.quant_routes import router as qbt_router
    app.include_router(qbt_router)

    _bt_html = _STATIC_DIR / "quant_backtest.html"

    @app.get("/")
    async def index() -> HTMLResponse:
        return HTMLResponse(_MAIN_HTML.read_text())

    @app.get("/backtest")
    async def backtest_page() -> HTMLResponse:
        return HTMLResponse(_bt_html.read_text())

    return app


def start_dashboard_server(
    state: DashboardState,
    bus: EventBus,
    engine: Any,
    host: str = "0.0.0.0",
    port: int = 8080,
    stream: Any = None,
    registry: StrategyRegistry | None = None,
    trade_repo: Any = None,
) -> asyncio.Task:
    app = create_app(state, bus, engine, stream=stream, registry=registry, trade_repo=trade_repo)

    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None

    task = asyncio.create_task(server.serve())
    task._uvicorn_server = server
    task._sse = app.state.sse
    logger.info("dashboard.started", host=host, port=port, url=f"http://localhost:{port}")
    return task
