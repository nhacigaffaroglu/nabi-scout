"""Fırsatlar Opportunity Center UI. Composition only; no writes or providers."""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

import pandas as pd
import streamlit as st

from components.nabi_design_system import (
    inject_nabi_theme,
    render_page_header,
    render_section_title,
    render_status_badge,
)
from services.candidate_pipeline_presentation import present_candidate_display_row
from services.opportunity_center_presentation import (
    ADVANCED_TITLE,
    ALL_CANDIDATES_LABEL,
    ALL_RESEARCH_LABEL,
    ALL_WATCHLIST_LABEL,
    CANDIDATE_POOL_PAGE,
    COMPANY_REPORT_PAGE,
    DISCOVERY_TITLE,
    INSPECT_LABEL,
    RESEARCH_PAGE,
    RESEARCH_TITLE,
    SCANNER_PAGE,
    TODAY_TITLE,
    UNIVERSE_PAGE,
    WATCHLIST_PAGE,
    WATCHLIST_TITLE,
    OpportunityCenterView,
    TodayOpportunityCard,
)
from services.research_workflow_service import normalize_research_status
from services.ui_formatters import format_research_status
from services.ui_table_headers import apply_display_headers


def _open_company_report(symbol: str, candidate: Optional[Mapping[str, Any]] = None) -> None:
    payload = dict(candidate or {})
    payload["symbol"] = symbol
    st.session_state["company_report_candidate"] = payload
    st.query_params["symbol"] = symbol
    st.switch_page(COMPANY_REPORT_PAGE)


def _render_hero(view: OpportunityCenterView) -> None:
    if view.hero.kpis:
        cols = st.columns(len(view.hero.kpis))
        for col, kpi in zip(cols, view.hero.kpis):
            col.metric(kpi.label, kpi.value)
    st.caption(view.hero.recommendation)


def _render_today_card(card: TodayOpportunityCard, index: int) -> None:
    tone = "success" if card.decision == "GÜÇLÜ ADAY" else "info"
    with st.container(border=True):
        st.markdown(
            f"**{card.symbol}** · {card.company_name} "
            + render_status_badge(card.decision, tone),
            unsafe_allow_html=True,
        )
        meta = [card.participation_label]
        if card.nabi_score is not None:
            meta.append(f"NABI Score {card.nabi_score:.1f}")
        if card.price_label:
            meta.append(card.price_label)
        st.caption(" · ".join(meta))
        if card.why:
            st.markdown(card.why)
        if card.risk:
            st.caption(f"Önemli sınırlama: {card.risk}")
        if st.button(INSPECT_LABEL, key=f"firsat_inspect_{card.symbol}_{index}", type="primary"):
            _open_company_report(card.symbol)


def _render_research(view: OpportunityCenterView) -> None:
    render_section_title(RESEARCH_TITLE)
    if view.research.headline:
        st.caption(view.research.headline)
    if view.research.items:
        for index, item in enumerate(view.research.items):
            prefix = "Veri eksik · " if item.exceptional else ""
            st.markdown(f"**{item.symbol}** · {item.company_name}")
            st.caption(f"{prefix}{item.summary}")
            if st.button(
                INSPECT_LABEL,
                key=f"firsat_research_{item.symbol}_{index}",
            ):
                _open_company_report(item.symbol)
    else:
        st.caption(view.research.empty_copy)
    if st.button(ALL_RESEARCH_LABEL, key="firsat_all_research"):
        st.switch_page(RESEARCH_PAGE)


def _render_watchlist(view: OpportunityCenterView) -> None:
    render_section_title(WATCHLIST_TITLE)
    if not view.watchlist.available:
        st.caption(view.watchlist.empty_copy)
    elif view.watchlist.items:
        for index, item in enumerate(view.watchlist.items):
            decision = f" · {item.decision}" if item.decision else ""
            st.markdown(f"**{item.symbol}** · {item.company_name}{decision}")
            st.caption(item.change)
            if st.button(
                INSPECT_LABEL,
                key=f"firsat_watch_{item.symbol}_{index}",
            ):
                _open_company_report(item.symbol)
    else:
        st.caption(view.watchlist.empty_copy)
    if st.button(ALL_WATCHLIST_LABEL, key="firsat_all_watchlist"):
        st.switch_page(WATCHLIST_PAGE)


def _render_discoveries(view: OpportunityCenterView) -> None:
    render_section_title(
        DISCOVERY_TITLE,
        description="Yeni keşfedilenler ve değerlendirme bekleyenler.",
    )
    if not view.discoveries.available:
        st.caption(view.discoveries.empty_copy)
        return
    chips = []
    if view.discoveries.new_count:
        chips.append(f"Yeni keşfedilenler: {view.discoveries.new_count}")
    if view.discoveries.waiting_count:
        chips.append(f"Değerlendirme bekleyenler: {view.discoveries.waiting_count}")
    if chips:
        st.caption(" · ".join(chips))
    if view.discoveries.items:
        for item in view.discoveries.items:
            st.markdown(f"**{item.symbol}** · {item.status_label}")
    else:
        st.caption(view.discoveries.empty_copy)


def _render_all_candidates(candidates: Sequence[Mapping[str, Any]]) -> None:
    with st.expander(ALL_CANDIDATES_LABEL, expanded=False):
        if not candidates:
            st.caption("Henüz aday yok.")
            return
        visible = [
            "symbol",
            "company_name",
            "current_price",
            "nabi_score",
            "decision",
            "participation_status",
            "research_status",
        ]
        display = pd.DataFrame([present_candidate_display_row(row) for row in candidates])
        if "research_status" in display.columns:
            display["research_status"] = display["research_status"].apply(
                lambda value: format_research_status(normalize_research_status(value))
            )
        present = [column for column in visible if column in display.columns]
        st.dataframe(
            apply_display_headers(display, columns=present),
            use_container_width=True,
            hide_index=True,
        )
        st.page_link(CANDIDATE_POOL_PAGE, label="Aday listesini yönet", icon="🎯")


def _render_advanced_tools() -> None:
    with st.expander(ADVANCED_TITLE, expanded=False):
        st.caption("Teknik tarama ve evren araçları. Birincil karar yüzeyi değildir.")
        st.page_link(UNIVERSE_PAGE, label="Evren oluştur", icon="🌌")
        st.page_link(SCANNER_PAGE, label="Tarama çalıştır", icon="🔭")
        st.page_link(RESEARCH_PAGE, label="Araştırma ayrıntıları", icon="🔬")
        st.page_link(CANDIDATE_POOL_PAGE, label="Aday listesi", icon="🎯")
        st.page_link(WATCHLIST_PAGE, label="İzleme listesi", icon="⭐")


def render_opportunity_center(
    view: OpportunityCenterView,
    *,
    candidates: Sequence[Mapping[str, Any]] = (),
) -> None:
    inject_nabi_theme()
    render_page_header(view.title, caption=view.caption)
    _render_hero(view)

    render_section_title(TODAY_TITLE)
    if view.today:
        for index, card in enumerate(view.today):
            _render_today_card(card, index)
    else:
        st.info(view.today_empty)

    _render_research(view)
    _render_watchlist(view)
    _render_discoveries(view)
    _render_all_candidates(candidates)
    _render_advanced_tools()
