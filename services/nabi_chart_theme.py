from __future__ import annotations

from typing import Optional

import altair as alt

CHART_WIDTH = "container"
CHART_HEIGHT_DEFAULT = 280
CHART_HEIGHT_COMPACT = 220

# Semantic palette — consistent meaning across all charts
NABI_PRIMARY = "#1a365d"
NABI_ACCENT = "#2b6cb0"
POSITIVE = "#1b7f3a"
NEGATIVE = "#b42318"
WARNING = "#b86e00"
NEUTRAL = "#667085"
MUTED = "#98a2b3"
PARTICIPATION_ELIGIBLE = "#1b7f3a"
PARTICIPATION_REVIEW = "#b86e00"
PARTICIPATION_INELIGIBLE = "#b42318"
PARTICIPATION_UNKNOWN = "#667085"
RESEARCH_COVERED = "#175cd3"
RESEARCH_LIMITED = "#b86e00"
MISSING = "#d0d5dd"
CONTRIBUTION = "#4c78a8"
INVESTMENT_GAIN = "#59a14f"
CASH = "#76b7b2"

PARTICIPATION_COLORS = {
    "Uygun": PARTICIPATION_ELIGIBLE,
    "Kontrol Et": PARTICIPATION_REVIEW,
    "Uygun Değil": PARTICIPATION_INELIGIBLE,
    "Bilinmiyor": PARTICIPATION_UNKNOWN,
}

MATERIALITY_COLORS = {
    "critical": NEGATIVE,
    "high": WARNING,
    "medium": NABI_ACCENT,
    "low": NEUTRAL,
    "info": MUTED,
}


def configure_altair_theme() -> None:
    alt.data_transformers.disable_max_rows()


_THEME_READY = False


def _ensure_theme() -> None:
    global _THEME_READY
    if not _THEME_READY:
        configure_altair_theme()
        _THEME_READY = True


def chart_title(title: str, *, subtitle: Optional[str] = None) -> dict:
    props: dict = {"title": title}
    if subtitle:
        props["title"] = {"text": [title, subtitle], "subtitle": subtitle, "fontSize": 14}
    return props


def empty_bar_chart(message: str = "Veri yok") -> alt.Chart:
    import pandas as pd

    return (
        alt.Chart(pd.DataFrame({"label": [message], "value": [0.0]}))
        .mark_bar(color=MUTED)
        .encode(x="value:Q", y="label:N")
        .properties(width=CHART_WIDTH, height=120)
    )


def format_currency_axis(title: str, currency: str) -> alt.X:
    return alt.X(f"{title}:Q", title=f"{title} ({currency})", axis=alt.Axis(format=",.0f"))


def format_pct_axis(title: str = "Ağırlık %") -> alt.X:
    return alt.X("weight_pct:Q", title=title, axis=alt.Axis(format=".1f"))
