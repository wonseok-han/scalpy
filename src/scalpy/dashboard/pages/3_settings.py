import streamlit as st

from scalpy.config import settings

st.set_page_config(page_title="Settings - Scalpy", layout="wide")
st.title("설정")

st.subheader("매매 설정")
st.text_input("종목 코드 (쉼표 구분)", value=",".join(settings.get("trading.symbols", [])))
stop_loss = settings.get("trading.stop_loss_ratio", 0.02) * 100
take_profit = settings.get("trading.take_profit_ratio", 0.03) * 100
st.number_input("손절 비율 (%)", value=stop_loss, step=0.1)
st.number_input("익절 비율 (%)", value=take_profit, step=0.1)
st.number_input("최대 포지션 수량", value=settings.get("trading.max_position_size", 100), step=10)

st.subheader("전략")
enabled = settings.get("strategies.enabled", [])
st.multiselect("활성 전략", ["ma_cross", "bollinger", "rsi", "orderbook", "vwap"], default=enabled)

st.subheader("환경")
st.toggle("모의투자 모드", value=settings.get("mock", True), disabled=True)
st.caption("모의투자 전환은 config/settings.toml에서만 가능합니다 (안전 정책)")
