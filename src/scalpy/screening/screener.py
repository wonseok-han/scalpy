from decimal import Decimal
from typing import Any

import structlog

from scalpy.broker.base import BaseBroker

logger = structlog.get_logger()

_ETF_PREFIXES = ("KODEX", "TIGER", "KBSTAR", "RISE", "ARIRANG", "SOL", "ACE", "HANARO", "KOSEF", "PLUS")


def _fetch_market_stocks() -> list[dict[str, Any]]:
    """FinanceDataReader로 전체 KRX 보통주 당일 데이터 조회."""
    import FinanceDataReader as fdr

    df = fdr.StockListing("KRX")
    df = df[df["Market"].isin(["KOSPI", "KOSDAQ"])]
    # 우선주 제외
    df = df[df["Code"].str[-1] == "0"]
    # SPAC/관리종목 제외
    exclude_dept = {"SPAC(소속부없음)", "관리종목(소속부없음)", "투자주의환기종목(소속부없음)"}
    if "Dept" in df.columns:
        df = df[~df["Dept"].isin(exclude_dept)]

    stocks = []
    for _, row in df.iterrows():
        stocks.append({
            "symbol": row["Code"],
            "name": row["Name"],
            "volume": int(row["Volume"]) if row["Volume"] else 0,
            "price": Decimal(str(int(row["Close"]))) if row["Close"] else Decimal("0"),
            "change_rate": float(row["ChagesRatio"]) if row["ChagesRatio"] else 0.0,
            "volume_turnover": 0.0,
        })
    logger.info("screener.market_fetched", total=len(stocks))
    return stocks


class StockScreener:
    def __init__(
        self,
        broker: BaseBroker,
        max_stocks: int = 5,
        min_change_rate: float = 2.0,
        max_change_rate: float = 8.0,
        min_change_rate_lower: float = -2.0,
        min_volume: int = 100_000,
    ) -> None:
        self._broker = broker
        self._max_stocks = max_stocks
        self._min_change_rate = min_change_rate
        self._max_change_rate = max_change_rate
        self._min_change_rate_lower = min_change_rate_lower
        self._min_volume = min_volume
        self.symbol_names: dict[str, str] = {}

    async def scan(self, held_symbols: list[str] | None = None) -> list[str]:
        held = set(held_symbols or [])

        try:
            import asyncio
            stocks = await asyncio.to_thread(_fetch_market_stocks)
        except Exception as e:
            logger.warning("screener.fdr_failed_fallback_broker", error=str(e))
            stocks = await self._broker.get_top_volume_stocks(30)
        if not stocks:
            logger.warning("screener.no_data")
            return list(held)

        for s in stocks:
            if s.get("name"):
                self.symbol_names[s["symbol"]] = s["name"]

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
            code = s.get("symbol", "")
            if code and not code[0].isdigit():
                continue
            if code.startswith("9"):
                continue
            name = s.get("name", "")
            if any(name.startswith(p) for p in _ETF_PREFIXES):
                continue
            if s.get("volume", 0) < self._min_volume:
                continue
            cr = s.get("change_rate", 0.0)
            if cr < self._min_change_rate_lower:
                continue
            if cr > self._max_change_rate:
                continue
            if abs(cr) < self._min_change_rate:
                continue
            result.append(s)
        return result

    def _score_and_rank(self, stocks: list[dict[str, Any]]) -> list[str]:
        if not stocks:
            return []

        max_vol = max(s["volume"] for s in stocks)
        max_cr = max(abs(s.get("change_rate", 0)) for s in stocks)
        max_vt = max(s.get("volume_turnover", 0) for s in stocks) or 1

        for s in stocks:
            norm_vol = s["volume"] / max_vol if max_vol > 0 else 0
            norm_cr = abs(s.get("change_rate", 0)) / max_cr if max_cr > 0 else 0
            norm_vt = s.get("volume_turnover", 0) / max_vt
            s["score"] = norm_vol * 0.4 + norm_cr * 0.3 + norm_vt * 0.3

        stocks.sort(key=lambda s: s["score"], reverse=True)
        return [s["symbol"] for s in stocks]
