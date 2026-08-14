from __future__ import annotations

import streamlit as st

from services.unified_research_contract import UnifiedResearchContext, WealthExposureContext
from services.wealth_exposure_bridge import build_wealth_exposure_context
from services.portfolio_intelligence_contract import PortfolioIntelligenceView


def render_portfolio_exposure_section(
    symbol: str,
    portfolio_view: PortfolioIntelligenceView | None = None,
    unified: UnifiedResearchContext | None = None,
) -> None:
    st.markdown("#### Portföy maruziyeti")
    exposure = (
        unified.wealth_exposure_context
        if unified and unified.wealth_exposure_context
        else build_wealth_exposure_context(portfolio_view, symbol)
    )
    _render_exposure(exposure)
    if unified and unified.portfolio_fit:
        st.markdown("**Portföy-tez ilişkisi**")
        for fit in unified.portfolio_fit:
            st.info(fit.statement)


def _render_exposure(exposure: WealthExposureContext) -> None:
    if not exposure.held:
        st.write(exposure.concentration_context or "Portföyde açık pozisyon yok.")
        for note in exposure.limitations:
            st.caption(note)
        return
    cols = st.columns(4)
    cols[0].metric("Tutulan", "Evet")
    cols[1].metric(
        "Ağırlık",
        f"%{exposure.portfolio_weight_pct:.1f}"
        if exposure.portfolio_weight_pct is not None
        else "veri mevcut değil",
    )
    cols[2].metric(
        "Piyasa değeri",
        f"{exposure.market_value:,.0f}" if exposure.market_value is not None else "veri mevcut değil",
    )
    cols[3].metric(
        "Gerçekleşmemiş K/Z",
        f"{exposure.unrealized_pl:,.0f}" if exposure.unrealized_pl is not None else "veri mevcut değil",
    )
    if exposure.concentration_context:
        st.caption(exposure.concentration_context)
    for note in exposure.limitations:
        st.caption(note)
