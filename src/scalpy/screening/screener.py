from typing import Any

import structlog

from scalpy.broker.base import BaseBroker

logger = structlog.get_logger()


class StockScreener:
    def __init__(
        self,
        broker: BaseBroker,
        max_stocks: int = 5,
        min_change_rate: float = 2.0,
        min_volume: int = 100_000,
    ) -> None:
        self._broker = broker
        self._max_stocks = max_stocks
        self._min_change_rate = min_change_rate
        self._min_volume = min_volume

    async def scan(self, held_symbols: list[str] | None = None) -> list[str]:
        held = set(held_symbols or [])

        stocks = await self._broker.get_top_volume_stocks(30)
        if not stocks:
            logger.warning("screener.no_data")
            return list(held)

        filtered = self._filter(stocks)
        if not filtered:
            logger.warning("screener.no_stocks_after_filter")
            return list(held)

        ranked = self._score_and_rank(filtered)

        available_slots = max(0, self._max_stocks - len(held))
        new_symbols = [s for s in ranked if s not in held][:available_slots]
        result = list(held) + new_symbols

        logger.info(
            "screener.scan_complete",
            held=list(held),
            new=new_symbols,
            total=len(result),
        )
        return result

    def _filter(self, stocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = []
        for s in stocks:
            if s.get("volume", 0) < self._min_volume:
                continue
            if abs(s.get("change_rate", 0.0)) < self._min_change_rate:
                continue
            result.append(s)
        return result

    def _score_and_rank(self, stocks: list[dict[str, Any]]) -> list[str]:
        if not stocks:
            return []

        max_vol = max(s["volume"] for s in stocks)
        max_cr = max(abs(s.get("change_rate", 0)) for s in stocks)

        for s in stocks:
            norm_vol = s["volume"] / max_vol if max_vol > 0 else 0
            norm_cr = abs(s.get("change_rate", 0)) / max_cr if max_cr > 0 else 0
            s["score"] = norm_vol * 0.6 + norm_cr * 0.4

        stocks.sort(key=lambda s: s["score"], reverse=True)
        return [s["symbol"] for s in stocks]
