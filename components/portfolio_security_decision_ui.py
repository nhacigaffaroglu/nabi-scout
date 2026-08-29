from __future__ import annotations

import streamlit as st

from services.portfolio_security_decision_contract import PortfolioSecurityDecision


def render_portfolio_security_decision_section(
    decision: PortfolioSecurityDecision,
) -> None:
    st.subheader("Portfolio Decision")
    st.caption(
        "Bu portföy için 8E kararı. Yatırım tavsiyesi değildir ve tutar önermez."
    )
    cols = st.columns(4)
    cols[0].metric("Karar", decision.decision or "INSUFFICIENT_DATA")
    cols[1].metric(
        "Artırım uygun",
        "evet" if decision.exposure_increase_allowed else "hayır",
    )
    cols[2].metric("Katılım", decision.participation_status or "—")
    cols[3].metric("SI durum", decision.security_intelligence_state or "—")
    if decision.primary_reasons:
        st.caption("Gerekçe: " + ", ".join(decision.primary_reasons))
    if decision.blocking_reasons:
        st.caption("Engeller: " + ", ".join(decision.blocking_reasons))
    if decision.risk_flags:
        st.caption("Risk: " + ", ".join(decision.risk_flags))
