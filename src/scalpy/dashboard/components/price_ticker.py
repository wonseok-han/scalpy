from decimal import Decimal

import streamlit as st


def render_price_ticker(prices: dict[str, Decimal]) -> None:
    st.subheader("실시간 시세")
    if not prices:
        st.info("시세 데이터 없음")
        return

    cols = st.columns(len(prices))
    for col, (symbol, price) in zip(cols, prices.items(), strict=False):
        col.metric(label=symbol, value=f"{price:,.0f}")
