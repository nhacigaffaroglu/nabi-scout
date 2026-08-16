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


def build_portfolio_value_history_chart(history_points) -> alt.Chart:
    import pandas as pd

    frame = pd.DataFrame(
        [
            {
                "date": point.captured_at[:10],
                "value": float(point.priced_market_value),
                "partial": point.is_partial,
            }
            for point in history_points
        ]
    )
    if frame.empty:
        return alt.Chart(pd.DataFrame({"date": ["—"], "value": [0.0]})).mark_line()

    return (
        alt.layer(
            alt.Chart(frame)
            .mark_area(opacity=0.25, color="#1f4e79")
            .encode(
                x=alt.X("date:T", title="Tarih"),
                y=alt.Y("value:Q", title="Portföy değeri"),
            ),
            alt.Chart(frame)
            .mark_line(color="#1f4e79")
            .encode(
                x=alt.X("date:T", title="Tarih"),
                y=alt.Y("value:Q", title="Portföy değeri"),
                tooltip=[
                    alt.Tooltip("date:T", title="Tarih"),
                    alt.Tooltip("value:Q", title="Değer", format=",.2f"),
                ],
            ),
        )
        .properties(width=CHART_WIDTH, height=280, title="Portföy değeri (zaman)")
    )


def build_performance_vs_contributions_chart(
    *,
    investment_gain: Optional[float],
    net_contributions: float,
    currency: str,
) -> alt.Chart:
    import pandas as pd

    gain = float(investment_gain or 0.0)
    contrib = float(net_contributions or 0.0)
    frame = pd.DataFrame(
        [
            {"category": "Net katkı", "amount": contrib},
            {"category": "Yatırım getirisi", "amount": gain},
        ]
    )
    return (
        alt.Chart(frame)
        .mark_bar()
        .encode(
            x=alt.X("category:N", title=None),
            y=alt.Y("amount:Q", title=f"Tutar ({currency})"),
            color=alt.Color(
                "category:N",
                scale=alt.Scale(range=["#4c78a8", "#59a14f"]),
                legend=None,
            ),
            tooltip=[
                alt.Tooltip("category:N", title="Bileşen"),
                alt.Tooltip("amount:Q", title="Tutar", format=",.2f"),
            ],
        )
        .properties(width=CHART_WIDTH, height=260, title="Getiri vs katkı")
    )


def build_income_timeline_chart(timeline_points) -> alt.Chart:
    import pandas as pd

    frame = pd.DataFrame(
        [{"period": p.period_label, "amount": float(p.amount)} for p in timeline_points]
    )
    if frame.empty:
        return alt.Chart(pd.DataFrame({"period": ["—"], "amount": [0.0]})).mark_bar()
    return (
        alt.Chart(frame)
        .mark_bar(color="#76b7b2")
        .encode(
            x=alt.X("period:N", title="Dönem"),
            y=alt.Y("amount:Q", title="Temettü"),
            tooltip=[
                alt.Tooltip("period:N", title="Dönem"),
                alt.Tooltip("amount:Q", title="Tutar", format=",.2f"),
            ],
        )
        .properties(width=CHART_WIDTH, height=240, title="Gelir zaman çizelgesi")
    )
