from __future__ import annotations

from typing import Literal, Optional

StatusTone = Literal["success", "warning", "danger", "info", "neutral"]

# Semantic colors (shared with chart theme)
COLOR_PRIMARY = "#1a365d"
COLOR_ACCENT = "#2b6cb0"
COLOR_POSITIVE = "#1b7f3a"
COLOR_NEGATIVE = "#b42318"
COLOR_WARNING = "#b86e00"
COLOR_NEUTRAL = "#667085"
COLOR_MUTED = "#98a2b3"

NABI_GLOBAL_CSS = """
<style>
    .nabi-hero {
        background: linear-gradient(135deg, #f8fafc 0%, #eef2f7 100%);
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 1.25rem 1.5rem;
        margin-bottom: 1rem;
    }
    .nabi-hero-primary {
        font-size: 2.75rem;
        font-weight: 700;
        color: #1a365d;
        line-height: 1.1;
        margin: 0;
        letter-spacing: -0.02em;
    }
    .nabi-hero-label {
        font-size: 0.75rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: #64748b;
        margin: 0 0 0.25rem 0;
    }
    .nabi-hero-delta {
        font-size: 1rem;
        font-weight: 600;
        margin-top: 0.35rem;
    }
    .nabi-kpi-strip {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
        gap: 0.75rem;
        margin: 0.75rem 0 1rem 0;
    }
    .nabi-kpi-cell {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 0.65rem 0.85rem;
    }
    .nabi-kpi-cell-label {
        font-size: 0.72rem;
        color: #64748b;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        margin-bottom: 0.15rem;
    }
    .nabi-kpi-cell-value {
        font-size: 1.05rem;
        font-weight: 600;
        color: #1e293b;
    }
    .nabi-hero-sub {
        font-size: 0.875rem;
        color: #64748b;
        margin-top: 0.25rem;
    }
    .nabi-kpi-secondary {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 0.75rem 1rem;
    }
    .nabi-insight {
        background: #f1f5f9;
        border-left: 3px solid #2b6cb0;
        padding: 0.5rem 0.75rem;
        margin: 0.25rem 0;
        font-size: 0.875rem;
        color: #334155;
    }
    .nabi-section-desc {
        color: #64748b;
        font-size: 0.875rem;
        margin-bottom: 0.75rem;
    }
    .nabi-partial-marker {
        color: #b86e00;
        font-weight: 600;
    }
    div[data-testid="stMetric"] {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 0.5rem 0.75rem;
    }
</style>
"""


def _st():
    import streamlit

    return streamlit


def inject_nabi_theme() -> None:
    _st().markdown(NABI_GLOBAL_CSS, unsafe_allow_html=True)


def render_page_header(title: str, *, caption: Optional[str] = None) -> None:
    st = _st()
    st.title(title)
    if caption:
        st.caption(caption)


def render_section_title(title: str, *, description: Optional[str] = None) -> None:
    st = _st()
    st.markdown(f"### {title}")
    if description:
        st.markdown(f'<p class="nabi-section-desc">{description}</p>', unsafe_allow_html=True)


def render_kpi_row(items: list[tuple[str, str, Optional[str]]]) -> None:
    st = _st()
    count = len(items)
    cols = st.columns(min(count, 4) if count > 4 else count)
    for col, (label, value, help_text) in zip(cols, items[:4]):
        col.metric(label, value, help=help_text)
    if count > 4:
        cols2 = st.columns(count - 4)
        for col, (label, value, help_text) in zip(cols2, items[4:]):
            col.metric(label, value, help=help_text)


def render_executive_hero(
    *,
    primary_label: str,
    primary_value: str,
    subtitle: Optional[str] = None,
    partial: bool = False,
    partial_note: Optional[str] = None,
    delta_lines: Optional[list[tuple[str, StatusTone]]] = None,
) -> None:
    st = _st()
    inject_nabi_theme()
    suffix = "*" if partial else ""
    delta_html = ""
    if delta_lines:
        parts = []
        for text, tone in delta_lines:
            colors = {
                "success": COLOR_POSITIVE,
                "warning": COLOR_WARNING,
                "danger": COLOR_NEGATIVE,
                "info": COLOR_ACCENT,
                "neutral": COLOR_NEUTRAL,
            }
            color = colors.get(tone, COLOR_NEUTRAL)
            parts.append(f'<div class="nabi-hero-delta" style="color:{color};">{text}</div>')
        delta_html = "".join(parts)
    subtitle_html = f'<p class="nabi-hero-sub">{subtitle}</p>' if subtitle else ""
    st.html(
        f"""
        <div class="nabi-hero">
            <p class="nabi-hero-label">{primary_label}</p>
            <p class="nabi-hero-primary">{primary_value}{suffix}</p>
            {delta_html}
            {subtitle_html}
        </div>
        """
    )
    if partial_note:
        st.warning(partial_note)


def render_secondary_kpi_strip(items: list[tuple[str, str]]) -> None:
    st = _st()
    inject_nabi_theme()
    cols = st.columns(len(items))
    for col, (label, value) in zip(cols, items):
        col.markdown(f'<p class="nabi-kpi-cell-label">{label}</p>', unsafe_allow_html=True)
        col.markdown(f'<p class="nabi-kpi-cell-value">{value}</p>', unsafe_allow_html=True)


def render_secondary_kpi_row(items: list[tuple[str, str, Optional[str]]]) -> None:
    render_secondary_kpi_strip([(label, value) for label, value, _ in items])


def render_delta_indicator(label: str, value: str, *, tone: StatusTone = "neutral") -> None:
    colors = {
        "success": COLOR_POSITIVE,
        "warning": COLOR_WARNING,
        "danger": COLOR_NEGATIVE,
        "info": COLOR_ACCENT,
        "neutral": COLOR_NEUTRAL,
    }
    color = colors.get(tone, COLOR_NEUTRAL)
    _st().markdown(
        f'<span style="color:{color};font-weight:600;">{label}: {value}</span>',
        unsafe_allow_html=True,
    )


def render_status_badge(label: str, tone: StatusTone = "neutral") -> str:
    colors = {
        "success": COLOR_POSITIVE,
        "warning": COLOR_WARNING,
        "danger": COLOR_NEGATIVE,
        "info": COLOR_ACCENT,
        "neutral": COLOR_NEUTRAL,
    }
    color = colors.get(tone, COLOR_NEUTRAL)
    return (
        f"<span style='background:{color}1a;color:{color};padding:2px 8px;"
        f"border-radius:999px;font-size:0.85rem;font-weight:600;'>{label}</span>"
    )


def render_data_quality_level(level: str, detail: str) -> None:
    tone_map = {
        "COMPLETE": "success",
        "PARTIAL": "warning",
        "STALE": "warning",
        "UNAVAILABLE": "danger",
    }
    tone = tone_map.get(level.upper(), "info")
    badge = render_status_badge(level, tone)
    _st().markdown(f"{badge} {detail}", unsafe_allow_html=True)


def render_insight_list(insights: list[str]) -> None:
    if not insights:
        return
    for line in insights:
        _st().caption(f"• {line}")


def render_empty_state(title: str, detail: str, *, action_label: Optional[str] = None) -> None:
    st = _st()
    st.info(f"**{title}** — {detail}")
    if action_label:
        st.caption(f"Önerilen adım: {action_label}")


def render_limitation_state(title: str, detail: str) -> None:
    _st().warning(f"**{title}** — {detail}")


def render_data_quality_banner(*, issues: list[str], partial: bool) -> None:
    st = _st()
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
    _st().caption(f"{label}: {value or '—'}{suffix}")


def render_chart_container(title: str, *, subtitle: Optional[str] = None) -> None:
    render_section_title(title, description=subtitle)
