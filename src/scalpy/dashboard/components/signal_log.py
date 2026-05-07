import streamlit as st

from scalpy.core.models import Signal


def render_signal_log(signals: list[Signal], max_rows: int = 20) -> None:
    st.subheader("전략 신호 로그")
    if not signals:
        st.info("신호 없음")
        return

    recent = signals[-max_rows:]
    for sig in reversed(recent):
        side_color = "🟢" if sig.side.value == "buy" else "🔴"
        st.text(
            f"{side_color} [{sig.strategy}] {sig.symbol} "
            f"{sig.side.value.upper()} {sig.price:,.0f} "
            f"({sig.timestamp:%H:%M:%S})"
        )
