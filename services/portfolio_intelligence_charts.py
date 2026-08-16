from __future__ import annotations

from typing import Sequence

import altair as alt
import pandas as pd

from services.portfolio_intelligence_enrichment_contract import EnrichedPositionRow
from services.portfolio_intelligence_contract import AllocationSlice

CHART_WIDTH = "container"


def _allocation_frame(slices: Sequence[AllocationSlice]) -> pd.DataFrame:
    if not slices:
        return pd.DataFrame(columns=["label", "weight_pct", "market_value"])
    return pd.DataFrame(
        [
            {
                "label": row.label,
                "weight_pct": float(row.weight_pct),
                "market_value": float(row.market_value),
            }
            for row in slices
        ]
    )


def build_position_allocation_chart(rows: Sequence[EnrichedPositionRow]) -> alt.Chart:
    priced = [
        row
        for row in rows
        if row.valuation.price_available and row.valuation.market_value is not None
    ]
    frame = pd.DataFrame(
        [
            {
                "symbol": row.valuation.symbol,
                "weight_pct": float(row.valuation.weight_pct or 0.0),
                "market_value": float(row.valuation.market_value or 0.0),
            }
            for row in priced
        ]
    )
    if frame.empty:
        return alt.Chart(pd.DataFrame({"label": ["Veri yok"], "weight_pct": [0.0]})).mark_bar()

    return (
        alt.Chart(frame)
        .mark_arc(innerRadius=50)
        .encode(
            theta=alt.Theta("weight_pct:Q", stack=True),
            color=alt.Color("symbol:N", title="Sembol"),
            tooltip=[
                alt.Tooltip("symbol:N", title="Sembol"),
                alt.Tooltip("weight_pct:Q", title="Ağırlık %", format=".1f"),
                alt.Tooltip("market_value:Q", title="Piyasa değeri", format=",.2f"),
            ],
        )
        .properties(width=CHART_WIDTH, height=320, title="Pozisyon dağılımı")
    )


def build_allocation_bar_chart(
    slices: Sequence[AllocationSlice],
    *,
    title: str,
) -> alt.Chart:
    frame = _allocation_frame(slices)
    if frame.empty:
        return alt.Chart(pd.DataFrame({"label": ["Veri yok"], "weight_pct": [0.0]})).mark_bar()

    return (
        alt.Chart(frame)
        .mark_bar()
        .encode(
            x=alt.X("weight_pct:Q", title="Ağırlık %"),
            y=alt.Y("label:N", sort="-x", title=None),
            tooltip=[
                alt.Tooltip("label:N", title="Kategori"),
                alt.Tooltip("weight_pct:Q", title="Ağırlık %", format=".1f"),
                alt.Tooltip("market_value:Q", title="Piyasa değeri", format=",.2f"),
            ],
        )
        .properties(width=CHART_WIDTH, height=max(220, 40 * len(frame)), title=title)
    )


def build_pl_by_position_chart(rows: Sequence[EnrichedPositionRow]) -> alt.Chart:
    priced = [
        row
        for row in rows
        if row.valuation.unrealized_pl is not None and row.valuation.price_available
    ]
    frame = pd.DataFrame(
        [
            {
                "symbol": row.valuation.symbol,
                "unrealized_pl": float(row.valuation.unrealized_pl or 0.0),
            }
            for row in priced
        ]
    )
    if frame.empty:
        return alt.Chart(pd.DataFrame({"symbol": ["—"], "unrealized_pl": [0.0]})).mark_bar()

    return (
        alt.Chart(frame)
        .mark_bar()
        .encode(
            x=alt.X("symbol:N", sort="-y", title="Sembol"),
            y=alt.Y("unrealized_pl:Q", title="Gerçekleşmemiş K/Z"),
            color=alt.condition(
                alt.datum.unrealized_pl >= 0,
                alt.value("#2ca02c"),
                alt.value("#d62728"),
            ),
            tooltip=[
                alt.Tooltip("symbol:N", title="Sembol"),
                alt.Tooltip("unrealized_pl:Q", title="K/Z", format=",.2f"),
            ],
        )
        .properties(width=CHART_WIDTH, height=320, title="Pozisyon bazında K/Z")
    )
