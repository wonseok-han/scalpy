from datetime import date
from decimal import Decimal

import structlog
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from scalpy.data.schema import Base, TradeRow

logger = structlog.get_logger()

_COMMISSION_RATE = Decimal("0.00015")
_SELL_TAX_RATE = Decimal("0.0018")


class TradeRepository:
    def __init__(self, database_url: str) -> None:
        self._engine = create_engine(database_url)

    def create_tables(self) -> None:
        Base.metadata.create_all(self._engine)

    def recreate_trades_table(self) -> None:
        TradeRow.__table__.drop(self._engine, checkfirst=True)
        TradeRow.__table__.create(self._engine, checkfirst=True)

    def sync_trades(self, trades: list[dict]) -> int:
        """ccld API 데이터를 DB에 upsert. (order_no, order_date) 기준."""
        if not trades:
            return 0

        new_count = 0
        update_count = 0

        with Session(self._engine) as session:
            existing: dict[tuple[str, str], int] = {}
            today = date.today().strftime("%Y%m%d")
            rows = session.execute(
                select(TradeRow.order_no, TradeRow.order_date, TradeRow.tot_ccld_qty).where(
                    TradeRow.order_date == today,
                )
            ).all()
            for r in rows:
                existing[(r.order_no, r.order_date)] = r.tot_ccld_qty

            for t in trades:
                order_no = t.get("order_no", "")
                order_date = t.get("order_date", "") or today
                if not order_no:
                    continue

                key = (order_no, order_date)
                prev_qty = existing.get(key)

                if prev_qty is not None and prev_qty == t.get("tot_ccld_qty", 0):
                    continue

                fee = self._calc_fee(t)

                if prev_qty is None:
                    row = TradeRow(
                        order_no=order_no,
                        order_date=order_date,
                        symbol=t.get("symbol", ""),
                        name=t.get("name", ""),
                        side=t.get("side", ""),
                        ord_qty=t.get("ord_qty", 0),
                        ord_price=t.get("ord_price", 0),
                        ord_time=t.get("ord_time", ""),
                        tot_ccld_qty=t.get("tot_ccld_qty", 0),
                        avg_price=t.get("avg_price", 0),
                        tot_ccld_amt=t.get("tot_ccld_amt", 0),
                        rmn_qty=t.get("rmn_qty", 0),
                        orgn_order_no=t.get("orgn_order_no", ""),
                        ord_dvsn_cd=t.get("ord_dvsn_cd", ""),
                        cncl_yn=t.get("cncl_yn", ""),
                        fee=fee,
                    )
                    session.add(row)
                    existing[key] = t.get("tot_ccld_qty", 0)
                    new_count += 1
                else:
                    session.execute(
                        TradeRow.__table__.update()
                        .where(
                            TradeRow.order_no == order_no,
                            TradeRow.order_date == order_date,
                        )
                        .values(
                            tot_ccld_qty=t.get("tot_ccld_qty", 0),
                            avg_price=t.get("avg_price", 0),
                            tot_ccld_amt=t.get("tot_ccld_amt", 0),
                            rmn_qty=t.get("rmn_qty", 0),
                            fee=fee,
                        )
                    )
                    existing[key] = t.get("tot_ccld_qty", 0)
                    update_count += 1

            total = new_count + update_count
            if total:
                session.commit()
                self._recalc_pnl(session, today)
                logger.info("trade_sync.committed", new=new_count, updated=update_count)
        return new_count + update_count

    def _calc_fee(self, t: dict) -> int:
        amt = t.get("tot_ccld_amt", 0)
        commission = int(amt * float(_COMMISSION_RATE))
        if t.get("side") == "sell":
            tax = int(amt * float(_SELL_TAX_RATE))
            return commission + tax
        return commission

    def _recalc_pnl(self, session: Session, order_date: str) -> None:
        """sync 완료 후 sell 건의 pnl을 일괄 재계산."""
        buy_agg = session.execute(
            select(
                TradeRow.symbol,
                func.sum(TradeRow.tot_ccld_amt).label("total_amt"),
                func.sum(TradeRow.tot_ccld_qty).label("total_qty"),
            ).where(
                TradeRow.side == "buy",
                TradeRow.order_date == order_date,
            ).group_by(TradeRow.symbol)
        ).all()
        buy_avgs: dict[str, float] = {}
        for row in buy_agg:
            if row.total_qty and row.total_qty > 0:
                buy_avgs[row.symbol] = row.total_amt / row.total_qty

        sells = session.scalars(
            select(TradeRow).where(
                TradeRow.side == "sell",
                TradeRow.order_date == order_date,
            )
        ).all()

        for sell in sells:
            buy_avg = buy_avgs.get(sell.symbol)
            if buy_avg is None or sell.avg_price == 0 or sell.tot_ccld_qty == 0:
                sell.pnl = None
                continue
            buy_fee = int(buy_avg * sell.tot_ccld_qty * float(_COMMISSION_RATE))
            sell.pnl = int((sell.avg_price - buy_avg) * sell.tot_ccld_qty - sell.fee - buy_fee)

        session.commit()

    def get_daily_pnl(self, day: date | None = None) -> int:
        day_str = (day or date.today()).strftime("%Y%m%d")
        with Session(self._engine) as session:
            result = session.scalar(
                select(func.coalesce(func.sum(TradeRow.pnl), 0)).where(
                    TradeRow.side == "sell",
                    TradeRow.order_date == day_str,
                )
            )
            return int(result or 0)

    def get_daily_trade_count(self, day: date | None = None) -> int:
        day_str = (day or date.today()).strftime("%Y%m%d")
        with Session(self._engine) as session:
            return session.scalar(
                select(func.count(TradeRow.id)).where(
                    TradeRow.order_date == day_str,
                )
            ) or 0

    def get_daily_fees(self, day: date | None = None) -> int:
        day_str = (day or date.today()).strftime("%Y%m%d")
        with Session(self._engine) as session:
            result = session.scalar(
                select(func.coalesce(func.sum(TradeRow.fee), 0)).where(
                    TradeRow.order_date == day_str,
                )
            )
            return int(result or 0)

    def get_trades_today(self, day: date | None = None) -> list[dict]:
        day_str = (day or date.today()).strftime("%Y%m%d")
        with Session(self._engine) as session:
            rows = session.scalars(
                select(TradeRow)
                .where(TradeRow.order_date == day_str)
                .order_by(TradeRow.ord_time.desc())
            ).all()

            return [
                {
                    "order_no": r.order_no,
                    "symbol": r.symbol,
                    "name": r.name,
                    "side": r.side,
                    "price": str(r.avg_price),
                    "quantity": r.tot_ccld_qty,
                    "ord_qty": r.ord_qty,
                    "ord_price": str(r.ord_price),
                    "tot_ccld_amt": str(r.tot_ccld_amt),
                    "rmn_qty": r.rmn_qty,
                    "fee": str(r.fee),
                    "pnl": str(r.pnl) if r.pnl is not None else "",
                    "time": f"{r.ord_time[:2]}:{r.ord_time[2:4]}:{r.ord_time[4:6]}" if len(r.ord_time) >= 6 else r.ord_time,
                }
                for r in rows
            ]
