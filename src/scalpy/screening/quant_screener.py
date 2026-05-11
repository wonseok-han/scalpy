import math
from typing import Any

import structlog

from scalpy.data.ohlcv import OhlcvRepository

logger = structlog.get_logger()


class QuantScreener:
    """OHLCV 히스토리 기반 퀀트 종목 스크리너.

    점수 = 리스크 조정 모멘텀(샤프) 35%
         + 거래량 급증 20%
         + 유동성(평균거래대금) 15%
         + RSI 적정구간 15%
         + ATR%(변동성 기회) 15%
    """

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
            candles = self._repo.get_candles(sym, interval="1d", limit=self._momentum_days + 10)
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

        # 모멘텀: 기간 수익률
        momentum = (closes[-1] - closes[0]) / closes[0]

        # 일간 수익률
        returns = [
            (closes[i] - closes[i - 1]) / closes[i - 1]
            for i in range(1, len(closes))
            if closes[i - 1] > 0
        ]
        volatility = _std(returns) if len(returns) > 1 else 0

        # 샤프 비율 (일간 수익률 평균 / 표준편차, 무위험 수익률 0 가정)
        avg_return = sum(returns) / len(returns) if returns else 0
        sharpe = avg_return / volatility if volatility > 0 else 0

        # 평균 거래량
        avg_volume = sum(volumes) / len(volumes) if volumes else 0

        # 평균 거래대금 (유동성)
        avg_turnover = sum(c * v for c, v in zip(closes, volumes)) / len(closes) if closes else 0

        # 거래량 급증: 최근 5일 vs 그 이전 전체
        recent_n = min(5, len(volumes))
        prior_n = len(volumes) - recent_n
        vol_recent = sum(volumes[-recent_n:]) / recent_n if recent_n > 0 else 0
        vol_prior = sum(volumes[:prior_n]) / prior_n if prior_n > 0 else vol_recent
        volume_surge = vol_recent / vol_prior if vol_prior > 0 else 1.0

        # ATR% (변동성 기회 — 높을수록 스윙 폭이 큼)
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

        # RSI
        rsi = self._calc_rsi(closes)

        return {
            "momentum": round(momentum, 4),
            "volatility": round(volatility, 4),
            "sharpe": round(sharpe, 4),
            "avg_volume": int(avg_volume),
            "avg_turnover": int(avg_turnover),
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

        # z-score 정규화: (값 - 평균) / 표준편차 → 이상치에 덜 민감
        sharpes = [s["sharpe"] for s in scored]
        surges = [s["volume_surge"] for s in scored]
        turnovers = [s["avg_turnover"] for s in scored]
        atrs = [s["atr_pct"] for s in scored]

        mu_sharpe, sd_sharpe = _mean_std(sharpes)
        mu_surge, sd_surge = _mean_std(surges)
        mu_turn, sd_turn = _mean_std(turnovers)
        mu_atr, sd_atr = _mean_std(atrs)

        for s in scored:
            # 1) 리스크 조정 모멘텀 (샤프): z-score
            z_sharpe = (s["sharpe"] - mu_sharpe) / sd_sharpe if sd_sharpe > 0 else 0

            # 2) 거래량 급증: z-score
            z_surge = (s["volume_surge"] - mu_surge) / sd_surge if sd_surge > 0 else 0

            # 3) 유동성(거래대금): z-score
            z_turn = (s["avg_turnover"] - mu_turn) / sd_turn if sd_turn > 0 else 0

            # 4) RSI 적정구간: 연속 점수 (40 최적, 양쪽으로 감쇠)
            rsi_score = 0.0
            if s["rsi"] is not None:
                rsi_score = math.exp(-0.5 * ((s["rsi"] - 40) / 15) ** 2)

            # 5) ATR% (변동성 기회): z-score
            z_atr = (s["atr_pct"] - mu_atr) / sd_atr if sd_atr > 0 else 0

            s["score"] = round(
                z_sharpe * 0.35
                + z_surge * 0.20
                + z_turn * 0.15
                + rsi_score * 0.15
                + z_atr * 0.15,
                4,
            )

        scored.sort(key=lambda s: s["score"], reverse=True)
        return scored[: self._max_stocks]


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance)


def _mean_std(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    mean = sum(values) / len(values)
    if len(values) < 2:
        return mean, 0.0
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return mean, math.sqrt(variance)
