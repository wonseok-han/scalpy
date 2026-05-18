"""미장 종목 스크리닝 — KIS 해외주식 조건검색 + 실시간/OHLCV 기반 스코어링.

기존 quant_screener.py(국장)를 수정하지 않는 독립 구현체.
"""

import math
import structlog
from decimal import Decimal
from typing import Any

logger = structlog.get_logger()

_market_condition: dict[str, Any] = {}


def get_market_condition() -> dict[str, Any]:
    return dict(_market_condition)


class USQuantScreener:
    """미장 퀀트 스크리너 — 브로커의 get_top_volume_stocks 결과를 기반으로 스코어링."""

    def __init__(
        self,
        ohlcv_repo: Any = None,
        max_stocks: int = 10,
        momentum_days: int = 10,
        min_avg_volume: int = 100_000,
        min_momentum: float = 0.0,
    ) -> None:
        self._ohlcv_repo = ohlcv_repo
        self.max_stocks = max_stocks
        self.momentum_days = momentum_days
        self.min_avg_volume = min_avg_volume
        self.min_momentum = min_momentum
        self._last_scan: list[dict] = []

    def scan(
        self,
        universe: list[str],
        held_symbols: list[str] | None = None,
        live_data: dict[str, dict] | None = None,
    ) -> list[str]:
        """universe 내 종목을 스코어링하여 상위 N개 반환."""
        held = set(held_symbols or [])
        scored: list[dict] = []

        for symbol in universe:
            candles = []
            if self._ohlcv_repo:
                candles = self._ohlcv_repo.get_candles(symbol, interval="1d", limit=self.momentum_days + 5)

            live = (live_data or {}).get(symbol, {})

            if len(candles) < 5:
                if not live:
                    scored.append({
                        "symbol": symbol,
                        "momentum": 0.0,
                        "avg_volume": 0,
                        "change_rate": 0.0,
                        "volume": 0,
                        "amount": 0,
                        "score": 0.3 if symbol in held else 0.0,
                    })
                    continue
                scored.append({
                    "symbol": symbol,
                    "momentum": 0.0,
                    "avg_volume": 0,
                    "change_rate": live.get("change_rate", 0.0),
                    "volume": live.get("volume", 0),
                    "amount": live.get("amount", 0),
                    "score": 0.0,
                })
                continue

            closes = [c["close"] for c in candles]
            volumes = [c["volume"] for c in candles]
            avg_vol = sum(volumes[-self.momentum_days:]) / min(len(volumes), self.momentum_days) if volumes else 0

            if len(closes) >= 2 and closes[-self.momentum_days] != 0:
                mom = (closes[-1] - closes[-self.momentum_days]) / closes[-self.momentum_days]
            else:
                mom = 0.0

            if avg_vol < self.min_avg_volume and symbol not in held:
                continue
            if mom < self.min_momentum and symbol not in held:
                continue

            scored.append({
                "symbol": symbol,
                "momentum": round(mom * 100, 2),
                "avg_volume": int(avg_vol),
                "change_rate": live.get("change_rate", 0.0),
                "volume": live.get("volume", 0),
                "amount": live.get("amount", 0),
                "score": 0.0,
            })

        self._rank(scored, held)

        self._last_scan = scored[:self.max_stocks]

        selected = [s["symbol"] for s in self._last_scan]
        for h in held:
            if h not in selected:
                selected.append(h)

        logger.info("us_screener.scan_done", universe=len(universe), selected=len(selected))
        return selected

    def _rank(self, scored: list[dict], held: set[str]) -> None:
        if not scored:
            return

        has_live = any(s.get("volume", 0) > 0 for s in scored)
        has_ohlcv = any(s.get("avg_volume", 0) > 0 for s in scored)

        if has_live:
            volumes = [s.get("volume", 0) for s in scored]
            changes = [s.get("change_rate", 0.0) for s in scored]
            amounts = [s.get("amount", 0) for s in scored]
            mu_vol, sd_vol = _mean_std(volumes)
            mu_chg, sd_chg = _mean_std(changes)
            mu_amt, sd_amt = _mean_std(amounts)

        if has_ohlcv:
            moms = [s.get("momentum", 0.0) for s in scored]
            avg_vols = [s.get("avg_volume", 0) for s in scored]
            mu_mom, sd_mom = _mean_std(moms)
            mu_avol, sd_avol = _mean_std(avg_vols)

        for s in scored:
            held_bonus = 0.2 if s["symbol"] in held else 0

            if has_live and has_ohlcv:
                z_vol = (s.get("volume", 0) - mu_vol) / sd_vol if sd_vol > 0 else 0
                z_chg = (s.get("change_rate", 0.0) - mu_chg) / sd_chg if sd_chg > 0 else 0
                z_amt = (s.get("amount", 0) - mu_amt) / sd_amt if sd_amt > 0 else 0
                z_mom = (s.get("momentum", 0.0) - mu_mom) / sd_mom if sd_mom > 0 else 0
                z_avol = (s.get("avg_volume", 0) - mu_avol) / sd_avol if sd_avol > 0 else 0
                s["score"] = round(z_mom * 0.20 + z_avol * 0.10 + z_vol * 0.25 + z_chg * 0.25 + z_amt * 0.20 + held_bonus, 4)
            elif has_live:
                z_vol = (s.get("volume", 0) - mu_vol) / sd_vol if sd_vol > 0 else 0
                z_chg = (s.get("change_rate", 0.0) - mu_chg) / sd_chg if sd_chg > 0 else 0
                z_amt = (s.get("amount", 0) - mu_amt) / sd_amt if sd_amt > 0 else 0
                s["score"] = round(z_vol * 0.35 + z_chg * 0.35 + z_amt * 0.30 + held_bonus, 4)
            elif has_ohlcv:
                z_mom = (s.get("momentum", 0.0) - mu_mom) / sd_mom if sd_mom > 0 else 0
                z_avol = (s.get("avg_volume", 0) - mu_avol) / sd_avol if sd_avol > 0 else 0
                s["score"] = round(z_mom * 0.5 + z_avol * 0.3 + held_bonus + 0.2, 4)
            else:
                s["score"] = round(held_bonus, 4)

        scored.sort(key=lambda x: x["score"], reverse=True)

    def get_last_scan(self) -> list[dict]:
        return list(self._last_scan)


def _mean_std(values: list) -> tuple[float, float]:
    fvals = [float(v) for v in values]
    if not fvals:
        return 0.0, 0.0
    mean = sum(fvals) / len(fvals)
    if len(fvals) < 2:
        return mean, 0.0
    variance = sum((v - mean) ** 2 for v in fvals) / (len(fvals) - 1)
    return mean, math.sqrt(variance)


async def scan_us_market(broker: Any, count: int = 50) -> list[dict[str, Any]]:
    """브로커 API로 미장 거래량 상위 종목을 가져와 universe 구성."""
    global _market_condition
    try:
        stocks = await broker.get_top_volume_stocks(count)
        if not stocks:
            return []

        total = len(stocks)
        changes = [s.get("change_rate", 0) for s in stocks if s.get("change_rate") is not None]
        if changes:
            avg_change = sum(changes) / len(changes)
            adv = sum(1 for c in changes if c > 0)
            adv_ratio = adv / len(changes) if changes else 0.5

            if avg_change > 0.5 and adv_ratio > 0.6:
                regime = "bullish"
                recommend = ["ichimoku", "momentum"]
            elif avg_change < -0.5 and adv_ratio < 0.4:
                regime = "bearish"
                recommend = ["mean_reversion"]
            else:
                regime = "sideways"
                recommend = ["mean_reversion", "factor"]

            _market_condition = {
                "regime": regime,
                "avg_change": round(avg_change, 2),
                "adv_ratio": round(adv_ratio * 100, 1),
                "total": total,
                "recommend": recommend,
            }

        logger.info("us_screener.market_scanned", count=len(stocks))
        return stocks
    except Exception as e:
        logger.warning("us_screener.market_scan_failed", error=str(e))
        return []
