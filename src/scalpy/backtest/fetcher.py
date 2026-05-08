import time
from datetime import datetime, timedelta
from decimal import Decimal

import requests
import structlog
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from scalpy.backtest.schema import Candle, get_engine, init_db

logger = structlog.get_logger()

_NAVER_CHART_URL = "https://api.stock.naver.com/chart/domestic/item"
_API_DELAY = 0.2

_name_cache: dict[str, str] = {}


def get_stock_names(symbols: list[str]) -> dict[str, str]:
    """종목코드 → 종목명 매핑 반환. 캐시 우선, 미스 시 네이버 API 조회."""
    result = {}
    missing = []
    for sym in symbols:
        if sym in _name_cache:
            result[sym] = _name_cache[sym]
        else:
            missing.append(sym)

    for sym in missing:
        try:
            resp = requests.get(
                f"https://m.stock.naver.com/api/stock/{sym}/basic",
                timeout=5,
            )
            if resp.status_code == 200:
                name = resp.json().get("stockName", sym)
                _name_cache[sym] = name
                result[sym] = name
        except Exception:
            result[sym] = sym

    return result


_ETF_PREFIXES = ("KODEX", "TIGER", "KBSTAR", "ARIRANG", "SOL", "ACE", "HANARO", "KOSEF", "PLUS")

def _parse_naver_stocks(data: dict) -> list[dict]:
    stocks = data.get("stocks", [])
    parsed = []
    for s in stocks:
        code = s.get("itemCode", "")
        if not code or len(code) != 6:
            continue
        if s.get("stockEndType") != "stock":
            continue
        if not code.endswith("0"):
            continue
        name = s.get("stockName", code)
        if any(name.startswith(p) for p in _ETF_PREFIXES):
            continue
        vol_str = s.get("accumulatedTradingVolume", "0").replace(",", "")
        price_str = s.get("closePrice", "0").replace(",", "")
        change_rate = float(s.get("fluctuationsRatio", 0))
        volume = int(vol_str)
        _name_cache[code] = name
        parsed.append({
            "symbol": code,
            "name": name,
            "volume": volume,
            "price": int(price_str),
            "change_rate": change_rate,
            "score": volume * abs(change_rate),
        })
    return parsed


def screen_top_volume(count: int = 10, min_change: float = 1.0, max_price: int = 0) -> list[dict]:
    """네이버 증권에서 급등+거래량 상위 종목 조회.

    거래량 × |변동률| 복합 스코어로 정렬.
    min_change: 최소 변동률(%) 필터 (기본 1%).
    max_price: 최대 주가 필터 (초기자본 이하만, 0이면 미적용).
    """
    seen = set()
    all_stocks = []

    for endpoint in ["marketValue/KOSPI", "up/KOSPI"]:
        url = f"https://m.stock.naver.com/api/stocks/{endpoint}"
        try:
            resp = requests.get(url, params={"page": 1, "pageSize": 50}, timeout=10)
            resp.raise_for_status()
            for s in _parse_naver_stocks(resp.json()):
                if s["symbol"] not in seen:
                    seen.add(s["symbol"])
                    all_stocks.append(s)
        except Exception as e:
            logger.warning("fetcher.screen_endpoint_failed", endpoint=endpoint, error=str(e))

    filtered = [s for s in all_stocks if abs(s["change_rate"]) >= min_change]
    if max_price > 0:
        before = len(filtered)
        filtered = [s for s in filtered if s["price"] <= max_price]
        logger.info("fetcher.price_filter", max_price=max_price, before=before, after=len(filtered))
    if len(filtered) < count:
        base = [s for s in all_stocks if max_price <= 0 or s["price"] <= max_price]
        if len(base) >= count:
            filtered = base
    filtered.sort(key=lambda x: x["score"], reverse=True)
    result = filtered[:count]
    logger.info("fetcher.screened", count=len(result), total_candidates=len(all_stocks))
    return result


def _fetch_naver_minute(
    symbol: str,
    start_dt: str,
    end_dt: str,
) -> list[dict]:
    url = f"{_NAVER_CHART_URL}/{symbol}/minute"
    params = {"startDateTime": start_dt, "endDateTime": end_dt}
    try:
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code != 200:
            logger.warning("fetcher.naver_error", status=resp.status_code, symbol=symbol)
            return []
        return resp.json()
    except Exception as e:
        logger.warning("fetcher.request_failed", symbol=symbol, error=str(e))
        return []


def _parse_naver_candle(symbol: str, item: dict) -> dict | None:
    try:
        dt_str = item.get("localDateTime", "")
        if not dt_str or len(dt_str) < 12:
            return None
        dt = datetime.strptime(dt_str[:14], "%Y%m%d%H%M%S")
        volume = int(item.get("accumulatedTradingVolume", 0))
        if volume <= 0:
            return None
        return {
            "symbol": symbol,
            "dt": dt,
            "open": Decimal(str(item.get("openPrice", 0))),
            "high": Decimal(str(item.get("highPrice", 0))),
            "low": Decimal(str(item.get("lowPrice", 0))),
            "close": Decimal(str(item.get("currentPrice", 0))),
            "volume": volume,
        }
    except (ValueError, KeyError) as e:
        logger.warning("fetcher.parse_error", error=str(e))
        return None


def fetch_and_store(
    symbols: list[str],
    days: int = 6,
) -> int:
    """네이버 증권 API에서 분봉 데이터를 가져와 DB에 저장.

    네이버 API는 최근 약 6거래일 분봉만 제공합니다.
    Returns: 저장된 총 레코드 수.
    """
    engine = init_db()

    if days > 10:
        logger.warning("fetcher.days_capped", requested=days, max=6,
                       note="네이버 API는 최근 ~6거래일만 제공")

    today = datetime.now()
    dates = []
    d = today
    while len(dates) < days:
        if d.weekday() < 5:
            dates.append(d)
        d -= timedelta(days=1)

    total = 0
    with Session(engine) as session:
        for symbol in symbols:
            for date in dates:
                start_dt = date.strftime("%Y%m%d") + "0900"
                end_dt = date.strftime("%Y%m%d") + "1530"
                date_str = date.strftime("%Y%m%d")

                logger.info("fetcher.fetching", symbol=symbol, date=date_str)
                time.sleep(_API_DELAY)
                items = _fetch_naver_minute(symbol, start_dt, end_dt)

                if not items:
                    logger.info("fetcher.no_data", symbol=symbol, date=date_str)
                    continue

                rows = []
                for item in items:
                    parsed = _parse_naver_candle(symbol, item)
                    if parsed:
                        rows.append(parsed)

                if rows:
                    stmt = insert(Candle).values(rows)
                    stmt = stmt.on_conflict_do_nothing(
                        index_elements=["symbol", "dt"]
                    )
                    session.execute(stmt)
                    session.commit()
                    total += len(rows)
                    logger.info(
                        "fetcher.stored",
                        symbol=symbol,
                        date=date_str,
                        count=len(rows),
                    )

    logger.info("fetcher.complete", total=total)
    return total
