from __future__ import annotations

from typing import Callable, Optional, Sequence

import streamlit as st

from components.nabi_design_system import render_status_badge
from services.monitor_contract import MonitorEventView
from services.portfolio_intelligence_charts import build_monitor_materiality_chart

CATEGORY_LABELS = {
    "portfolio": "Portföy",
    "research": "Araştırma",
    "financial": "Finansal",
    "filing": "Bildirim",
    "thesis": "Tez",
    "participation": "Katılım",
    "wealth": "Wealth",
}

MATERIALITY_LABELS = {
    "critical": ("Kritik", "danger"),
    "high": ("Yüksek", "warning"),
    "medium": ("Orta", "info"),
    "low": ("Düşük", "neutral"),
    "info": ("Bilgi", "neutral"),
}

REVIEW_LABELS = {
    "new": ("Yeni", "info"),
    "reviewed": ("İncelendi", "success"),
    "dismissed": ("Kapatıldı", "neutral"),
}


def render_monitor_filters() -> tuple[Optional[str], Optional[str], bool]:
    col1, col2, col3 = st.columns(3)
    with col1:
        category = st.selectbox(
            "Kategori",
            options=["Tümü", *CATEGORY_LABELS.keys()],
            format_func=lambda value: "Tümü" if value == "Tümü" else CATEGORY_LABELS.get(value, value),
        )
    with col2:
        review = st.selectbox(
            "Durum",
            options=["Tümü", "new", "reviewed", "dismissed"],
            format_func=lambda value: {
                "Tümü": "Tümü",
                "new": "Yeni",
                "reviewed": "İncelendi",
                "dismissed": "Kapatıldı",
            }.get(value, value),
        )
    with col3:
        held_only = st.checkbox("Yalnızca tutulan semboller", value=False)
    return (
        None if category == "Tümü" else category,
        None if review == "Tümü" else review,
        held_only,
    )


def _materiality_badge(materiality: str) -> str:
    label, tone = MATERIALITY_LABELS.get(materiality, (materiality.upper(), "neutral"))
    return render_status_badge(label, tone)


def _review_badge(review_status: str) -> str:
    label, tone = REVIEW_LABELS.get(review_status, (review_status, "neutral"))
    return render_status_badge(label, tone)


def render_monitor_event_card(
    event: MonitorEventView,
    *,
    on_review: Optional[Callable[[str], None]] = None,
    on_dismiss: Optional[Callable[[str], None]] = None,
    on_ai: Optional[Callable[[str], None]] = None,
) -> None:
    border = "2px solid #b42318" if event.materiality in {"critical", "high"} else "1px solid #e2e8f0"
    with st.container(border=True):
        header_cols = st.columns([3, 1, 1])
        header_cols[0].markdown(f"**{event.title}**")
        header_cols[1].markdown(_materiality_badge(event.materiality), unsafe_allow_html=True)
        header_cols[2].markdown(_review_badge(event.review_status), unsafe_allow_html=True)
        st.caption(
            f"{CATEGORY_LABELS.get(event.event_category, event.event_category)} · "
            f"{event.occurred_at[:10] if event.occurred_at else '—'}"
        )
        st.write(event.summary)
        if event.portfolio_impact and event.portfolio_impact.held:
            weight = event.portfolio_impact.portfolio_weight
            weight_text = f"%{weight:.1f}" if weight is not None else "bilinmiyor"
            st.markdown(
                f"Portföy etkisi: tutuluyor · ağırlık {weight_text} · "
                f"{event.portfolio_impact.account_count} hesap"
            )
        elif event.portfolio_impact:
            st.markdown("Portföy etkisi: tutulmuyor")
        if event.thesis_relevance and event.thesis_relevance.relevance != "none":
            st.info(event.thesis_relevance.explanation)
        if event.evidence_reference:
            st.caption(f"Kanıt: {event.evidence_type or 'kaynak'} · {event.evidence_reference}")
        cols = st.columns(3)
        if on_review and event.review_status == "new":
            if cols[0].button("İncelendi", key=f"review_{event.event_id}"):
                on_review(event.event_id)
        if on_dismiss and event.review_status != "dismissed":
            if cols[1].button("Reddet", key=f"dismiss_{event.event_id}"):
                on_dismiss(event.event_id)
        if on_ai:
            if cols[2].button("AI ile değerlendir", key=f"ai_{event.event_id}"):
                on_ai(event.event_id)


def render_monitor_feed(events: Sequence[MonitorEventView], **callbacks) -> None:
    if not events:
        st.info("Şu anda incelemen gereken yeni olay yok.")
        return
    st.altair_chart(build_monitor_materiality_chart(events), use_container_width=True)
    for event in events:
        render_monitor_event_card(event, **callbacks)


def render_daily_brief_summary(brief) -> None:
    counts = brief.event_counts
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Toplam olay", counts.get("total", 0))
    c2.metric("Yüksek/Kritik", counts.get("high_critical", 0))
    c3.metric("Portföy etkili", len(brief.portfolio_affected_events))
    c4.metric("İncelenmemiş", counts.get("unreviewed", 0))
    if brief.unresolved_attention:
        st.warning("Dikkat: " + "; ".join(brief.unresolved_attention[:5]))
    if brief.limitations:
        with st.expander("Veri kalitesi / sınırlar"):
            for item in brief.limitations:
                st.markdown(f"- {item}")
