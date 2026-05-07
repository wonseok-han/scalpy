import pytest

from scalpy.broker.mock import MockBroker
from scalpy.screening.screener import StockScreener


@pytest.fixture
def broker() -> MockBroker:
    return MockBroker()


@pytest.fixture
def screener(broker: MockBroker) -> StockScreener:
    return StockScreener(broker, max_stocks=5, min_change_rate=2.0, min_volume=100_000)


async def test_scan_returns_top_stocks(screener: StockScreener) -> None:
    result = await screener.scan()
    assert len(result) <= 5
    assert len(result) > 0


async def test_scan_respects_max_stocks(broker: MockBroker) -> None:
    screener = StockScreener(broker, max_stocks=3, min_change_rate=0.0, min_volume=0)
    result = await screener.scan()
    assert len(result) <= 3


async def test_held_symbols_always_included(screener: StockScreener) -> None:
    result = await screener.scan(held_symbols=["999999"])
    assert "999999" in result


async def test_held_symbols_reduce_available_slots(broker: MockBroker) -> None:
    screener = StockScreener(broker, max_stocks=3, min_change_rate=0.0, min_volume=0)
    result = await screener.scan(held_symbols=["HELD1", "HELD2"])
    assert "HELD1" in result
    assert "HELD2" in result
    assert len(result) <= 3


async def test_change_rate_filter(broker: MockBroker) -> None:
    # min_change_rate=5.0 → 카카오(5.6%)만 통과
    screener = StockScreener(broker, max_stocks=10, min_change_rate=5.0, min_volume=0)
    result = await screener.scan()
    assert "035720" in result
    assert "006400" not in result  # 1.1%


async def test_volume_filter(broker: MockBroker) -> None:
    screener = StockScreener(broker, max_stocks=10, min_change_rate=0.0, min_volume=10_000_000)
    result = await screener.scan()
    assert "005930" in result
    assert "051910" not in result


async def test_scan_returns_held_on_empty_broker() -> None:
    broker = MockBroker()

    async def empty_top(*a, **kw):
        return []

    broker.get_top_volume_stocks = empty_top  # type: ignore[assignment]
    screener = StockScreener(broker, max_stocks=5)
    result = await screener.scan(held_symbols=["005930"])
    assert result == ["005930"]


async def test_score_ranking_prefers_high_volume(broker: MockBroker) -> None:
    screener = StockScreener(broker, max_stocks=2, min_change_rate=0.0, min_volume=0)
    result = await screener.scan()
    assert result[0] == "005930"
