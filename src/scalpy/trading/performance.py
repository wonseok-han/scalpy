from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scalpy.data.repository import TradeRepository


@dataclass
class StrategyStats:
    trades: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: Decimal = Decimal("0")
    max_drawdown: Decimal = Decimal("0")
    _peak: Decimal = Decimal("0")

    @property
    def win_rate(self) -> float:
        return self.wins / self.trades * 100 if self.trades > 0 else 0.0

    @property
    def avg_pnl(self) -> Decimal:
        return self.total_pnl / self.trades if self.trades > 0 else Decimal("0")


class PerformanceTracker:
    def __init__(self) -> None:
        self._stats: dict[str, StrategyStats] = {}
        self._repo: TradeRepository | None = None

    def set_repo(self, repo: TradeRepository) -> None:
        self._repo = repo
        self._load_from_db()

    def _load_from_db(self) -> None:
        if not self._repo:
            return
        self._stats.clear()
        for t in self._repo.get_strategy_trades():
            strategy = t["strategy"]
            pnl = Decimal(str(t["pnl"]))
            if strategy not in self._stats:
                self._stats[strategy] = StrategyStats()
            s = self._stats[strategy]
            s.trades += 1
            s.total_pnl += pnl
            if pnl > 0:
                s.wins += 1
            elif pnl < 0:
                s.losses += 1
            if s.total_pnl > s._peak:
                s._peak = s.total_pnl
            dd = s._peak - s.total_pnl
            if dd > s.max_drawdown:
                s.max_drawdown = dd

    def record_trade(self, strategy: str, pnl: Decimal, symbol: str = "") -> None:
        if strategy not in self._stats:
            self._stats[strategy] = StrategyStats()
        s = self._stats[strategy]
        s.trades += 1
        s.total_pnl += pnl
        if pnl > 0:
            s.wins += 1
        elif pnl < 0:
            s.losses += 1

        if s.total_pnl > s._peak:
            s._peak = s.total_pnl
        dd = s._peak - s.total_pnl
        if dd > s.max_drawdown:
            s.max_drawdown = dd

        if self._repo:
            try:
                self._repo.record_strategy_trade(strategy, symbol, float(pnl))
            except Exception:
                pass

    def get_stats(self, strategy: str) -> StrategyStats | None:
        return self._stats.get(strategy)

    def all_stats(self) -> dict[str, dict]:
        return {
            name: {
                "trades": s.trades,
                "wins": s.wins,
                "losses": s.losses,
                "win_rate": round(s.win_rate, 1),
                "total_pnl": str(s.total_pnl),
                "avg_pnl": str(s.avg_pnl),
                "max_drawdown": str(s.max_drawdown),
            }
            for name, s in self._stats.items()
        }

    def reset(self) -> None:
        self._stats.clear()
