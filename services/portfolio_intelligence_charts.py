from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Sequence

import altair as alt
import pandas as pd

from services.nabi_chart_theme import (
    CASH,
    CHART_HEIGHT_COMPACT,
    CHART_HEIGHT_DEFAULT,
    CHART_HEIGHT_HERO,
    CHART_WIDTH,
    CONTRIBUTION,
    INVESTMENT_GAIN,
    MATERIALITY_COLORS,
    NABI_ACCENT,
    NABI_PRIMARY,
    NEGATIVE,
    PARTICIPATION_COLORS,
    POSITIVE,
    WARNING,
    empty_bar_chart,
)
from services.nabi_chart_theme import _ensure_theme
from services.portfolio_intelligence_enrichment_contract import EnrichedPositionRow
from services.portfolio_intelligence_contract import AllocationSlice
from services.portfolio_construction_contract import ReferenceLimitGap, RiskBudgetDimension
from services.wealth_timeline_contract import PortfolioPerformancePeriod


PL_CHART_COLUMNS = ("symbol", "unrealized_pl", "pl_pct")
WEIGHT_CHART_COLUMNS = ("symbol", "weight_pct", "market_value", "pl")
PL_UNAVAILABLE_MESSAGE = "K/Z grafiği için güncel fiyat verisi mevcut değil."


@dataclass(frozen=True)
class HoldingsChartRow:
    symbol: str
    weight_pct: Optional[float]
    market_value: Optional[float]
    unrealized_pl: Optional[float]
    pl_pct: Optional[float]
    price_available: bool


def _holding_get(row: Any, name: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(name, default)
    return getattr(row, name, default)


def _optional_number(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _holding_from_valuation(val: Any) -> HoldingsChartRow:
    pl = _optional_number(_holding_get(val, "unrealized_pl"))
    cost_basis = _optional_number(_holding_get(val, "cost_basis"))
    pl_pct = (pl / cost_basis) * 100.0 if pl is not None and cost_basis else None
    return HoldingsChartRow(
        symbol=str(_holding_get(val, "symbol") or ""),
        weight_pct=_optional_number(_holding_get(val, "weight_pct")),
        market_value=_optional_number(_holding_get(val, "market_value")),
        unrealized_pl=pl,
        pl_pct=pl_pct,
        price_available=bool(_holding_get(val, "price_available", False)),
    )


def normalize_enriched_holdings(rows) -> list[HoldingsChartRow]:
    normalized: list[HoldingsChartRow] = []
    for row in rows:
        if isinstance(row, HoldingsChartRow):
            normalized.append(row)
            continue
        val = _holding_get(row, "valuation", None)
        normalized.append(_holding_from_valuation(val if val is not None else row))
    return normalized


def normalize_valuation_holdings(rows) -> list[HoldingsChartRow]:
    return [
        row if isinstance(row, HoldingsChartRow) else _holding_from_valuation(row)
        for row in rows
    ]


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
    return build_holdings_weight_chart(normalize_enriched_holdings(rows))


def build_holdings_weight_chart(holdings: Sequence[HoldingsChartRow]) -> alt.Chart:
    _ensure_theme()
    records = []
    for row in holdings:
        price_available = bool(_holding_get(row, "price_available", False))
        market_value = _optional_number(_holding_get(row, "market_value"))
        if not price_available or market_value is None:
            continue
        records.append(
            {
                "symbol": str(_holding_get(row, "symbol") or ""),
                "weight_pct": float(_optional_number(_holding_get(row, "weight_pct")) or 0.0),
                "market_value": market_value,
                "pl": _optional_number(_holding_get(row, "unrealized_pl")),
            }
        )
    frame = pd.DataFrame(records, columns=list(WEIGHT_CHART_COLUMNS))
    if frame.empty:
        return empty_bar_chart("Fiyatlı pozisyon yok — ağırlık grafiği çizilemedi")
    frame = frame.sort_values("weight_pct", ascending=True)

    display = frame.tail(12)
    return (
        alt.Chart(display)
        .mark_bar(cornerRadiusTopRight=3)
        .encode(
            y=alt.Y("symbol:N", title=None, sort="-x"),
            x=alt.X("weight_pct:Q", title="Portföy ağırlığı %"),
            color=alt.value(NABI_PRIMARY),
            tooltip=[
                alt.Tooltip("symbol:N", title="Sembol"),
                alt.Tooltip("weight_pct:Q", title="Ağırlık %", format=".1f"),
                alt.Tooltip("market_value:Q", title="Değer", format=",.0f"),
                alt.Tooltip("pl:Q", title="K/Z", format=",.2f"),
            ],
        )
        .properties(
            width=CHART_WIDTH,
            height=max(260, 32 * len(display)),
            title="Pozisyon büyüklüğü / ağırlık",
        )
    )


def build_pl_by_position_chart(rows: Sequence[EnrichedPositionRow]) -> alt.Chart:
    return build_holdings_pl_chart(normalize_enriched_holdings(rows))


def build_holdings_pl_chart(holdings: Sequence[HoldingsChartRow]) -> alt.Chart:
    _ensure_theme()
    records = []
    excluded = 0
    for row in holdings:
        pl = _optional_number(_holding_get(row, "unrealized_pl"))
        if pl is None:
            excluded += 1
            continue
        records.append(
            {
                "symbol": str(_holding_get(row, "symbol") or ""),
                "unrealized_pl": pl,
                "pl_pct": _optional_number(_holding_get(row, "pl_pct")),
            }
        )
    frame = pd.DataFrame(records, columns=list(PL_CHART_COLUMNS))
    if frame.empty:
        return empty_bar_chart(PL_UNAVAILABLE_MESSAGE)

    display = frame.sort_values("unrealized_pl", ascending=True).tail(12)
    max_abs = max(abs(display["unrealized_pl"].max()), abs(display["unrealized_pl"].min()), 1.0)
    title = "Pozisyon K/Z (sıfır merkezli)"
    if excluded > 0:
        title = f"{title} · {excluded} fiyatsız hariç"
    return (
        alt.Chart(display)
        .mark_bar(cornerRadiusTopRight=3)
        .encode(
            y=alt.Y("symbol:N", title=None),
            x=alt.X(
                "unrealized_pl:Q",
                title="Gerçekleşmemiş K/Z",
                scale=alt.Scale(domain=[-max_abs * 1.1, max_abs * 1.1]),
            ),
            color=alt.condition(
                alt.datum.unrealized_pl >= 0,
                alt.value(POSITIVE),
                alt.value(NEGATIVE),
            ),
            tooltip=[
                alt.Tooltip("symbol:N", title="Sembol"),
                alt.Tooltip("unrealized_pl:Q", title="K/Z", format=",.2f"),
                alt.Tooltip("pl_pct:Q", title="K/Z %", format=".1f"),
            ],
        )
        .properties(
            width=CHART_WIDTH,
            height=max(260, 32 * len(display)),
            title=title,
        )
    )


def count_unpriced_holdings(holdings: Sequence[HoldingsChartRow]) -> int:
    return sum(1 for row in holdings if not row.price_available)


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
            height=CHART_HEIGHT_HERO,
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


def build_top_concentration_chart(
    *,
    top1_pct: Optional[float],
    top3_pct: Optional[float],
    top5_pct: Optional[float],
    top1_limit: Optional[float] = None,
    top3_limit: Optional[float] = None,
) -> alt.Chart:
    _ensure_theme()
    rows = []
    if top1_pct is not None:
        rows.append(
            {"bucket": "Top-1", "current": float(top1_pct), "limit": float(top1_limit or 100.0)}
        )
    if top3_pct is not None:
        rows.append(
            {"bucket": "Top-3", "current": float(top3_pct), "limit": float(top3_limit or 100.0)}
        )
    if top5_pct is not None:
        rows.append({"bucket": "Top-5", "current": float(top5_pct), "limit": 100.0})
    if not rows:
        return empty_bar_chart("Yoğunlaşma verisi yok")
    frame = pd.DataFrame(rows)
    bars = (
        alt.Chart(frame)
        .mark_bar(color=NABI_ACCENT, cornerRadiusTopRight=3)
        .encode(
            x=alt.X("current:Q", title="Ağırlık %"),
            y=alt.Y("bucket:N", sort=["Top-1", "Top-3", "Top-5"], title=None),
            tooltip=[
                alt.Tooltip("bucket:N", title="Kova"),
                alt.Tooltip("current:Q", title="Mevcut %", format=".1f"),
                alt.Tooltip("limit:Q", title="Limit %", format=".0f"),
            ],
        )
    )
    rule = (
        alt.Chart(frame)
        .mark_tick(color=NEGATIVE, thickness=3)
        .encode(x="limit:Q", y="bucket:N")
    )
    return alt.layer(bars, rule).properties(
        width=CHART_WIDTH,
        height=140,
        title="Yapısal yoğunlaşma (Top-1 / Top-3 / Top-5)",
    )


def build_coverage_status_chart(
    *,
    participation_pct: float,
    research_pct: float,
    unknown_participation_pct: float = 0.0,
    unresearched_pct: float = 0.0,
) -> alt.Chart:
    _ensure_theme()
    from services.nabi_chart_theme import NEUTRAL

    frame = pd.DataFrame(
        [
            {"dimension": "Katılım uygun", "pct": float(participation_pct), "kind": "eligible"},
            {
                "dimension": "Katılım bilinmiyor",
                "pct": float(unknown_participation_pct),
                "kind": "unknown",
            },
            {"dimension": "Araştırma kapsamı", "pct": float(research_pct), "kind": "research"},
            {"dimension": "Araştırma dışı", "pct": float(unresearched_pct), "kind": "gap"},
        ]
    )
    color_scale = alt.Scale(
        domain=["eligible", "unknown", "research", "gap"],
        range=[POSITIVE, WARNING, NABI_ACCENT, NEUTRAL],
    )
    return (
        alt.Chart(frame)
        .mark_bar(cornerRadiusTopRight=3)
        .encode(
            y=alt.Y("dimension:N", title=None),
            x=alt.X("pct:Q", title="Ağırlık %", scale=alt.Scale(domain=[0, 100])),
            color=alt.Color("kind:N", scale=color_scale, legend=None),
            tooltip=[
                alt.Tooltip("dimension:N", title="Boyut"),
                alt.Tooltip("pct:Q", title="%", format=".1f"),
            ],
        )
        .properties(width=CHART_WIDTH, height=CHART_HEIGHT_COMPACT, title="Katılım / araştırma kapsamı")
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
