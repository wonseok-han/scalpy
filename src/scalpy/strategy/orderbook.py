from datetime import datetime
from decimal import Decimal

from scalpy.core.enums import Side
from scalpy.core.models import Signal
from scalpy.strategy.base import BaseStrategy


class OrderbookStrategy(BaseStrategy):
    name = "orderbook"
    display_name = "호가창 불균형"
    description = "Orderbook Imbalance — buy when bid volume dominates, sell when ask dominates"

    def __init__(self) -> None:
        self._init_base()
        self.bid_ask_ratio_threshold: float = 1.5

    async def on_tick(self, symbol: str, price: Decimal, volume: int) -> Signal | None:
        return None

    async def on_orderbook(
        self,
        symbol: str,
        asks: list[tuple[Decimal, int]],
        bids: list[tuple[Decimal, int]],
    ) -> Signal | None:
        if not asks or not bids:
            return None

        total_ask_vol = sum(qty for _, qty in asks)
        total_bid_vol = sum(qty for _, qty in bids)

        if total_ask_vol == 0 or total_bid_vol == 0:
            return None

        bid_ask_ratio = total_bid_vol / total_ask_vol

        best_bid_price = bids[0][0]
        best_ask_price = asks[0][0]
        mid_price = (best_bid_price + best_ask_price) / 2

        if bid_ask_ratio >= self.bid_ask_ratio_threshold and self._check_cooldown(symbol, "BUY"):
            return Signal(
                symbol, Side.BUY, self.name, mid_price, 0, 0.55, datetime.now()
            )

        inverse_ratio = total_ask_vol / total_bid_vol
        if inverse_ratio >= self.bid_ask_ratio_threshold and self._check_cooldown(symbol, "SELL"):
            return Signal(
                symbol, Side.SELL, self.name, mid_price, 0, 0.55, datetime.now()
            )

        return None
