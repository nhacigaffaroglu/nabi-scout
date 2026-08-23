"""NABI — Bugün dashboard composition. No financial engines."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Sequence, Tuple

from components.portfolio_decision_center_ui import (
    HEALTHY_MESSAGE,
    ActionCenterPresentation,
    PresentedAction,
)
from services.candidate_pipeline_presentation import (
    NO_OPPORTUNITY_COPY,
    display_nabi_score,
    is_actionable_opportunity,
)
from services.fx_rate_service import FxRateService
from services.portfolio_intelligence_enrichment_contract import (
    CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT,
    PortfolioIntelligenceDashboardView,
)
from services.total_wealth_service import TotalWealthMetrics
from services.wealth_brief_presentation import (
    BriefGoal,
    BriefNewMoney,
    BriefPerformance,
    WealthBrief,
)
from services.wealth_performance_center_presentation import INSUFFICIENT_COPY

DASHBOARD_TITLE = "NABI — Bugün"
SECTION_WEALTH = "Servet"
SECTION_GOAL = "2031 Hedefi"
SECTION_PRIORITY = "NABI'nin Bugünkü Önceliği"
SECTION_PORTFOLIO = "Portföy"
SECTION_OPPORTUNITIES = "Fırsatlar"
SECTION_NEW_MONEY = "Yeni Para"
SECTION_PERFORMANCE = "Performans"
MAX_DASHBOARD_ACTIONS = 3
MAX_OPPORTUNITIES = 3
MAX_TOP_HOLDINGS = 5
NEW_MONEY_LEAD_TEMPLATE = "Bu ay {amount} yatırılsaydı NABI..."
FX_MISSING_COPY = "Güncel USDTRY yok; TRY karşılığı gösterilmiyor."
FX_STALE_COPY = "Güncel USDTRY eski; TRY karşılığı gösterilmiyor."
NO_CHANGE_COPY = "Karşılaştırılabilir servet geçmişi yok; değişim gösterilmiyor."


@dataclass(frozen=True)
class TryEquivalentView:
    amount: Optional[float]
    label: Optional[str]
    rate: Optional[float]
    rate_date: Optional[str]
    available: bool
    limitation: Optional[str]


@dataclass(frozen=True)
class DashboardWealthSection:
    usd_amount: Optional[float]
    usd_label: str
    try_equivalent: TryEquivalentView
    valuation_complete: bool
    valuation_label: str
    coverage_pct: Optional[float]
    change_label: Optional[str]
    limitation: Optional[str]


@dataclass(frozen=True)
class DashboardActionItem:
    title: str
    severity: str
    explanation: str
    options: Tuple[str, ...]
    evidence: Tuple[str, ...] = ()


@dataclass(frozen=True)
class DashboardPrioritySection:
    healthy: bool
    items: Tuple[DashboardActionItem, ...]
    empty_copy: str


@dataclass(frozen=True)
class DashboardHoldingRow:
    symbol: str
    weight_label: str
    value_label: str


@dataclass(frozen=True)
class DashboardPortfolioSection:
    holdings: Tuple[DashboardHoldingRow, ...]
    allocation_lines: Tuple[str, ...]
    concentration_label: Optional[str]
    imbalance_warnings: Tuple[str, ...]


@dataclass(frozen=True)
class DashboardOpportunityRow:
    symbol: str
    nabi_score: Optional[float]
    decision: str
    reason: Optional[str]


@dataclass(frozen=True)
class DashboardOpportunitySection:
    rows: Tuple[DashboardOpportunityRow, ...]
    empty_copy: str


@dataclass(frozen=True)
class NabiTodayDashboard:
    title: str
    wealth: DashboardWealthSection
    goal: BriefGoal
    priority: DashboardPrioritySection
    portfolio: DashboardPortfolioSection
    opportunities: DashboardOpportunitySection
    new_money: BriefNewMoney
    new_money_lead: str
    performance: BriefPerformance


def format_usd_display(amount: Optional[float]) -> str:
    if amount is None:
        return "—"
    return f"${amount:,.0f}"


def format_try_compact(amount: Optional[float]) -> Optional[str]:
    if amount is None:
        return None
    if abs(amount) >= 1_000_000:
        return f"₺{amount / 1_000_000:.2f} Mn"
    return f"₺{amount:,.0f}"


def present_current_try_equivalent(
    usd_amount: Optional[float],
    fx_service: Optional[FxRateService],
) -> TryEquivalentView:
    """TRY display from persisted CURRENT FX only. Never planning FX."""
    if usd_amount is None:
        return TryEquivalentView(
            amount=None,
            label=None,
            rate=None,
            rate_date=None,
            available=False,
            limitation=FX_MISSING_COPY,
        )
    if fx_service is None:
        return TryEquivalentView(
            amount=None,
            label=None,
            rate=None,
            rate_date=None,
            available=False,
            limitation=FX_MISSING_COPY,
        )
    result = fx_service.convert_amount(
        amount=usd_amount,
        from_currency="USD",
        to_currency="TRY",
    )
    if result.unavailable or not result.converted or result.converted_amount is None:
        return TryEquivalentView(
            amount=None,
            label=None,
            rate=result.rate_used,
            rate_date=result.rate_date,
            available=False,
            limitation=result.limitation or FX_MISSING_COPY,
        )
    if result.stale:
        return TryEquivalentView(
            amount=None,
            label=None,
            rate=result.rate_used,
            rate_date=result.rate_date,
            available=False,
            limitation=FX_STALE_COPY,
        )
    return TryEquivalentView(
        amount=float(result.converted_amount),
        label=format_try_compact(float(result.converted_amount)),
        rate=result.rate_used,
        rate_date=result.rate_date,
        available=True,
        limitation=None,
    )


def select_dashboard_actions(
    presented: ActionCenterPresentation,
    *,
    limit: int = MAX_DASHBOARD_ACTIONS,
) -> Tuple[PresentedAction, ...]:
    if presented.healthy:
        return ()
    rows = [row for row in presented.visible_actions if row.id != "continue_observation"]
    return tuple(rows[: max(0, limit)])


def present_priority_section(
    presented: ActionCenterPresentation,
    *,
    limit: int = MAX_DASHBOARD_ACTIONS,
) -> DashboardPrioritySection:
    items = tuple(
        DashboardActionItem(
            title=row.title,
            severity=row.priority_label,
            explanation=row.explanation,
            options=row.options,
            evidence=row.evidence_lines,
        )
        for row in select_dashboard_actions(presented, limit=limit)
    )
    return DashboardPrioritySection(
        healthy=not items,
        items=items,
        empty_copy=HEALTHY_MESSAGE,
    )


def present_opportunity_section(
    candidates: Sequence[Mapping[str, Any]],
    *,
    limit: int = MAX_OPPORTUNITIES,
) -> DashboardOpportunitySection:
    qualified: list[DashboardOpportunityRow] = []
    for candidate in candidates:
        if not is_actionable_opportunity(candidate):
            continue
        reason = (
            str(candidate.get("main_reason") or candidate.get("investment_thesis") or "")
            .strip()
            or None
        )
        qualified.append(
            DashboardOpportunityRow(
                symbol=str(candidate.get("symbol") or "").strip().upper(),
                nabi_score=display_nabi_score(candidate),
                decision=str(candidate.get("decision") or ""),
                reason=reason,
            )
        )

    def _rank(row: DashboardOpportunityRow) -> tuple[int, float, str]:
        score = row.nabi_score if row.nabi_score is not None else -1.0
        strong = 0 if row.decision == "GÜÇLÜ ADAY" else 1
        return (strong, -score, row.symbol)

    qualified.sort(key=_rank)
    return DashboardOpportunitySection(
        rows=tuple(qualified[: max(0, limit)]),
        empty_copy=NO_OPPORTUNITY_COPY,
    )


def present_portfolio_section(
    dashboard: PortfolioIntelligenceDashboardView,
    *,
    currency: str,
) -> DashboardPortfolioSection:
    holdings: list[DashboardHoldingRow] = []
    for row in dashboard.consolidated_symbols[:MAX_TOP_HOLDINGS]:
        if not row.symbol:
            continue
        weight = (
            f"%{row.portfolio_weight_pct:.1f}"
            if row.portfolio_weight_pct is not None
            else "—"
        )
        value = (
            f"{row.total_market_value:,.0f} {currency}"
            if row.total_market_value is not None
            else "—"
        )
        holdings.append(
            DashboardHoldingRow(
                symbol=row.symbol,
                weight_label=weight,
                value_label=value,
            )
        )
    allocation_lines = []
    for slice_row in dashboard.base.asset_class_allocation[:4]:
        allocation_lines.append(
            f"{slice_row.label}: %{slice_row.weight_pct:.0f}"
        )
    concentration = None
    if dashboard.top5_concentration_pct:
        concentration = f"En büyük 5 pozisyon: %{dashboard.top5_concentration_pct:.0f}"
    warnings = tuple(
        item.title
        for item in dashboard.attention_items
        if item.severity in {"high", "watch"}
        and (
            "yoğun" in item.title.casefold()
            or "dengesiz" in item.title.casefold()
            or (item.metric_value or 0) >= CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT
        )
    )[:3]
    return DashboardPortfolioSection(
        holdings=tuple(holdings),
        allocation_lines=tuple(allocation_lines),
        concentration_label=concentration,
        imbalance_warnings=warnings,
    )


def _wealth_change_label(performance: BriefPerformance) -> Optional[str]:
    if performance.return_label:
        return f"{performance.period_label}: {performance.return_label}"
    return None


def present_wealth_section(
    metrics: TotalWealthMetrics,
    *,
    coverage_pct: Optional[float],
    fx_service: Optional[FxRateService],
    performance: BriefPerformance,
) -> DashboardWealthSection:
    usd = metrics.total_wealth
    try_view = present_current_try_equivalent(usd, fx_service)
    complete = not metrics.partial_total
    change = _wealth_change_label(performance)
    limitation_parts = [part for part in (metrics.limitation, try_view.limitation) if part]
    if change is None:
        limitation_parts.append(NO_CHANGE_COPY)
    return DashboardWealthSection(
        usd_amount=usd,
        usd_label=format_usd_display(usd),
        try_equivalent=try_view,
        valuation_complete=complete,
        valuation_label=(
            "Değerleme tamam" if complete else "Değerleme kısmi — gösterilen tutar alt sınırdır."
        ),
        coverage_pct=coverage_pct,
        change_label=change,
        limitation=" ".join(limitation_parts) if limitation_parts else None,
    )


def build_nabi_today_dashboard(
    *,
    metrics: TotalWealthMetrics,
    coverage_pct: Optional[float],
    fx_service: Optional[FxRateService],
    pi_dashboard: PortfolioIntelligenceDashboardView,
    brief: WealthBrief,
    presented_actions: ActionCenterPresentation,
    candidates: Sequence[Mapping[str, Any]],
) -> NabiTodayDashboard:
    performance = brief.performance
    return NabiTodayDashboard(
        title=DASHBOARD_TITLE,
        wealth=present_wealth_section(
            metrics,
            coverage_pct=coverage_pct,
            fx_service=fx_service,
            performance=performance,
        ),
        goal=brief.goal,
        priority=present_priority_section(presented_actions),
        portfolio=present_portfolio_section(pi_dashboard, currency=metrics.base_currency),
        opportunities=present_opportunity_section(candidates),
        new_money=brief.new_money,
        new_money_lead=NEW_MONEY_LEAD_TEMPLATE.format(amount=brief.new_money.amount_label),
        performance=performance,
    )
