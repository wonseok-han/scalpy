import math
from typing import Any

import structlog

from scalpy.data.ohlcv import OhlcvRepository

logger = structlog.get_logger()


class QuantScreener:
    """OHLCV 히스토리 기반 퀀트 종목 스크리너."""

    def __init__(
        self,
        ohlcv_repo: OhlcvRepository,
        max_stocks: int = 10,
        momentum_days: int = 20,
        min_avg_volume: int = 500_000,
        min_momentum: float = 0.0,
    ) -> None:
        self._repo = ohlcv_repo
        self._max_stocks = max_stocks
        self._momentum_days = momentum_days
        self._min_avg_volume = min_avg_volume
        self._min_momentum = min_momentum
        self.symbol_names: dict[str, str] = {}
        self._last_scan: list[dict[str, Any]] = []

    def scan(self, symbols: list[str], held_symbols: list[str] | None = None) -> list[str]:
        held = set(held_symbols or [])
        scored: list[dict[str, Any]] = []

        for sym in symbols:
            candles = self._repo.get_candles(sym, interval="1d", limit=self._momentum_days + 5)
            if len(candles) < self._momentum_days:
                continue

            factors = self._calc_factors(candles)
            if factors is None:
                continue

            if factors["avg_volume"] < self._min_avg_volume:
                continue
            if factors["momentum"] < self._min_momentum:
                continue

            scored.append({"symbol": sym, **factors})

        if not scored:
            logger.warning("quant_screener.no_candidates")
            self._last_scan = []
            return list(held)

        ranked = self._rank(scored)
        self._last_scan = ranked

        available_slots = max(0, self._max_stocks - len(held))
        new_symbols = [s["symbol"] for s in ranked if s["symbol"] not in held][:available_slots]
        result = list(held) + new_symbols

        logger.info(
            "quant_screener.scan_complete",
            candidates=len(scored),
            selected=len(new_symbols),
            total=len(result),
        )
        return result

    def get_last_scan(self) -> list[dict[str, Any]]:
        return self._last_scan

    def _calc_factors(self, candles: list[dict]) -> dict[str, Any] | None:
        closes = [c["close"] for c in candles]
        volumes = [c["volume"] for c in candles]
        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]

        if closes[0] == 0 or len(closes) < 2:
            return None

        momentum = (closes[-1] - closes[0]) / closes[0]

        returns = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes)) if closes[i - 1] > 0]
        volatility = _std(returns) if len(returns) > 1 else 0

        avg_volume = sum(volumes) / len(volumes) if volumes else 0

        vol_recent = sum(volumes[-5:]) / 5 if len(volumes) >= 5 else avg_volume
        vol_prev = sum(volumes[:-5]) / max(len(volumes) - 5, 1)
        volume_surge = vol_recent / vol_prev if vol_prev > 0 else 1.0

        true_ranges = []
        for i in range(1, len(candles)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            true_ranges.append(tr)
        atr = sum(true_ranges) / len(true_ranges) if true_ranges else 0
        atr_pct = atr / closes[-1] if closes[-1] > 0 else 0

        rsi = self._calc_rsi(closes)

        return {
            "momentum": round(momentum, 4),
            "volatility": round(volatility, 4),
            "avg_volume": int(avg_volume),
            "volume_surge": round(volume_surge, 2),
            "atr_pct": round(atr_pct, 4),
            "rsi": round(rsi, 1) if rsi is not None else None,
            "close": closes[-1],
        }

    def _calc_rsi(self, closes: list[int], period: int = 14) -> float | None:
        if len(closes) < period + 1:
            return None
        changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        recent = changes[-period:]
        gains = [c for c in recent if c > 0]
        losses = [-c for c in recent if c < 0]
        avg_gain = sum(gains) / period if gains else 0
        avg_loss = sum(losses) / period if losses else 0
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _rank(self, scored: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not scored:
            return []

        max_mom = max(abs(s["momentum"]) for s in scored) or 1
        max_vs = max(s["volume_surge"] for s in scored) or 1
        max_vol = max(s["avg_volume"] for s in scored) or 1

        for s in scored:
            norm_mom = s["momentum"] / max_mom
            norm_vs = s["volume_surge"] / max_vs
            norm_vol = s["avg_volume"] / max_vol
            rsi_score = 0.0
            if s["rsi"] is not None:
                if 30 <= s["rsi"] <= 50:
                    rsi_score = 1.0
                elif 25 <= s["rsi"] <= 60:
                    rsi_score = 0.5
            s["score"] = round(
                norm_mom * 0.35
                + norm_vs * 0.25
                + norm_vol * 0.2
                + rsi_score * 0.2,
                4,
            )

        scored.sort(key=lambda s: s["score"], reverse=True)
        return scored[:self._max_stocks]


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance)
