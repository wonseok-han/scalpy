import streamlit as st

from scalpy.config import settings
from scalpy.dashboard.components.performance import render_performance
from scalpy.dashboard.components.position_table import render_position_table
from scalpy.dashboard.components.price_ticker import render_price_ticker
from scalpy.dashboard.components.signal_log import render_signal_log


def main() -> None:
    st.set_page_config(page_title="Scalpy Dashboard", layout="wide")

    mock_label = "모의투자" if settings.get("mock", True) else "실거래"

    st.title("Scalpy Dashboard")
    st.caption(f"[{mock_label}]")

    state = st.session_state

    if "prices" not in state:
        state.prices = {}
    if "positions" not in state:
        state.positions = []
    if "signals" not in state:
        state.signals = []
    if "trades" not in state:
        state.trades = []

    col_left, col_right = st.columns(2)

    with col_left:
        render_price_ticker(state.prices)
        render_signal_log(state.signals)

    with col_right:
        render_position_table(state.positions)
        render_performance(state.trades)


if __name__ == "__main__":
    main()
