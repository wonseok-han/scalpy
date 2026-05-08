from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from scalpy.events.bus import EventBus


@dataclass
class TradeRecord:
    time: str
    symbol: str
    side: str
    quantity: int
    price: str
    strategy: str
    pnl: str = ""


@dataclass
class SignalRecord:
    time: str
    symbol: str
    side: str
    strategy: str
    price: str
    confidence: float = 0.0


@dataclass
class DashboardState:
    trades: deque[TradeRecord] = field(default_factory=lambda: deque(maxlen=200))
    signals: deque[SignalRecord] = field(default_factory=lambda: deque(maxlen=100))
    screening_symbols: list[str] = field(default_factory=list)
    symbol_names: dict[str, str] = field(default_factory=dict)
    next_scan_at: str = ""
    engine_running: bool = False
    last_tick_at: str = ""
    daily_pnl: Decimal = Decimal("0")
    last_api_balance: str = "-"

    def register_handlers(self, bus: EventBus) -> None:
        bus.subscribe("order.filled", self._on_order_filled)
        bus.subscribe("signal.generated", self._on_signal)
        bus.subscribe("position.closed", self._on_position_closed)
        bus.subscribe("engine.started", self._on_engine_started)
        bus.subscribe("engine.stopped", self._on_engine_stopped)
        bus.subscribe("screening.completed", self._on_screening)
        bus.subscribe("tick.received", self._on_tick)

    def _on_order_filled(self, data: dict[str, Any]) -> None:
        self.trades.appendleft(TradeRecord(
            time=datetime.now().strftime("%H:%M:%S"),
            symbol=data.get("symbol", ""),
            side=data.get("side", ""),
            quantity=data.get("qty", 0),
            price=str(data.get("price", "")),
            strategy=data.get("strategy", ""),
            pnl=data.get("pnl", ""),
        ))

    def _on_signal(self, data: dict[str, Any]) -> None:
        self.signals.appendleft(SignalRecord(
            time=datetime.now().strftime("%H:%M:%S"),
            symbol=data.get("symbol", ""),
            side=data.get("side", ""),
            strategy=data.get("strategy", ""),
            price=str(data.get("price", "")),
            confidence=data.get("confidence", 0.0),
        ))

    def _on_position_closed(self, data: dict[str, Any]) -> None:
        symbol = data.get("symbol", "")
        pnl = Decimal(str(data.get("pnl", 0)))
        self.daily_pnl += pnl
        for trade in self.trades:
            if trade.symbol == symbol and trade.side == "sell" and not trade.pnl:
                trade.pnl = str(pnl)
                break

    def _on_engine_started(self, data: dict[str, Any]) -> None:
        self.engine_running = True

    def _on_engine_stopped(self, data: dict[str, Any]) -> None:
        self.engine_running = False

    def _on_screening(self, data: dict[str, Any]) -> None:
        self.screening_symbols = data.get("symbols", [])
        names = data.get("names", {})
        if names:
            self.symbol_names.update(names)

    def _on_tick(self, data: dict[str, Any]) -> None:
        self.last_tick_at = datetime.now().strftime("%H:%M:%S")

    def trades_list(self) -> list[dict[str, Any]]:
        return [
            {
                "time": t.time,
                "symbol": t.symbol,
                "side": t.side,
                "quantity": t.quantity,
                "price": t.price,
                "strategy": t.strategy,
                "pnl": t.pnl,
            }
            for t in self.trades
        ]

    def signals_list(self) -> list[dict[str, Any]]:
        return [
            {
                "time": s.time,
                "symbol": s.symbol,
                "side": s.side,
                "strategy": s.strategy,
                "price": s.price,
            }
            for s in self.signals
        ]
