from datetime import date
from decimal import Decimal

import structlog
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.orm import Session

from scalpy.data.schema import Base, PositionRow, TradeRow

logger = structlog.get_logger()

_COMMISSION_RATE = Decimal("0.000147")
_SELL_TAX_RATE = Decimal("0.0018")


class TradeRepository:
    def __init__(self, database_url: str, mock: bool = True) -> None:
        self._engine = create_engine(database_url)
        self._mock = mock

    def create_tables(self) -> None:
        Base.metadata.create_all(self._engine)
        self._migrate_mock_column()

    def _migrate_mock_column(self) -> None:
        insp = inspect(self._engine)
        if not insp.has_table("trades"):
            return
        columns = {c["name"] for c in insp.get_columns("trades")}
        if "mock" not in columns:
            with self._engine.begin() as conn:
                conn.execute(text("ALTER TABLE trades ADD COLUMN mock BOOLEAN DEFAULT true"))
            logger.info("migration.added_mock_column")
        if "strategy" not in columns:
            with self._engine.begin() as conn:
                conn.execute(text("ALTER TABLE trades ADD COLUMN strategy VARCHAR(50) DEFAULT ''"))
                conn.execute(text("UPDATE trades SET strategy = 'factor' WHERE strategy = '' OR strategy IS NULL"))
                conn.execute(text("UPDATE positions SET strategy = 'factor' WHERE strategy = 'synced' OR strategy = ''"))
            logger.info("migration.added_strategy_column")

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
                    TradeRow.mock == self._mock,
                )
            ).all()
            for r in rows:
                existing[(r.order_no, r.order_date)] = r.tot_ccld_qty

            strat_map: dict[str, str] = {}
            pos_rows = session.scalars(
                select(PositionRow).where(PositionRow.closed_at.is_(None))
            ).all()
            for pr in pos_rows:
                strat_map[pr.symbol] = pr.strategy
            closed_pos = session.execute(
                select(PositionRow.symbol, PositionRow.strategy)
                .where(PositionRow.closed_at.isnot(None))
                .order_by(PositionRow.closed_at.desc())
            ).all()
            for cp in closed_pos:
                if cp.symbol not in strat_map:
                    strat_map[cp.symbol] = cp.strategy

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
                    symbol = t.get("symbol", "")
                    row = TradeRow(
                        order_no=order_no,
                        order_date=order_date,
                        symbol=symbol,
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
                        strategy=strat_map.get(symbol, ""),
                        fee=fee,
                        mock=self._mock,
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
        """sync 완료 후 sell 건의 pnl을 FIFO 매칭으로 재계산 (전체 기간 매수 대상)."""
        symbols = [r[0] for r in session.execute(
            select(TradeRow.symbol).where(
                TradeRow.order_date == order_date,
                TradeRow.mock == self._mock,
            ).group_by(TradeRow.symbol)
        ).all()]

        for symbol in symbols:
            buys = session.scalars(
                select(TradeRow).where(
                    TradeRow.symbol == symbol,
                    TradeRow.side == "buy",
                    TradeRow.mock == self._mock,
                ).order_by(TradeRow.order_date, TradeRow.ord_time)
            ).all()
            sells = session.scalars(
                select(TradeRow).where(
                    TradeRow.symbol == symbol,
                    TradeRow.side == "sell",
                    TradeRow.mock == self._mock,
                ).order_by(TradeRow.order_date, TradeRow.ord_time)
            ).all()

            buy_queue: list[tuple[int, float]] = []
            for b in buys:
                if b.tot_ccld_qty > 0 and b.avg_price > 0:
                    buy_queue.append((b.tot_ccld_qty, float(b.avg_price)))

            qi = 0
            remaining = buy_queue[0][0] if buy_queue else 0

            for sell in sells:
                if sell.avg_price == 0 or sell.tot_ccld_qty == 0:
                    sell.pnl = None
                    continue

                to_match = sell.tot_ccld_qty
                total_buy_cost = 0.0

                while to_match > 0 and qi < len(buy_queue):
                    take = min(to_match, remaining)
                    total_buy_cost += take * buy_queue[qi][1]
                    to_match -= take
                    remaining -= take
                    if remaining <= 0:
                        qi += 1
                        remaining = buy_queue[qi][0] if qi < len(buy_queue) else 0

                if to_match > 0:
                    sell.pnl = None
                    continue

                matched_qty = sell.tot_ccld_qty
                buy_avg = total_buy_cost / matched_qty
                buy_fee = int(total_buy_cost * float(_COMMISSION_RATE))
                sell.pnl = int((sell.avg_price - buy_avg) * matched_qty - sell.fee - buy_fee)

        session.commit()

    def recalc_all_pnl(self) -> int:
        """전체 종목의 pnl을 FIFO로 재계산. 반환값: 갱신된 sell 건수."""
        with Session(self._engine) as session:
            symbols = [r[0] for r in session.execute(
                select(TradeRow.symbol).where(
                    TradeRow.side == "sell",
                    TradeRow.mock == self._mock,
                ).group_by(TradeRow.symbol)
            ).all()]

            updated = 0
            for symbol in symbols:
                buys = session.scalars(
                    select(TradeRow).where(
                        TradeRow.symbol == symbol,
                        TradeRow.side == "buy",
                        TradeRow.mock == self._mock,
                    ).order_by(TradeRow.order_date, TradeRow.ord_time)
                ).all()
                sells = session.scalars(
                    select(TradeRow).where(
                        TradeRow.symbol == symbol,
                        TradeRow.side == "sell",
                        TradeRow.mock == self._mock,
                    ).order_by(TradeRow.order_date, TradeRow.ord_time)
                ).all()

                buy_queue: list[tuple[int, float]] = []
                for b in buys:
                    if b.tot_ccld_qty > 0 and b.avg_price > 0:
                        buy_queue.append((b.tot_ccld_qty, float(b.avg_price)))

                qi = 0
                remaining = buy_queue[0][0] if buy_queue else 0

                for sell in sells:
                    if sell.avg_price == 0 or sell.tot_ccld_qty == 0:
                        sell.pnl = None
                        continue

                    to_match = sell.tot_ccld_qty
                    total_buy_cost = 0.0

                    while to_match > 0 and qi < len(buy_queue):
                        take = min(to_match, remaining)
                        total_buy_cost += take * buy_queue[qi][1]
                        to_match -= take
                        remaining -= take
                        if remaining <= 0:
                            qi += 1
                            remaining = buy_queue[qi][0] if qi < len(buy_queue) else 0

                    if to_match > 0:
                        sell.pnl = None
                        continue

                    matched_qty = sell.tot_ccld_qty
                    buy_avg = total_buy_cost / matched_qty
                    buy_fee = int(total_buy_cost * float(_COMMISSION_RATE))
                    sell.pnl = int((sell.avg_price - buy_avg) * matched_qty - sell.fee - buy_fee)
                    updated += 1

            session.commit()
            logger.info("recalc_all_pnl.done", symbols=len(symbols), updated=updated)
            return updated

    def get_daily_pnl(self, day: date | None = None) -> int:
        day_str = (day or date.today()).strftime("%Y%m%d")
        with Session(self._engine) as session:
            result = session.scalar(
                select(func.coalesce(func.sum(TradeRow.pnl), 0)).where(
                    TradeRow.side == "sell",
                    TradeRow.order_date == day_str,
                    TradeRow.mock == self._mock,
                )
            )
            return int(result or 0)

    def get_daily_trade_count(self, day: date | None = None) -> int:
        day_str = (day or date.today()).strftime("%Y%m%d")
        with Session(self._engine) as session:
            return session.scalar(
                select(func.count(TradeRow.id)).where(
                    TradeRow.order_date == day_str,
                    TradeRow.mock == self._mock,
                )
            ) or 0

    def get_daily_fees(self, day: date | None = None) -> int:
        day_str = (day or date.today()).strftime("%Y%m%d")
        with Session(self._engine) as session:
            result = session.scalar(
                select(func.coalesce(func.sum(TradeRow.fee), 0)).where(
                    TradeRow.order_date == day_str,
                    TradeRow.mock == self._mock,
                )
            )
            return int(result or 0)


    def get_strategy_performance(self) -> dict[str, dict]:
        """trades 테이블에서 전략별 라운드트립(매수→매도) 기반 성과 집계."""
        with Session(self._engine) as session:
            symbols = [r[0] for r in session.execute(
                select(TradeRow.symbol).where(
                    TradeRow.side == "sell",
                    TradeRow.mock == self._mock,
                    TradeRow.strategy != "",
                ).group_by(TradeRow.symbol)
            ).all()]

            stats: dict[str, dict] = {}
            for symbol in symbols:
                buys = session.scalars(
                    select(TradeRow).where(
                        TradeRow.symbol == symbol,
                        TradeRow.side == "buy",
                        TradeRow.mock == self._mock,
                    ).order_by(TradeRow.order_date, TradeRow.ord_time)
                ).all()
                sells = session.scalars(
                    select(TradeRow).where(
                        TradeRow.symbol == symbol,
                        TradeRow.side == "sell",
                        TradeRow.mock == self._mock,
                    ).order_by(TradeRow.order_date, TradeRow.ord_time)
                ).all()

                buy_queue: list[tuple[int, float, str, str]] = []
                for b in buys:
                    if b.tot_ccld_qty > 0 and b.avg_price > 0:
                        buy_queue.append((b.tot_ccld_qty, float(b.avg_price), b.order_date, b.strategy))

                qi = 0
                remaining = buy_queue[0][0] if buy_queue else 0

                for sell in sells:
                    if sell.avg_price == 0 or sell.tot_ccld_qty == 0:
                        continue
                    strat = sell.strategy or (buy_queue[qi][3] if qi < len(buy_queue) else "")
                    if not strat:
                        continue

                    to_match = sell.tot_ccld_qty
                    total_buy_cost = 0.0
                    buy_date = buy_queue[qi][2] if qi < len(buy_queue) else sell.order_date

                    while to_match > 0 and qi < len(buy_queue):
                        take = min(to_match, remaining)
                        total_buy_cost += take * buy_queue[qi][1]
                        buy_date = buy_queue[qi][2]
                        to_match -= take
                        remaining -= take
                        if remaining <= 0:
                            qi += 1
                            remaining = buy_queue[qi][0] if qi < len(buy_queue) else 0

                    if to_match > 0:
                        continue

                    matched_qty = sell.tot_ccld_qty
                    buy_avg = total_buy_cost / matched_qty
                    buy_fee = int(total_buy_cost * float(_COMMISSION_RATE))
                    pnl = int((sell.avg_price - buy_avg) * matched_qty - sell.fee - buy_fee)
                    pnl_pct = round((sell.avg_price - buy_avg) / buy_avg * 100, 2) if buy_avg > 0 else 0.0
                    cross_day = buy_date != sell.order_date

                    s = stats.setdefault(strat, {
                        "trades": 0, "wins": 0, "losses": 0,
                        "total_pnl": 0, "max_drawdown": 0, "_peak": 0,
                        "intraday_trades": 0, "cross_day_trades": 0,
                        "avg_pnl_pct": 0.0, "_pnl_pcts": [],
                    })
                    s["trades"] += 1
                    s["total_pnl"] += pnl
                    s["_pnl_pcts"].append(pnl_pct)
                    if pnl > 0:
                        s["wins"] += 1
                    elif pnl < 0:
                        s["losses"] += 1
                    if cross_day:
                        s["cross_day_trades"] += 1
                    else:
                        s["intraday_trades"] += 1
                    if s["total_pnl"] > s["_peak"]:
                        s["_peak"] = s["total_pnl"]
                    dd = s["_peak"] - s["total_pnl"]
                    if dd > s["max_drawdown"]:
                        s["max_drawdown"] = dd

            for s in stats.values():
                s["win_rate"] = round(s["wins"] / s["trades"] * 100, 1) if s["trades"] > 0 else 0.0
                pcts = s.pop("_pnl_pcts")
                s["avg_pnl_pct"] = round(sum(pcts) / len(pcts), 2) if pcts else 0.0
                s["total_pnl"] = str(s["total_pnl"])
                s["max_drawdown"] = str(s["max_drawdown"])
                del s["_peak"]
            return stats

    def save_position_open(
        self, symbol: str, strategy: str, opened_at: "datetime | None" = None,
    ) -> None:
        from datetime import datetime as dt
        opened = opened_at or dt.now()
        with Session(self._engine) as session:
            existing = session.scalar(
                select(PositionRow).where(
                    PositionRow.symbol == symbol,
                    PositionRow.closed_at.is_(None),
                )
            )
            if existing:
                return
            session.add(PositionRow(
                symbol=symbol, side="buy", quantity=0,
                avg_price=0, strategy=strategy, opened_at=opened,
            ))
            session.commit()

    def close_position(self, symbol: str) -> None:
        from datetime import datetime as dt
        with Session(self._engine) as session:
            row = session.scalar(
                select(PositionRow).where(
                    PositionRow.symbol == symbol,
                    PositionRow.closed_at.is_(None),
                )
            )
            if row:
                row.closed_at = dt.now()
                session.commit()

    def get_open_position_times(self) -> dict[str, "datetime"]:
        with Session(self._engine) as session:
            rows = session.scalars(
                select(PositionRow).where(PositionRow.closed_at.is_(None))
            ).all()
            return {r.symbol: r.opened_at for r in rows}

    def get_position_strategies(self) -> dict[str, str]:
        """보유 종목별 전략명 조회. positions 테이블 우선, 없으면 trades 최근 매수 건."""
        with Session(self._engine) as session:
            result: dict[str, str] = {}
            pos_rows = session.scalars(
                select(PositionRow).where(PositionRow.closed_at.is_(None))
            ).all()
            for r in pos_rows:
                if r.strategy:
                    result[r.symbol] = r.strategy

            missing = session.scalars(
                select(TradeRow.symbol).where(
                    TradeRow.side == "buy",
                    TradeRow.strategy != "",
                    TradeRow.mock == self._mock,
                ).group_by(TradeRow.symbol)
            ).all()
            for symbol in missing:
                if symbol in result:
                    continue
                row = session.scalar(
                    select(TradeRow.strategy).where(
                        TradeRow.symbol == symbol,
                        TradeRow.side == "buy",
                        TradeRow.strategy != "",
                        TradeRow.mock == self._mock,
                    ).order_by(TradeRow.ord_time.desc()).limit(1)
                )
                if row:
                    result[symbol] = row
            return result

    def get_trades_today(self, day: date | None = None) -> list[dict]:
        day_str = (day or date.today()).strftime("%Y%m%d")
        with Session(self._engine) as session:
            rows = session.scalars(
                select(TradeRow)
                .where(TradeRow.order_date == day_str, TradeRow.mock == self._mock)
                .order_by(TradeRow.ord_time.desc())
            ).all()

            result = []
            for r in rows:
                entry: dict = {
                    "order_no": r.order_no,
                    "symbol": r.symbol,
                    "name": r.name,
                    "side": r.side,
                    "strategy": r.strategy or "",
                    "price": str(r.avg_price),
                    "quantity": r.tot_ccld_qty,
                    "ord_qty": r.ord_qty,
                    "ord_price": str(r.ord_price),
                    "tot_ccld_amt": str(r.tot_ccld_amt),
                    "rmn_qty": r.rmn_qty,
                    "fee": str(r.fee),
                    "pnl": str(r.pnl) if r.pnl is not None else "",
                    "pnl_pct": "",
                    "time": f"{r.ord_time[:2]}:{r.ord_time[2:4]}:{r.ord_time[4:6]}" if len(r.ord_time) >= 6 else r.ord_time,
                }
                if r.side == "sell" and r.pnl is not None and r.tot_ccld_amt > 0:
                    buy_cost = r.tot_ccld_amt - r.pnl + r.fee
                    if buy_cost > 0:
                        entry["pnl_pct"] = round(r.pnl / buy_cost * 100, 2)
                result.append(entry)
            return result
