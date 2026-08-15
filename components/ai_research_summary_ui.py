from __future__ import annotations

from typing import Callable, Optional

import streamlit as st
import streamlit.components.v1 as components

from services.ai_research_summary_contract import (
    AIResearchSummaryView,
    EVIDENCE_LEVEL_LABELS_TR,
)
from services.ui_formatters import format_datetime_tr

AI_SUMMARY_SECTION_PREFIX = "nabi-ai-research-summary"


def ai_summary_cache_key(symbol: str) -> str:
    return f"company_report_ai_summary_{str(symbol or '').strip().upper()}"


def ai_summary_identity_key(symbol: str) -> str:
    return f"company_report_ai_summary_identity_{str(symbol or '').strip().upper()}"


def ai_summary_scroll_to_key(symbol: str) -> str:
    return f"company_report_ai_summary_scroll_to_{str(symbol or '').strip().upper()}"


def ai_summary_section_anchor_id(symbol: str) -> str:
    normalized = str(symbol or "").strip().upper() or "UNKNOWN"
    return f"{AI_SUMMARY_SECTION_PREFIX}-{normalized}"


def ai_summary_llm_call_count_key(symbol: str) -> str:
    return f"company_report_ai_summary_llm_calls_{str(symbol or '').strip().upper()}"


def mark_ai_summary_scroll_target(symbol: str) -> None:
    st.session_state[ai_summary_scroll_to_key(symbol)] = True


def load_cached_ai_summary(symbol: str) -> tuple[Optional[AIResearchSummaryView], Optional[str]]:
    cached = st.session_state.get(ai_summary_cache_key(symbol))
    identity = st.session_state.get(ai_summary_identity_key(symbol))
    if isinstance(cached, AIResearchSummaryView):
        return cached, str(identity) if identity else None
    return None, None


def store_ai_summary(symbol: str, view: AIResearchSummaryView, *, identity: str) -> None:
    st.session_state[ai_summary_cache_key(symbol)] = view
    st.session_state[ai_summary_identity_key(symbol)] = identity
    if view.metadata is not None:
        current = int(st.session_state.get(ai_summary_llm_call_count_key(symbol), 0))
        st.session_state[ai_summary_llm_call_count_key(symbol)] = (
            current + view.metadata.llm_call_count
        )


def clear_ai_summary_cache(symbol: str) -> None:
    st.session_state.pop(ai_summary_cache_key(symbol), None)
    st.session_state.pop(ai_summary_identity_key(symbol), None)


def render_ai_summary_section_anchor(symbol: str) -> str:
    anchor_id = ai_summary_section_anchor_id(symbol)
    st.markdown(
        f'<div id="{anchor_id}" aria-label="Yapay Zeka Araştırma Özeti"></div>',
        unsafe_allow_html=True,
    )
    return anchor_id


def scroll_to_ai_summary_section(symbol: str) -> None:
    anchor_id = ai_summary_section_anchor_id(symbol)
    components.html(
        f"""
        <script>
            (function() {{
                const doc = window.parent.document;
                const target = doc.getElementById("{anchor_id}");
                if (target) {{
                    target.scrollIntoView({{ behavior: "smooth", block: "start" }});
                }}
            }})();
        </script>
        """,
        height=0,
        width=0,
    )


def maybe_scroll_to_ai_summary_section(symbol: str) -> None:
    if st.session_state.pop(ai_summary_scroll_to_key(symbol), False):
        scroll_to_ai_summary_section(symbol)


def _render_summary_content(view: AIResearchSummaryView) -> None:
    if view.status == "UNAVAILABLE":
        st.info(view.user_message or "AI araştırma özeti şu anda kullanılamıyor.")
        if view.metadata and view.metadata.validation_outcome:
            st.caption(f"Durum: {view.metadata.validation_outcome}")
        return

    if view.status == "VALIDATION_FAILED":
        st.warning(view.user_message or "AI özeti güvenlik doğrulamasından geçemedi.")
        if view.metadata and view.metadata.validation_outcome:
            st.caption(f"Doğrulama: {view.metadata.validation_outcome}")
        return

    evidence_label = EVIDENCE_LEVEL_LABELS_TR.get(view.evidence_level, view.evidence_level)
    st.markdown(f"**Kanıt düzeyi:** {evidence_label.upper()}")

    if view.financial_outlook:
        st.markdown("**Finansal görünüm**")
        st.write(view.financial_outlook)

    if view.valuation_summary:
        st.markdown("**Değerleme**")
        st.write(view.valuation_summary)

    if view.key_strengths:
        st.markdown("**Güçlü yönler**")
        for item in view.key_strengths:
            st.markdown(f"- {item}")

    weaknesses = [*view.key_weaknesses, *view.risks_to_watch]
    if weaknesses:
        st.markdown("**Zayıf yönler / riskler**")
        for item in weaknesses:
            st.markdown(f"- {item}")

    if view.missing_evidence:
        st.markdown("**Eksik kanıtlar**")
        for item in view.missing_evidence:
            st.markdown(f"- {item}")

    if view.monitoring_points:
        st.markdown("**İzlenecek göstergeler**")
        for item in view.monitoring_points:
            st.markdown(f"- {item}")

    if view.limitations:
        with st.expander("Sınırlamalar"):
            for item in view.limitations:
                st.caption(item)

    if view.metadata and view.metadata.validation_outcome == "persisted":
        date_label = format_datetime_tr(view.generated_at)
        st.caption(f"Kaydedilmiş AI araştırma özeti · {date_label}")
    elif view.metadata and view.metadata.cache_hit:
        st.caption("Önbellekten gösteriliyor.")
    elif view.generated_at:
        st.caption(f"Oluşturulma: {view.generated_at}")


def render_ai_research_summary_section(
    view: Optional[AIResearchSummaryView],
    *,
    feature_enabled: bool,
    symbol: str = "",
    generate_callback: Optional[Callable[[], AIResearchSummaryView]] = None,
    display_polish_callback: Optional[Callable[[AIResearchSummaryView], AIResearchSummaryView]] = None,
    stale_context_hint: bool = False,
) -> None:
    """Render the AI summary section.

    Page contract: pass ``generate_callback`` to run same-run generation on button
    click (exactly one invocation per click). Do not call ``st.rerun()`` from the page.
    Pass ``display_polish_callback`` to re-apply deterministic display polish when
    rendering cached AVAILABLE summaries.
    """
    normalized_symbol = str(symbol or (view.symbol if view else "")).strip().upper()
    render_ai_summary_section_anchor(normalized_symbol)
    st.subheader("Yapay Zeka Araştırma Özeti")
    st.caption(
        "Bu bölüm mevcut NABI araştırma verilerini özetler; yeni veri üretmez ve yatırım talimatı değildir."
    )

    if not feature_enabled:
        st.info("AI araştırma özeti şu anda etkin değil.")
        maybe_scroll_to_ai_summary_section(normalized_symbol)
        return

    if stale_context_hint and (view is None or view.status != "AVAILABLE"):
        st.info("Mevcut araştırma verileri değişti. Yeni AI özeti oluşturulabilir.")

    show_generate_button = view is None or view.status != "AVAILABLE"
    clicked = False
    if show_generate_button:
        button_key = f"company_report_ai_summary_generate_btn_{normalized_symbol or 'unknown'}"
        clicked = st.button("AI özetini oluştur", key=button_key)

    active_view = view
    if (
        active_view is not None
        and active_view.status == "AVAILABLE"
        and display_polish_callback is not None
        and not clicked
    ):
        active_view = display_polish_callback(active_view)
    if clicked and generate_callback is not None:
        with st.spinner("AI özeti oluşturuluyor..."):
            active_view = generate_callback()
        mark_ai_summary_scroll_target(normalized_symbol)

    if active_view is None:
        st.info("Özet henüz oluşturulmadı.")
        maybe_scroll_to_ai_summary_section(normalized_symbol)
        return

    _render_summary_content(active_view)
    maybe_scroll_to_ai_summary_section(normalized_symbol)
