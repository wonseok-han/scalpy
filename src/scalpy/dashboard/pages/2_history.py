import pandas as pd
import streamlit as st

st.set_page_config(page_title="History - Scalpy", layout="wide")
st.title("체결 이력")

state = st.session_state

if "trades" not in state or not state.trades:
    st.info("체결 이력이 없습니다.")
else:
    rows = []
    for t in state.trades:
        rows.append(
            {
                "시간": t.executed_at.strftime("%Y-%m-%d %H:%M:%S"),
                "종목": t.symbol,
                "방향": t.side.value.upper(),
                "가격": f"{t.price:,.0f}",
                "수량": t.quantity,
                "전략": t.strategy,
                "PnL": f"{t.pnl:,.0f}",
            }
        )
    df = pd.DataFrame(rows)

    strategy_filter = st.selectbox("전략 필터", ["전체", *df["전략"].unique()])
    if strategy_filter != "전체":
        df = df[df["전략"] == strategy_filter]

    st.dataframe(df, use_container_width=True, hide_index=True)
