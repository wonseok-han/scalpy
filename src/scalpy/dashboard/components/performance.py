import pandas as pd
import streamlit as st

from scalpy.core.models import TradeRecord


def render_performance(trades: list[TradeRecord]) -> None:
    st.subheader("전략별 성과")
    if not trades:
        st.info("체결 이력 없음")
        return

    stats: dict[str, dict[str, int | float]] = {}
    for t in trades:
        if t.strategy not in stats:
            stats[t.strategy] = {"wins": 0, "losses": 0, "total_pnl": 0.0}
        s = stats[t.strategy]
        if t.pnl > 0:
            s["wins"] += 1
        elif t.pnl < 0:
            s["losses"] += 1
        s["total_pnl"] += float(t.pnl)

    rows = []
    for strategy, s in stats.items():
        total = s["wins"] + s["losses"]
        win_rate = s["wins"] / total * 100 if total > 0 else 0.0
        rows.append(
            {
                "전략": strategy,
                "승": s["wins"],
                "패": s["losses"],
                "승률": f"{win_rate:.1f}%",
                "총 PnL": f"{s['total_pnl']:,.0f}",
            }
        )

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)
