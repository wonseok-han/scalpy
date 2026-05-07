import pandas as pd
import streamlit as st

from scalpy.core.models import Position


def render_position_table(positions: list[Position]) -> None:
    st.subheader("포지션 현황")
    if not positions:
        st.info("보유 포지션 없음")
        return

    rows = []
    for p in positions:
        pnl_ratio = (
            float((p.current_price - p.avg_price) / p.avg_price * 100)
            if p.avg_price > 0
            else 0.0
        )
        rows.append(
            {
                "종목": p.symbol,
                "수량": p.quantity,
                "평균단가": f"{p.avg_price:,.0f}",
                "현재가": f"{p.current_price:,.0f}",
                "수익률": f"{pnl_ratio:+.2f}%",
                "미실현PnL": f"{p.unrealized_pnl:,.0f}",
                "전략": p.strategy,
            }
        )

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)
