from __future__ import annotations

from typing import Optional, Sequence

import altair as alt
import pandas as pd

from services.nabi_chart_theme import (
    CASH,
    CHART_HEIGHT_COMPACT,
    CHART_HEIGHT_DEFAULT,
    CHART_WIDTH,
    CONTRIBUTION,
    INVESTMENT_GAIN,
    MATERIALITY_COLORS,
    NABI_ACCENT,
    NABI_PRIMARY,
    NEGATIVE,
    PARTICIPATION_COLORS,
    POSITIVE,
    empty_bar_chart,
)
from services.nabi_chart_theme import _ensure_theme
from services.portfolio_intelligence_enrichment_contract import EnrichedPositionRow
from services.portfolio_intelligence_contract import AllocationSlice
from services.portfolio_construction_contract import ReferenceLimitGap, RiskBudgetDimension
from services.wealth_timeline_contract import PortfolioPerformancePeriod


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
    _ensure_theme()
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
        return empty_bar_chart("Fiyatlı pozisyon yok")

    top = frame.sort_values("weight_pct", ascending=False).head(8)
    other_weight = frame["weight_pct"].sum() - top["weight_pct"].sum()
    if other_weight > 0.5:
        top = pd.concat(
            [top, pd.DataFrame([{"symbol": "Diğer", "weight_pct": other_weight, "market_value": 0.0}])],
            ignore_index=True,
        )

    return (
        alt.Chart(top)
        .mark_arc(innerRadius=55, outerRadius=100)
        .encode(
            theta=alt.Theta("weight_pct:Q", stack=True),
            color=alt.Color("symbol:N", title="Sembol", scale=alt.Scale(scheme="blues")),
            tooltip=[
                alt.Tooltip("symbol:N", title="Sembol"),
                alt.Tooltip("weight_pct:Q", title="Ağırlık %", format=".1f"),
                alt.Tooltip("market_value:Q", title="Değer", format=",.0f"),
            ],
        )
        .properties(width=CHART_WIDTH, height=CHART_HEIGHT_DEFAULT, title="Pozisyon dağılımı")
    )


def build_allocation_bar_chart(
    slices: Sequence[AllocationSlice],
    *,
    title: str,
    color_field: Optional[str] = None,
) -> alt.Chart:
    _ensure_theme()
    frame = _allocation_frame(slices)
    if frame.empty:
        return empty_bar_chart("Veri yok")

    color_enc = alt.Color("label:N", legend=None)
    if color_field == "participation":
        color_enc = alt.Color(
            "label:N",
            scale=alt.Scale(
                domain=list(PARTICIPATION_COLORS.keys()),
                range=list(PARTICIPATION_COLORS.values()),
            ),
            legend=None,
        )

    return (
        alt.Chart(frame.sort_values("weight_pct", ascending=True))
        .mark_bar(cornerRadiusTopRight=3)
        .encode(
            x=alt.X("weight_pct:Q", title="Ağırlık %", axis=alt.Axis(format=".1f")),
            y=alt.Y("label:N", sort="-x", title=None),
            color=color_enc,
            tooltip=[
                alt.Tooltip("label:N", title="Kategori"),
                alt.Tooltip("weight_pct:Q", title="Ağırlık %", format=".1f"),
                alt.Tooltip("market_value:Q", title="Değer", format=",.0f"),
            ],
        )
        .properties(width=CHART_WIDTH, height=max(CHART_HEIGHT_COMPACT, 36 * len(frame)), title=title)
    )


def build_position_weight_chart(rows: Sequence[EnrichedPositionRow]) -> alt.Chart:
    _ensure_theme()
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
                "pl": float(row.valuation.unrealized_pl or 0.0),
            }
            for row in priced
        ]
    ).sort_values("weight_pct", ascending=True)
    if frame.empty:
        return empty_bar_chart("Fiyatlı pozisyon yok")

    return (
        alt.Chart(frame)
        .mark_bar(cornerRadiusTopRight=3)
        .encode(
            y=alt.Y("symbol:N", title=None),
            x=alt.X("weight_pct:Q", title="Portföy ağırlığı %"),
            color=alt.condition(
                alt.datum.pl >= 0,
                alt.value(POSITIVE),
                alt.value(NEGATIVE),
            ),
            tooltip=[
                alt.Tooltip("symbol:N", title="Sembol"),
                alt.Tooltip("weight_pct:Q", title="Ağırlık %", format=".1f"),
                alt.Tooltip("market_value:Q", title="Değer", format=",.0f"),
                alt.Tooltip("pl:Q", title="K/Z", format=",.2f"),
            ],
        )
        .properties(width=CHART_WIDTH, height=max(240, 28 * len(frame.head(12))), title="Pozisyon ağırlığı")
    )


def build_pl_by_position_chart(rows: Sequence[EnrichedPositionRow]) -> alt.Chart:
    _ensure_theme()
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
    ).sort_values("unrealized_pl", ascending=True)
    if frame.empty:
        return empty_bar_chart("K/Z verisi yok")

    return (
        alt.Chart(frame)
        .mark_bar(cornerRadiusTopRight=3)
        .encode(
            y=alt.Y("symbol:N", title=None),
            x=alt.X("unrealized_pl:Q", title="Gerçekleşmemiş K/Z"),
            color=alt.condition(
                alt.datum.unrealized_pl >= 0,
                alt.value(POSITIVE),
                alt.value(NEGATIVE),
            ),
            tooltip=[
                alt.Tooltip("symbol:N", title="Sembol"),
                alt.Tooltip("unrealized_pl:Q", title="K/Z", format=",.2f"),
            ],
        )
        .properties(width=CHART_WIDTH, height=max(240, 28 * len(frame.head(12))), title="Pozisyon K/Z katkısı")
    )


def build_portfolio_value_history_chart(
    history_points,
    *,
    net_contributions: Optional[float] = None,
    currency: str = "USD",
) -> alt.Chart:
    _ensure_theme()
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
        return empty_bar_chart("Yeterli tarihsel snapshot bulunmuyor")

    line = (
        alt.Chart(frame)
        .mark_line(color=NABI_PRIMARY, strokeWidth=2.5)
        .encode(
            x=alt.X("date:T", title="Tarih"),
            y=alt.Y("value:Q", title=f"Portföy değeri ({currency})", axis=alt.Axis(format=",.0f")),
            tooltip=[
                alt.Tooltip("date:T", title="Tarih"),
                alt.Tooltip("value:Q", title="Değer", format=",.2f"),
            ],
        )
    )
    area = (
        alt.Chart(frame)
        .mark_area(color=NABI_ACCENT, opacity=0.12)
        .encode(x="date:T", y="value:Q")
    )
    layers: list = [area, line]

    if net_contributions is not None and net_contributions > 0:
        ref = pd.DataFrame({"y": [net_contributions]})
        layers.append(
            alt.Chart(ref)
            .mark_rule(color=CONTRIBUTION, strokeDash=[6, 4], strokeWidth=1.5)
            .encode(y="y:Q")
        )

    partial_note = ""
    if any(point.is_partial for point in history_points):
        partial_note = " · Kısmi snapshot"

    return (
        alt.layer(*layers)
        .properties(
            width=CHART_WIDTH,
            height=CHART_HEIGHT_DEFAULT,
            title=f"Portföy değeri (zaman){partial_note}",
        )
    )


def build_performance_vs_contributions_chart(
    *,
    investment_gain: Optional[float],
    net_contributions: float,
    currency: str,
) -> alt.Chart:
    _ensure_theme()
    gain = float(investment_gain or 0.0)
    contrib = float(net_contributions or 0.0)
    frame = pd.DataFrame(
        [
            {"category": "Net katkı", "amount": contrib, "order": 1},
            {"category": "Yatırım getirisi", "amount": gain, "order": 2},
        ]
    )
    return (
        alt.Chart(frame)
        .mark_bar(cornerRadiusTopRight=4)
        .encode(
            x=alt.X("category:N", title=None, sort=["Net katkı", "Yatırım getirisi"]),
            y=alt.Y("amount:Q", title=f"Tutar ({currency})", axis=alt.Axis(format=",.0f")),
            color=alt.Color(
                "category:N",
                scale=alt.Scale(
                    domain=["Net katkı", "Yatırım getirisi"],
                    range=[CONTRIBUTION, INVESTMENT_GAIN if gain >= 0 else NEGATIVE],
                ),
                legend=None,
            ),
            tooltip=[
                alt.Tooltip("category:N", title="Bileşen"),
                alt.Tooltip("amount:Q", title="Tutar", format=",.2f"),
            ],
        )
        .properties(width=CHART_WIDTH, height=CHART_HEIGHT_COMPACT, title="Katkı vs yatırım getirisi")
    )


def build_performance_waterfall_chart(
    period: Optional[PortfolioPerformancePeriod],
    *,
    currency: str,
) -> alt.Chart:
    _ensure_theme()
    if period is None or not period.performance_comparable:
        return empty_bar_chart("Dönemsel köprü için karşılaştırılabilir snapshot gerekli")

    steps = [
        ("Başlangıç", period.start_priced_value, "base"),
        ("Net katkı", period.net_external_flow, "flow"),
        ("Yatırım getirisi", period.investment_gain, "gain"),
        ("Temettü", period.dividend_income, "income"),
        ("Masraf", -abs(period.fee_cost), "fee"),
        ("Bitiş", period.end_priced_value, "end"),
    ]
    frame = pd.DataFrame(
        [{"step": name, "amount": float(val), "kind": kind} for name, val, kind in steps]
    )
    color_scale = alt.Scale(
        domain=["base", "flow", "gain", "income", "fee", "end"],
        range=[NABI_PRIMARY, CONTRIBUTION, INVESTMENT_GAIN, POSITIVE, NEGATIVE, NABI_ACCENT],
    )
    return (
        alt.Chart(frame)
        .mark_bar(cornerRadiusTopRight=3)
        .encode(
            x=alt.X("step:N", title=None, sort=[s[0] for s in steps]),
            y=alt.Y("amount:Q", title=f"Tutar ({currency})", axis=alt.Axis(format=",.0f")),
            color=alt.Color("kind:N", scale=color_scale, legend=None),
            tooltip=[
                alt.Tooltip("step:N", title="Adım"),
                alt.Tooltip("amount:Q", title="Tutar", format=",.2f"),
            ],
        )
        .properties(width=CHART_WIDTH, height=CHART_HEIGHT_DEFAULT, title="Değer değişimi köprüsü")
    )


def build_concentration_limit_chart(
    *,
    current_pct: Optional[float],
    limit_pct: Optional[float],
    label: str,
) -> alt.Chart:
    _ensure_theme()
    if current_pct is None:
        return empty_bar_chart(f"{label}: veri yok")
    limit = float(limit_pct or 100.0)
    frame = pd.DataFrame([{"label": label, "current": float(current_pct), "limit": limit}])
    bars = (
        alt.Chart(frame)
        .mark_bar(color=NABI_ACCENT, cornerRadiusTopRight=3)
        .encode(
            x=alt.X("current:Q", title="Ağırlık %", scale=alt.Scale(domain=[0, max(limit * 1.2, current_pct + 5)])),
            y=alt.Y("label:N", title=None),
        )
    )
    rule = (
        alt.Chart(frame)
        .mark_rule(color=NEGATIVE, strokeDash=[4, 4])
        .encode(x="limit:Q")
    )
    return alt.layer(bars, rule).properties(
        width=CHART_WIDTH,
        height=80,
        title=f"{label} (limit: {limit:.0f}%)",
    )


def build_reference_gap_chart(gaps: Sequence[ReferenceLimitGap]) -> alt.Chart:
    _ensure_theme()
    if not gaps:
        return empty_bar_chart("Referans limit karşılaştırması yok")
    frame = pd.DataFrame(
        [
            {
                "dimension": gap.dimension,
                "current": float(gap.current_value or 0.0),
                "limit": float(gap.reference_limit or 0.0),
                "status": gap.status,
            }
            for gap in gaps
            if gap.current_value is not None
        ]
    )
    if frame.empty:
        return empty_bar_chart("Yeterli kapsam yok")

    current = (
        alt.Chart(frame)
        .mark_bar(color=NABI_ACCENT, cornerRadiusTopRight=3)
        .encode(
            x=alt.X("current:Q", title="Mevcut %"),
            y=alt.Y("dimension:N", sort="-x", title=None),
        )
    )
    limit = (
        alt.Chart(frame)
        .mark_tick(color=NEGATIVE, thickness=3)
        .encode(x="limit:Q", y="dimension:N")
    )
    return alt.layer(current, limit).properties(
        width=CHART_WIDTH,
        height=max(160, 40 * len(frame)),
        title="Referans limit karşılaştırması",
    )


def build_scenario_impact_chart(
    scenarios,
    *,
    currency: str,
) -> alt.Chart:
    _ensure_theme()
    rows = []
    for scenario in scenarios:
        if scenario.portfolio_impact_abs is None:
            continue
        rows.append(
            {
                "label": scenario.scenario_label[:40],
                "impact": float(scenario.portfolio_impact_abs),
                "impact_pct": float(scenario.portfolio_impact_pct or 0.0),
            }
        )
    if not rows:
        return empty_bar_chart("Senaryo etkisi hesaplanamadı")
    frame = pd.DataFrame(rows)
    return (
        alt.Chart(frame)
        .mark_bar(cornerRadiusTopRight=3)
        .encode(
            y=alt.Y("label:N", title=None),
            x=alt.X("impact:Q", title=f"Etki ({currency})", axis=alt.Axis(format=",.0f")),
            color=alt.condition(
                alt.datum.impact >= 0,
                alt.value(POSITIVE),
                alt.value(NEGATIVE),
            ),
            tooltip=[
                alt.Tooltip("label:N", title="Senaryo"),
                alt.Tooltip("impact:Q", title="Tutar", format=",.2f"),
                alt.Tooltip("impact_pct:Q", title="Etki %", format=".1f"),
            ],
        )
        .properties(width=CHART_WIDTH, height=max(180, 50 * len(frame)), title="Senaryo etkisi")
    )


def build_decision_timeline_chart(timeline) -> alt.Chart:
    _ensure_theme()
    if not timeline:
        return empty_bar_chart("Karar zaman çizelgesi boş")
    frame = pd.DataFrame(
        [
            {
                "date": entry.decision_date[:10],
                "symbol": entry.symbol,
                "outcome": float(entry.outcome_pct or 0.0),
                "status": entry.outcome_status or "—",
            }
            for entry in timeline[:15]
        ]
    )
    return (
        alt.Chart(frame)
        .mark_circle(size=120)
        .encode(
            x=alt.X("date:T", title="Tarih"),
            y=alt.Y("outcome:Q", title="Sonuç %"),
            color=alt.condition(
                alt.datum.outcome >= 0,
                alt.value(POSITIVE),
                alt.value(NEGATIVE),
            ),
            tooltip=[
                alt.Tooltip("symbol:N", title="Sembol"),
                alt.Tooltip("date:T", title="Tarih"),
                alt.Tooltip("outcome:Q", title="Sonuç %", format=".1f"),
                alt.Tooltip("status:N", title="Durum"),
            ],
        )
        .properties(width=CHART_WIDTH, height=CHART_HEIGHT_COMPACT, title="Karar sonuçları")
    )


def build_monitor_materiality_chart(events) -> alt.Chart:
    _ensure_theme()
    if not events:
        return empty_bar_chart("Olay yok")
    counts: dict[str, int] = {}
    for event in events:
        key = event.materiality or "info"
        counts[key] = counts.get(key, 0) + 1
    frame = pd.DataFrame([{"materiality": k, "count": v} for k, v in counts.items()])
    return (
        alt.Chart(frame)
        .mark_bar(cornerRadiusTopRight=3)
        .encode(
            x=alt.X("count:Q", title="Olay sayısı"),
            y=alt.Y("materiality:N", sort=["critical", "high", "medium", "low", "info"], title=None),
            color=alt.Color(
                "materiality:N",
                scale=alt.Scale(
                    domain=list(MATERIALITY_COLORS.keys()),
                    range=list(MATERIALITY_COLORS.values()),
                ),
                legend=None,
            ),
        )
        .properties(width=CHART_WIDTH, height=CHART_HEIGHT_COMPACT, title="Olay önem dağılımı")
    )


def build_income_timeline_chart(timeline_points) -> alt.Chart:
    _ensure_theme()
    frame = pd.DataFrame(
        [{"period": p.period_label, "amount": float(p.amount)} for p in timeline_points]
    )
    if frame.empty:
        return empty_bar_chart("Gelir verisi yok")
    return (
        alt.Chart(frame)
        .mark_bar(color=CASH, cornerRadiusTopRight=3)
        .encode(
            x=alt.X("period:N", title="Dönem"),
            y=alt.Y("amount:Q", title="Temettü", axis=alt.Axis(format=",.0f")),
            tooltip=[
                alt.Tooltip("period:N", title="Dönem"),
                alt.Tooltip("amount:Q", title="Tutar", format=",.2f"),
            ],
        )
        .properties(width=CHART_WIDTH, height=CHART_HEIGHT_COMPACT, title="Gelir zaman çizelgesi")
    )


def build_risk_budget_chart(dimensions: Sequence[RiskBudgetDimension]) -> alt.Chart:
    _ensure_theme()
    rows = [
        {
            "dimension": row.dimension,
            "current": float(row.current_value or 0.0),
            "threshold": float(row.threshold or 0.0),
        }
        for row in dimensions
        if row.current_value is not None
    ]
    if not rows:
        return empty_bar_chart("Risk bütçesi verisi yok")
    frame = pd.DataFrame(rows)
    current = (
        alt.Chart(frame)
        .mark_bar(color=NABI_ACCENT, cornerRadiusTopRight=3)
        .encode(x=alt.X("current:Q", title="Mevcut %"), y=alt.Y("dimension:N", title=None))
    )
    threshold = (
        alt.Chart(frame)
        .mark_tick(color=WARNING, thickness=3)
        .encode(x="threshold:Q", y="dimension:N")
    )
    return alt.layer(current, threshold).properties(
        width=CHART_WIDTH,
        height=max(140, 36 * len(frame)),
        title="Yapısal risk bütçesi",
    )
