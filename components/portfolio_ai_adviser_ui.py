from __future__ import annotations

from typing import Optional

import streamlit as st

from services.portfolio_ai_adviser_contract import PortfolioAIAdviserResponse


def render_portfolio_ai_adviser_section(
    *,
    portfolio_id: str,
    response: Optional[PortfolioAIAdviserResponse],
    semantic_identity: str,
    stale: bool,
    on_generate,
) -> None:
    st.subheader("AI Portföy Değerlendirmesi")
    st.caption(
        "AI yalnızca yapılandırılmış portföy bağlamını yorumlar. "
        "Sayfa yenilemesinde otomatik LLM çağrısı yapılmaz."
    )
    if stale and response is not None:
        st.warning("Portföy bağlamı değişmiş olabilir; kayıtlı AI yanıtı güncel olmayabilir.")

    if response is None or response.status != "AVAILABLE":
        st.info("Henüz AI portföy değerlendirmesi yok.")
    else:
        if response.generated_at:
            st.caption(f"Oluşturulma: {response.generated_at[:19]}")
        if response.executive_summary:
            st.markdown(response.executive_summary)
        if response.what_changed:
            st.markdown("**Ne değişti**")
            for item in response.what_changed:
                st.markdown(f"- {item}")
        if response.portfolio_implications:
            st.markdown("**Portföy etkileri**")
            for item in response.portfolio_implications:
                st.markdown(f"- {item}")
        if response.thesis_watch:
            st.markdown("**Tez izleme**")
            for item in response.thesis_watch:
                st.markdown(f"- {item}")
        if response.participation_watch:
            st.markdown("**Katılım izleme**")
            for item in response.participation_watch:
                st.markdown(f"- {item}")
        if response.research_gaps:
            st.markdown("**Araştırma boşlukları**")
            for item in response.research_gaps:
                st.markdown(f"- {item}")
        if response.questions_to_review:
            st.markdown("**İnceleme soruları**")
            for item in response.questions_to_review:
                st.markdown(f"- {item}")
        if response.limitations:
            st.markdown("**Sınırlar**")
            for item in response.limitations:
                st.markdown(f"- {item}")
        if response.metadata:
            st.caption(
                f"LLM çağrısı: {response.metadata.llm_call_count} · "
                f"Kimlik: {semantic_identity[:12]}…"
            )

    if st.button("AI portföy değerlendirmesi oluştur", key="pi_ai_generate"):
        on_generate()
