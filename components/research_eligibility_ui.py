from __future__ import annotations

import streamlit as st

from services.research_eligibility_contract import (
    RESEARCH_STATUS_FAIL,
    RESEARCH_STATUS_INSUFFICIENT_DATA,
    RESEARCH_STATUS_UNKNOWN,
    ResearchEligibilityResult,
)


def render_research_eligibility_block(view: ResearchEligibilityResult) -> None:
    st.subheader("Araştırma Durumu")
    if view.status == RESEARCH_STATUS_FAIL:
        st.error(view.block_message)
    else:
        st.warning(view.block_message)
    if view.participation_status:
        st.caption(f"Katılım durumu: {view.participation_status}")
    if view.limitations:
        for item in view.limitations[:6]:
            st.caption(f"• {item}")
    if view.status in {RESEARCH_STATUS_UNKNOWN, RESEARCH_STATUS_INSUFFICIENT_DATA}:
        st.info(
            "Bu sonuç halal/non-halal hükmü değildir; yalnızca mevcut katılım "
            "tarama kanıtının yetersiz veya doğrulanamadığını gösterir."
        )
