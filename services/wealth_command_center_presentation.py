"""Wealth Command Center composition. No new valuation or return math."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence, Tuple

from components.portfolio_decision_center_ui import (
    CONTRIBUTION_PLAN_TITLE,
    HEALTHY_MESSAGE,
    present_action_center,
)
from services.canonical_current_valuation import canonical_total_wealth_usd
from services.fx_rate_service import FxRateService
from services.nabi_dashboard_presentation import (
    MAX_DASHBOARD_ACTIONS,
    DashboardActionItem,
    DashboardPrioritySection,
    format_usd_display,
    present_priority_section,
)
from services.portfolio_cockpit_presentation import (
    COST_MISSING_COPY,
    CockpitAllocationSlice,
    GainLossRow,
    HoldingWeightRow,
    HoldingsTableRow,
    PortfolioCockpitView,
    allocation_sums_to_total,
    build_portfolio_cockpit,
)
from services.portfolio_decision_intelligence import CONCENTRATION_REVIEW_THRESHOLD_PCT
from services.portfolio_intelligence_contract import PortfolioIntelligenceView
from services.wealth_goal_center_presentation import GoalCenterDashboard
from datetime import datetime, timezone

from services.wealth_history_service import (
    WealthHistoryPoint,
    WealthHistoryState,
    _snapshot_complete,
)
from services.wealth_performance_center_presentation import (
    PERIOD_OPTIONS,
    PerformanceCenterView,
    PerformancePeriod,
    build_performance_center,
    select_period_snapshots,
)

COMMAND_TITLE = "NABI Wealth"
HERO_LABEL = "TOPLAM SERVET"
GAIN_KPI_LABEL = "GERÇEKLEŞMEMİŞ K/Z"
GAIN_KPI_CAPTION = "Mevcut piyasa değeri ile kayıtlı maliyet arasındaki fark."
PRIORITY_TITLE = "NABI — BUGÜNKÜ ÖNCELİK"
COMMENTARY_TITLE = "NABI — PORTFÖY YORUMU"
SYNTHESIS_PREFIX = "NABI görüşü:"
ALLOCATION_TITLE = "PORTFÖYÜM NEREDE?"
TREEMAP_TITLE = "PORTFÖY HARİTASI"
WINNERS_TITLE = "KAZANANLAR"
LOSERS_TITLE = "KAYBEDENLER"
UNREALIZED_NOTE = "Alış maliyetine göre gerçekleşmemiş K/Z"
HISTORY_TITLE = "SERVET GELİŞİMİ"
CONTRIBUTION_NOT_RETURN = "Katkılar yatırım getirisi değildir."
INCOMPARABLE_HISTORY = "Karşılaştırılabilir geçmiş henüz oluşmadı."
ONE_POINT_HISTORY = "Karşılaştırılabilir servet geçmişi yeni oluşmaya başladı."
INCOMPARABLE_SCOPE = "Karşılaştırılamaz değerleme kapsamı"
HISTORY_DETAIL_TITLE = "Geçmiş değerleme detayları"
TECHNICAL_HISTORY_TITLE = "Teknik geçmiş / Eski değerleme kapsamı"
COST_EXCLUDED_COPY = "Maliyet verisi bulunmayan ürünler K/Z sıralamasına dahil edilmedi."
TREEMAP_SIZE_LEGEND = "Boyut = portföy ağırlığı"
TREEMAP_COLOR_LEGEND = "Renk = gerçekleşmemiş K/Z"
TREEMAP_COLOR_LIMIT = "Renk yalnızca maliyet verisi geçerli olan pozisyonlar için."
JOURNEY_TITLE = "2031 YOLCULUĞU"
REQUIRED_MONTHLY_CAPTION = "2031 için gerekli aylık katkı"
CURRENT_MONTHLY_CAPTION = "Mevcut katkı"
REACH_YEAR_CAPTION = "Mevcut planla tahmini ulaşma"
MONTHLY_UNIT = "/ ay"
TOP_HOLDINGS_TITLE = "EN BÜYÜK POZİSYONLAR"
DETAILS_TITLE = "Detaylar"
FULL_HOLDINGS_LABEL = "Tümünü göster"
OTHER_HOLDINGS_TEMPLATE = "Diğer pozisyonlar: {count} · toplam %{weight:.1f}"
PRIORITY_OVERFLOW_TEMPLATE = "+{count} diğer konu"
CONCENTRATION_TITLE = "Yoğunlaşmayı gözden geçir"
NO_CONCENTRATION_COPY = "Portföyde kritik tekil pozisyon yoğunlaşması görünmüyor."
CONCENTRATION_FLAG_COPY = "yoğunlaşma inceleme eşiğine ulaştı"
PLAN_GAP_INSIGHT = (
    "Portföy yapısından daha belirgin stratejik açık, 2031 hedefi için katkı hızında."
)
SYNTHESIS_PLAN_GAP = (
    "Portföy yapısı mevcut yoğunlaşma kuralları açısından dengeli; "
    "ana iyileştirme alanı katkı planı."
)
MAX_TOP_HOLDINGS = 5
MAX_PRIORITY = MAX_DASHBOARD_ACTIONS
PRIMARY_PRIORITY_LIMIT = 1
MAX_COMMENTARY_INSIGHTS = 4
MAX_COMMENTARY_CHIPS = 3
PERIOD_CHIP_LABELS = {
    PerformancePeriod.DAILY: "1D",
    PerformancePeriod.WEEKLY: "1W",
    PerformancePeriod.MONTHLY: "1M",
    PerformancePeriod.YEARLY: "1Y",
    PerformancePeriod.ALL: "ALL",
}
COMPACT_ACTION_LABELS = {
    "A) Aylık katkıyı artır": "Katkıyı artır",
    "B) Hedef tarihini uzat": "Hedef tarihini uzat",
    "C) Senaryo karşılaştır": "Senaryo karşılaştır",
}
CURVE_MODE_CHART = "curve"
CURVE_MODE_ONE_POINT = "one_point"
CURVE_MODE_EMPTY = "empty"
_HISTORY_MONTHS_TR = {
    1: "Ocak",
    2: "Şubat",
    3: "Mart",
    4: "Nisan",
    5: "Mayıs",
    6: "Haziran",
    7: "Temmuz",
    8: "Ağustos",
    9: "Eylül",
    10: "Ekim",
    11: "Kasım",
    12: "Aralık",
}


@dataclass(frozen=True)
class TreemapCell:
    symbol: str
    market_value: float
    weight_pct: float
    asset_class: str
    unrealized_pl: Optional[float]
    cost_missing: bool


@dataclass(frozen=True)
class JourneyView:
    current_label: str
    projected_label: str
    target_label: str
    progress_label: str
    attainment_label: str
    configured_monthly_label: str
    required_monthly_label: str
    earliest_label: Optional[str]
    interpretation: str
    progress_pct: Optional[float] = None
    attainment_pct: Optional[float] = None
    current_amount: Optional[float] = None
    projected_amount: Optional[float] = None
    target_amount: Optional[float] = None
    summary_line: str = ""


@dataclass(frozen=True)
class FirstViewportKpis:
    wealth_usd: str
    wealth_try: Optional[str]
    gain_usd: Optional[str]
    gain_pct: Optional[str]
    progress_compact: str
    largest_symbol: Optional[str]
    largest_weight: Optional[str]
    valuation_chip: str


@dataclass(frozen=True)
class PriorityFocus:
    primary: Optional[DashboardActionItem]
    overflow_count: int
    overflow_items: Tuple[DashboardActionItem, ...]
    current_metric: Optional[str] = None
    required_metric: Optional[str] = None
    action_labels: Tuple[str, ...] = ()


@dataclass(frozen=True)
class PortfolioCommentary:
    insights: Tuple[str, ...]
    synthesis: Optional[str]
    chips: Tuple[str, ...] = ()


@dataclass(frozen=True)
class WealthCurvePresentation:
    mode: str
    comparable_points: Tuple[WealthHistoryPoint, ...]
    technical_points: Tuple[WealthHistoryPoint, ...]
    latest_complete: Optional[WealthHistoryPoint]
    compact_copy: Optional[str]
    show_chart: bool
    all_points: Tuple[WealthHistoryPoint, ...] = ()


@dataclass(frozen=True)
class PerformanceStrip:
    comparable: bool
    period_return: Optional[str]
    investment_gain: Optional[str]
    net_contribution: Optional[str]
    best_product: Optional[str]
    weakest_product: Optional[str]
    limitation: Optional[str]


@dataclass(frozen=True)
class WealthCommandCenterView:
    title: str
    cockpit: PortfolioCockpitView
    usd_total: float
    priority: DashboardPrioritySection
    journey: JourneyView
    treemap: Tuple[TreemapCell, ...]
    top_holdings: Tuple[HoldingWeightRow, ...]
    winners: Tuple[GainLossRow, ...]
    losers: Tuple[GainLossRow, ...]
    gain_available: bool
    gain_limitation: Optional[str]
    performance: Optional[PerformanceCenterView]
    excluded_cost_count: int
    viewport: FirstViewportKpis
    priority_focus: PriorityFocus
    supported_periods: Tuple[PerformancePeriod, ...]
    performance_strip: PerformanceStrip
    other_holdings_count: int
    other_holdings_weight: float
    commentary: PortfolioCommentary
    history_curve: WealthCurvePresentation
    show_period_controls: bool


def _select_performance(
    snapshots: Sequence[Any],
    *,
    transactions: Sequence[Any] = (),
    account_ids: Sequence[str] = (),
    portfolio_id: str = "",
    fallback: Optional[PerformanceCenterView] = None,
) -> Optional[PerformanceCenterView]:
    if not snapshots:
        return fallback
    kwargs = {
        "transactions": transactions,
        "account_ids": account_ids,
        "portfolio_id": portfolio_id or None,
    }
    monthly = build_performance_center(snapshots, period=PerformancePeriod.MONTHLY, **kwargs)
    if monthly.sufficient:
        return monthly
    entire = build_performance_center(snapshots, period=PerformancePeriod.ALL, **kwargs)
    if entire.sufficient:
        return entire
    return monthly if monthly.history is not None else (entire if entire.history is not None else fallback)


def _journey(dashboard: GoalCenterDashboard) -> JourneyView:
    alt = dashboard.target_date_alternative
    earliest = None
    if alt.available and alt.reach_year:
        earliest = str(alt.reach_year)
    elif alt.reach_date_label:
        earliest = alt.reach_date_label
    baseline = dashboard.baseline
    current_amount = float(dashboard.snapshot.current_value_lower_bound)
    projected_amount = (
        float(baseline.projected_wealth) if baseline.projected_wealth is not None else None
    )
    target_amount = float(dashboard.goal.target_amount)
    progress_pct = float(dashboard.header.progress_pct)
    attainment_pct = (
        float(baseline.attainment_pct) if baseline.attainment_pct is not None else None
    )
    return JourneyView(
        current_label=dashboard.header.current_wealth_label,
        projected_label=dashboard.current_plan.projected_wealth_label,
        target_label=dashboard.header.target_wealth_label,
        progress_label=dashboard.header.progress_caption,
        attainment_label=dashboard.current_plan.attainment_label,
        configured_monthly_label=_with_monthly_unit(
            dashboard.current_plan.starting_monthly_label
        ),
        required_monthly_label=_with_monthly_unit(dashboard.required.required_label),
        earliest_label=earliest,
        interpretation=dashboard.nabi.copy,
        progress_pct=progress_pct,
        attainment_pct=attainment_pct,
        current_amount=current_amount,
        projected_amount=projected_amount,
        target_amount=target_amount,
        summary_line=(
            f"Mevcut planla tahmini ulaşma yılı {earliest}." if earliest else ""
        ),
    )


def _treemap(view: PortfolioIntelligenceView, cockpit: PortfolioCockpitView) -> Tuple[TreemapCell, ...]:
    missing = {row.symbol for row in cockpit.holdings_table if row.cost_missing}
    cells = []
    for row in view.priced_positions:
        if row.market_value in (None, 0, 0.0):
            continue
        cost_missing = row.symbol in missing
        cells.append(
            TreemapCell(
                symbol=row.symbol,
                market_value=float(row.market_value),
                weight_pct=float(row.weight_pct or 0.0),
                asset_class=str(row.asset_class or "—"),
                unrealized_pl=None if cost_missing else (
                    float(row.unrealized_pl) if row.unrealized_pl is not None else None
                ),
                cost_missing=cost_missing,
            )
        )
    return tuple(cells)


def treemap_sums_to_total(cells: Sequence[TreemapCell], total: float) -> bool:
    if not cells:
        return total == 0
    return abs(sum(row.market_value for row in cells) - total) < 0.02


def _with_monthly_unit(label: Optional[str]) -> str:
    text = str(label or "").strip()
    if not text or text == "—":
        return text or "—"
    if MONTHLY_UNIT in text:
        return text
    return f"{text} {MONTHLY_UNIT}"


def list_supported_periods(snapshots: Sequence[Any]) -> Tuple[PerformancePeriod, ...]:
    if not snapshots:
        return ()
    supported = []
    for period in PERIOD_OPTIONS:
        start, end = select_period_snapshots(snapshots, period)
        if start is not None and end is not None:
            supported.append(period)
    return tuple(supported)


def history_points_from_snapshots(snapshots: Sequence[Any]) -> Tuple[WealthHistoryPoint, ...]:
    ordered = sorted(
        snapshots,
        key=lambda row: str(getattr(row, "captured_at", "") or ""),
    )
    return tuple(
        WealthHistoryPoint(
            captured_at=str(row.captured_at),
            priced_market_value=float(row.priced_market_value),
            is_partial=not _snapshot_complete(row),
        )
        for row in ordered
    )


def list_comparable_periods(snapshots: Sequence[Any]) -> Tuple[PerformancePeriod, ...]:
    complete = [row for row in snapshots if _snapshot_complete(row)]
    if len(complete) < 2:
        return ()
    return list_supported_periods(complete)


def format_history_point_date(captured_at: str) -> str:
    text = str(captured_at or "").replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return text[:10] if text else "—"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    month = _HISTORY_MONTHS_TR.get(parsed.month, str(parsed.month))
    return f"{parsed.day} {month} {parsed.year}"


def _compact_action_label(option: str) -> str:
    return COMPACT_ACTION_LABELS.get(option, option.split(") ", 1)[-1] if ") " in option else option)


def _evidence_metric(evidence: Sequence[str], *prefixes: str) -> Optional[str]:
    for line in evidence:
        text = str(line or "")
        for prefix in prefixes:
            if text.startswith(prefix):
                return text.split(":", 1)[-1].strip()
    return None


def _priority_focus(
    priority: DashboardPrioritySection,
    journey: Optional[JourneyView] = None,
) -> PriorityFocus:
    if priority.healthy or not priority.items:
        return PriorityFocus(None, 0, ())
    primary = priority.items[0]
    overflow = priority.items[1:]
    current_metric = _evidence_metric(primary.evidence, "Mevcut aylık katkı")
    required_metric = _evidence_metric(
        primary.evidence,
        "Gerekli başlangıç aylık katkı",
        "Gerekli aylık katkı",
    )
    if journey is not None and primary.title == CONTRIBUTION_PLAN_TITLE:
        if journey.configured_monthly_label and journey.configured_monthly_label != "—":
            current_metric = journey.configured_monthly_label
        if journey.required_monthly_label and journey.required_monthly_label != "—":
            required_metric = journey.required_monthly_label
    return PriorityFocus(
        primary,
        len(overflow),
        overflow,
        current_metric=current_metric,
        required_metric=required_metric,
        action_labels=tuple(_compact_action_label(option) for option in primary.options[:3]),
    )


def _viewport(hero, journey: JourneyView) -> FirstViewportKpis:
    try_label = None
    if hero.try_label:
        try_label = hero.try_label.replace("≈ ", "")
    progress = "—"
    if journey.progress_pct is not None:
        progress = f"%{journey.progress_pct:.1f}"
    return FirstViewportKpis(
        wealth_usd=hero.usd_label,
        wealth_try=try_label,
        gain_usd=hero.gain_usd_label,
        gain_pct=hero.gain_pct_label,
        progress_compact=progress,
        largest_symbol=hero.largest_symbol,
        largest_weight=hero.largest_weight_label,
        valuation_chip=hero.valuation_label,
    )


def build_performance_strip(center: Optional[PerformanceCenterView]) -> PerformanceStrip:
    if center is None or center.history is None:
        return PerformanceStrip(
            comparable=False,
            period_return=None,
            investment_gain=None,
            net_contribution=None,
            best_product=None,
            weakest_product=None,
            limitation=INCOMPARABLE_HISTORY,
        )
    hist = center.history
    comparable = (
        hist.history_state == WealthHistoryState.COMPARABLE
        and hist.return_pct is not None
    )
    period_return = f"{float(hist.return_pct):+.1f}%" if comparable else None
    gain = (
        format_usd_display(float(hist.investment_gain_loss))
        if hist.investment_gain_loss is not None
        else None
    )
    contrib = (
        format_usd_display(float(hist.net_external_contributions))
        if hist.net_external_contributions is not None
        else None
    )
    best = None
    weakest = None
    if comparable and center.best:
        row = center.best[0]
        if row.comparable and row.period_return is not None:
            best = f"{row.symbol} {float(row.period_return):+.1f}%"
    if comparable and center.weakest:
        row = center.weakest[0]
        if row.comparable and row.period_return is not None:
            weakest = f"{row.symbol} {float(row.period_return):+.1f}%"
    return PerformanceStrip(
        comparable=comparable,
        period_return=period_return,
        investment_gain=gain,
        net_contribution=contrib,
        best_product=best,
        weakest_product=weakest,
        limitation=None if comparable else INCOMPARABLE_HISTORY,
    )


def select_latest_complete_segment(
    points: Sequence[WealthHistoryPoint],
) -> Tuple[WealthHistoryPoint, ...]:
    """Latest contiguous complete snapshots, newest-first walk until a partial."""
    tail: list[WealthHistoryPoint] = []
    for point in reversed(tuple(points)):
        if point.is_partial:
            break
        tail.append(point)
    return tuple(reversed(tail))


def present_wealth_curve(points: Sequence[WealthHistoryPoint]) -> WealthCurvePresentation:
    comparable = select_latest_complete_segment(points)
    technical = tuple(point for point in points if point.is_partial)
    latest = comparable[-1] if comparable else None
    stored = tuple(points)
    if len(comparable) >= 2:
        return WealthCurvePresentation(
            mode=CURVE_MODE_CHART,
            comparable_points=comparable,
            technical_points=technical,
            latest_complete=latest,
            compact_copy=None,
            show_chart=True,
            all_points=stored,
        )
    if len(comparable) == 1:
        return WealthCurvePresentation(
            mode=CURVE_MODE_ONE_POINT,
            comparable_points=comparable,
            technical_points=technical,
            latest_complete=latest,
            compact_copy=ONE_POINT_HISTORY,
            show_chart=False,
            all_points=stored,
        )
    return WealthCurvePresentation(
        mode=CURVE_MODE_EMPTY,
        comparable_points=(),
        technical_points=technical,
        latest_complete=None,
        compact_copy=INCOMPARABLE_HISTORY,
        show_chart=False,
        all_points=stored,
    )


def _join_tr(names: Sequence[str]) -> str:
    clean = [name for name in names if name]
    if not clean:
        return ""
    if len(clean) == 1:
        return clean[0]
    if len(clean) == 2:
        return f"{clean[0]} ve {clean[1]}"
    return f"{', '.join(clean[:-1])} ve {clean[-1]}"


def _plan_gap_supported(
    *,
    journey: Optional[JourneyView],
    priority: Optional[DashboardPrioritySection],
) -> bool:
    titles = tuple(item.title for item in (priority.items if priority else ()))
    if CONTRIBUTION_PLAN_TITLE in titles:
        return True
    copy = getattr(journey, "interpretation", "") if journey is not None else ""
    return bool(copy and "katkı" in copy and "2031" in copy)


def build_portfolio_commentary(
    *,
    largest_symbol: Optional[str] = None,
    largest_weight_pct: Optional[float] = None,
    gain_pct_label: Optional[str] = None,
    winners: Sequence[GainLossRow] = (),
    losers: Sequence[GainLossRow] = (),
    journey: Optional[JourneyView] = None,
    priority: Optional[DashboardPrioritySection] = None,
    decision_available: bool = False,
    gain_available: bool = False,
) -> PortfolioCommentary:
    insights: list[str] = []
    titles = tuple(item.title for item in (priority.items if priority else ()))
    conc_signal = CONCENTRATION_TITLE in titles
    over_threshold = (
        largest_weight_pct is not None
        and largest_weight_pct >= CONCENTRATION_REVIEW_THRESHOLD_PCT
    )
    no_concentration = decision_available and not conc_signal and not over_threshold
    plan_gap = _plan_gap_supported(journey=journey, priority=priority)

    if decision_available and no_concentration:
        insights.append(NO_CONCENTRATION_COPY)
    elif decision_available and (conc_signal or over_threshold) and largest_symbol:
        insights.append(
            f"En büyük pozisyon {largest_symbol} {CONCENTRATION_FLAG_COPY}."
        )

    if gain_available:
        pos = [row.symbol for row in winners[:3] if row.symbol]
        neg = [row.symbol for row in losers[:2] if row.symbol]
        if pos and neg:
            insights.append(
                f"Getiriyi şu anda özellikle {_join_tr(pos)} taşıyor; "
                f"{_join_tr(neg)} negatif tarafta."
            )
        elif pos:
            insights.append(f"Getiriyi şu anda özellikle {_join_tr(pos)} taşıyor.")

    if plan_gap:
        insights.append(PLAN_GAP_INSIGHT)

    chips: list[str] = []
    if largest_symbol and largest_weight_pct is not None:
        chips.append(f"{largest_symbol} %{largest_weight_pct:.1f}")
    if gain_pct_label:
        chips.append(f"K/Z {gain_pct_label}")
    if journey is not None and journey.earliest_label:
        chips.append(f"Hedef yılı {journey.earliest_label}")

    synthesis = None
    if decision_available and no_concentration and plan_gap:
        synthesis = SYNTHESIS_PLAN_GAP
    elif decision_available and conc_signal and plan_gap:
        synthesis = "Ana açıklar: yoğunlaşma incelemesi ve 2031 hedefi için katkı hızı."
    elif decision_available and conc_signal and largest_symbol:
        synthesis = f"Mevcut ana sinyal {largest_symbol} yoğunlaşma incelemesi."
    elif decision_available and priority is not None and priority.healthy:
        synthesis = HEALTHY_MESSAGE
    elif decision_available and priority is not None and priority.items:
        synthesis = f"Mevcut ana konu: {priority.items[0].title}."

    return PortfolioCommentary(
        insights=tuple(insights[:MAX_COMMENTARY_INSIGHTS]),
        synthesis=synthesis,
        chips=tuple(chips[:MAX_COMMENTARY_CHIPS]),
    )


def format_holdings_table_rows(rows: Sequence[HoldingsTableRow]) -> Tuple[dict, ...]:
    ordered = sorted(
        rows,
        key=lambda row: float(row.market_value or 0.0),
        reverse=True,
    )
    formatted = []
    for row in ordered:
        qty = "—"
        if row.quantity is not None:
            qty = f"{row.quantity:.4f}".rstrip("0").rstrip(".")
        price = "—"
        if row.current_price is not None:
            price = f"{row.current_price:,.2f}"
        market = "—" if row.market_value is None else format_usd_display(float(row.market_value))
        weight = "—" if row.weight_pct is None else f"%{float(row.weight_pct):.1f}"
        cost = "—" if row.cost_missing or row.cost_basis is None else format_usd_display(float(row.cost_basis))
        gain = "—" if row.cost_missing or row.unrealized_pl is None else format_usd_display(float(row.unrealized_pl))
        gain_pct = "—" if row.cost_missing or row.pl_pct is None else f"{float(row.pl_pct):+.1f}%"
        score = "—" if row.nabi_score is None else f"{float(row.nabi_score):.1f}"
        formatted.append(
            {
                "Sembol": row.symbol or "—",
                "Varlık": row.asset_type or "—",
                "Kurum": row.institution or "—",
                "Adet": qty,
                "Güncel Fiyat": price,
                "Piyasa Değeri": market,
                "Portföy Payı": weight,
                "Maliyet": cost,
                "K/Z": gain,
                "K/Z %": gain_pct,
                "NABI Score": score,
                "Karar": row.decision or "—",
            }
        )
    return tuple(formatted)


def build_wealth_command_center(
    view: PortfolioIntelligenceView,
    *,
    wealth=None,
    accounts: Sequence[Mapping[str, Any]] = (),
    assets: Sequence[Mapping[str, Any]] = (),
    positions: Sequence[Mapping[str, Any]] = (),
    candidates: Sequence[Mapping[str, Any]] = (),
    snapshots: Sequence[Any] = (),
    transactions: Sequence[Any] = (),
    account_ids: Sequence[str] = (),
    portfolio_id: str = "",
    fx_service: Optional[FxRateService] = None,
    operating=None,
    cockpit: Optional[PortfolioCockpitView] = None,
    performance: Optional[PerformanceCenterView] = None,
) -> WealthCommandCenterView:
    from components.wealth_brief_ui import compose_wealth_operating_views

    fx = fx_service
    if fx is None and wealth is not None:
        fx = FxRateService(getattr(wealth, "client", None))
    ops = operating
    if ops is None and wealth is not None:
        ops = compose_wealth_operating_views(
            portfolio_view=view,
            wealth=wealth,
            accounts=list(accounts),
            candidates=candidates,
            snapshots=snapshots,
        )
    center = performance
    if center is None and ops is not None:
        center = ops.performance
    if center is None:
        center = _select_performance(
            snapshots,
            transactions=transactions,
            account_ids=account_ids,
            portfolio_id=portfolio_id,
        )
    built = cockpit or build_portfolio_cockpit(
        view,
        fx_service=fx,
        accounts=accounts,
        assets=assets,
        positions=positions,
        candidates=candidates,
        performance=center,
        benchmark_available=False,
    )
    if ops is not None:
        presented = present_action_center(ops.decision)
        priority = present_priority_section(presented, limit=MAX_PRIORITY)
        journey = _journey(ops.goal_dashboard)
    else:
        priority = DashboardPrioritySection(True, (), HEALTHY_MESSAGE)
        journey = JourneyView("—", "—", "—", "—", "—", "—", "—", None, "")
    ranked = tuple(sorted(built.holding_weights, key=lambda row: row.market_value, reverse=True))
    top = ranked[:MAX_TOP_HOLDINGS]
    rest = ranked[len(top):]
    excluded = sum(1 for row in built.holdings_table if row.cost_missing)
    remaining = len(rest)
    other_weight = float(sum(row.weight_pct for row in rest))
    largest_weight = top[0].weight_pct if top else None
    if snapshots:
        curve = present_wealth_curve(history_points_from_snapshots(snapshots))
    elif center is not None and center.history is not None:
        curve = present_wealth_curve(center.history.curve_points)
    else:
        curve = present_wealth_curve(())
    commentary = build_portfolio_commentary(
        largest_symbol=built.hero.largest_symbol,
        largest_weight_pct=largest_weight,
        gain_pct_label=built.hero.gain_pct_label,
        winners=built.winners,
        losers=built.losers,
        journey=journey if ops is not None else None,
        priority=priority if ops is not None else None,
        decision_available=ops is not None,
        gain_available=built.gain_available,
    )
    return WealthCommandCenterView(
        title=COMMAND_TITLE,
        cockpit=built,
        usd_total=canonical_total_wealth_usd(view),
        priority=priority,
        journey=journey,
        treemap=_treemap(view, built),
        top_holdings=top,
        winners=built.winners,
        losers=built.losers,
        gain_available=built.gain_available,
        gain_limitation=None if built.gain_available else COST_MISSING_COPY,
        performance=center,
        excluded_cost_count=excluded,
        viewport=_viewport(built.hero, journey),
        priority_focus=_priority_focus(priority, journey),
        supported_periods=list_comparable_periods(snapshots),
        performance_strip=build_performance_strip(center),
        other_holdings_count=remaining,
        other_holdings_weight=other_weight,
        commentary=commentary,
        history_curve=curve,
        show_period_controls=curve.show_chart,
    )
