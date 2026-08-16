from __future__ import annotations

from typing import Literal, Optional

import streamlit as st

StatusTone = Literal["success", "warning", "danger", "info", "neutral"]


def render_page_header(title: str, *, caption: Optional[str] = None) -> None:
    st.title(title)
    if caption:
        st.caption(caption)


def render_section_title(title: str) -> None:
    st.markdown(f"### {title}")


def render_kpi_row(items: list[tuple[str, str, Optional[str]]]) -> None:
    cols = st.columns(len(items))
    for col, (label, value, help_text) in zip(cols, items):
        col.metric(label, value, help=help_text)


def render_status_badge(label: str, tone: StatusTone = "neutral") -> str:
    colors = {
        "success": "#1b7f3a",
        "warning": "#b86e00",
        "danger": "#b42318",
        "info": "#175cd3",
        "neutral": "#667085",
    }
    color = colors.get(tone, colors["neutral"])
    return (
        f"<span style='background:{color}1a;color:{color};padding:2px 8px;"
        f"border-radius:999px;font-size:0.85rem;font-weight:600;'>{label}</span>"
    )


def render_empty_state(title: str, detail: str, *, action_label: Optional[str] = None) -> None:
    st.info(f"**{title}** — {detail}")
    if action_label:
        st.caption(f"Önerilen adım: {action_label}")


def render_data_quality_banner(*, issues: list[str], partial: bool) -> None:
    if not issues:
        st.success("Veri kalitesi: güncel persisted veriler kullanılıyor.")
        return
    message = " · ".join(issues[:4])
    if partial:
        st.warning(f"Kısmi veri kapsamı: {message}")
    else:
        st.info(f"Veri notu: {message}")


def render_freshness_line(label: str, value: Optional[str], *, stale: bool = False) -> None:
    suffix = " (eski)" if stale else ""
    st.caption(f"{label}: {value or '—'}{suffix}")
