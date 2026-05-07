import streamlit as st

st.set_page_config(page_title="Strategy - Scalpy", layout="wide")
st.title("전략별 성과 비교")

state = st.session_state

if "trades" not in state or not state.trades:
    st.info("체결 데이터가 없습니다. 봇을 실행한 후 확인해주세요.")
else:
    from scalpy.dashboard.components.performance import render_performance

    render_performance(state.trades)
