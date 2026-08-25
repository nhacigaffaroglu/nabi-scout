"""NABI — Bugün executive orchestration. No financial or research engines."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence, Tuple

from services.portfolio_decision_intelligence import PortfolioDecisionView
from services.wealth_new_money_allocation import AllocationPlan

from components.portfolio_decision_center_ui import (
    CONTRIBUTION_PLAN_TITLE,
    HEALTHY_MESSAGE,
    ActionCenterPresentation,
)
from services.candidate_pipeline_presentation import (
    NO_OPPORTUNITY_COPY,
    is_actionable_opportunity,
)
from services.nabi_dashboard_presentation import (
    DashboardPrioritySection,
    DashboardWealthSection,
    present_priority_section,
)
from services.opportunity_center_presentation import (
    FIRSATLAR_PAGE,
    FIRSATLARI_GOR_LABEL,
    MAX_TODAY_OPPORTUNITIES,
    TodayOpportunityCard,
    count_research_waiting,
    count_strong_opportunities,
    opportunity_teaser_copy,
    present_today_opportunity_cards,
)
from services.portfolio_cockpit_presentation import PortfolioCockpitView
from services.wealth_brief_presentation import BriefNewMoney
from services.wealth_command_center_presentation import (
    GAIN_KPI_LABEL,
    NO_CONCENTRATION_COPY,
    ONE_POINT_HISTORY,
    PLAN_GAP_INSIGHT,
    PRIORITY_OVERFLOW_TEMPLATE,
    PriorityFocus,
    _journey,
    _priority_focus,
    build_portfolio_commentary,
    build_performance_strip,
)
from services.nabi_recommendation import (
    NABIRecommendation,
    build_nabi_recommendation,
)
from services.nabi_decision_orchestrator import build_nabi_decision_v3
from services.nabi_decision_contract import NabiDecisionV3
from services.nabi_recommendation_history_presentation import present_tracking_status
from services.wealth_goal_center_presentation import GoalCenterDashboard
from services.wealth_performance_center_presentation import PerformanceCenterView

TODAY_TITLE = "NABI — Bugün"
SECTION_STATUS = "Bugünkü Durum"
SECTION_PRIORITY = "Bugünkü Öncelik"
SECTION_ACTIONS = "Yapılacaklar"
SECTION_OPPORTUNITIES = "Fırsatlar"
SECTION_PORTFOLIO = "Portföy & Hedef"
SECTION_PERFORMANCE = "Kısa Performans"
SECTION_DETAILS = "Detaylar"
KPI_WEALTH = "TOPLAM SERVET"
KPI_GAIN = GAIN_KPI_LABEL
KPI_PROGRESS = "2031 İLERLEME"
KPI_OPPORTUNITIES = "FIRSATLAR"
WEALTH_PAGE = "pages/10_Wealth.py"
WEALTH_OPEN_LABEL = "Wealth'i Aç"
ALLOCATION_OPEN_LABEL = "Dağılımı Gör"
NEW_MONEY_READY_TEMPLATE = "Bu ayki {amount} için NABI dağılım önerisi hazır."
NEW_MONEY_ADVISORY = "Danışmanlık özetidir; işlem uygulanmaz."
MAX_TODAY_ACTIONS = 3
MAX_NEW_MONEY_PREVIEW = 2
ACTION_REVIEW_PLAN = "Katkı planını gözden geçir"
ACTION_REVIEW_ALLOCATION = "Yeni para dağılımını incele"
ACTION_REVIEW_OPPORTUNITIES = "Fırsatları incele"
ACTION_RESEARCH_STRONG = "Güçlü adayı araştır"
ACTION_FINISH_RESEARCH = "Eksik araştırmaları tamamla"
ACTION_WAIT_HISTORY = "Performans geçmişi oluşmasını bekle"
WHY_PLAN_GAP = "2031 hedefi için mevcut plan yetersiz."
WHY_OPPORTUNITIES = "{count} tamamlanmış aday mevcut."
WHY_RESEARCH = "{count} şirket araştırma bekliyor."


@dataclass(frozen=True)
class TodayKpi:
    label: str
    value: str
    caption: Optional[str] = None


@dataclass(frozen=True)
class TodayAction:
    title: str
    why: str
    destination_label: str
    destination_page: str


@dataclass(frozen=True)
class TodayPriorityCard:
    healthy: bool
    severity: Optional[str]
    title: str
    current_metric: Optional[str]
    required_metric: Optional[str]
    overflow_label: Optional[str]
    empty_copy: str
    explanation: Optional[str]


@dataclass(frozen=True)
class TodayOpportunityPreview:
    qualified_count: int
    strong_count: int
    waiting_research: int
    cards: Tuple[TodayOpportunityCard, ...]
    teaser: str
    research_line: Optional[str]


@dataclass(frozen=True)
class TodayPortfolioPreview:
    largest_symbol: Optional[str]
    largest_weight: Optional[str]
    gain_usd: Optional[str]
    gain_pct: Optional[str]
    projected_label: str
    reach_year: Optional[str]
    interpretation: Optional[str]


@dataclass(frozen=True)
class TodayNewMoneyPreview:
    ready: bool
    line: str
    symbols: Tuple[str, ...]
    limitation: Optional[str]


@dataclass(frozen=True)
class TodayPerformancePreview:
    comparable: bool
    period_return: Optional[str]
    best: Optional[str]
    weakest: Optional[str]
    copy: Optional[str]


@dataclass(frozen=True)
class NabiTodayExecutive:
    title: str
    synthesis: str
    kpis: Tuple[TodayKpi, ...]
    priority: TodayPriorityCard
    actions: Tuple[TodayAction, ...]
    opportunities: TodayOpportunityPreview
    portfolio: TodayPortfolioPreview
    new_money: TodayNewMoneyPreview
    performance: TodayPerformancePreview
    material_alert: Optional[str]
    wealth_usd: str
    details: Tuple[str, ...]
    recommendation: NABIRecommendation
    decision_v3: Optional[NabiDecisionV3] = None
    tracking_status: str = ""


def count_qualified_opportunities(candidates: Sequence[Mapping[str, Any]]) -> int:
    return sum(1 for row in candidates if is_actionable_opportunity(row))


def _largest_weight_pct(cockpit: PortfolioCockpitView) -> Optional[float]:
    symbol = cockpit.hero.largest_symbol
    if not symbol:
        return None
    for row in cockpit.holding_weights:
        if row.symbol == symbol:
            return row.weight_pct
    return None


def build_today_synthesis(
    *,
    commentary_insights: Sequence[str],
    commentary_synthesis: Optional[str],
    opportunity_teaser: str,
) -> str:
    lead = ""
    insights = [str(item).strip() for item in commentary_insights if str(item).strip()]
    if insights:
        first = insights[0].rstrip(".")
        rest = insights[1:]
        plan = next((item for item in rest if "katkı hızında" in item or item == PLAN_GAP_INSIGHT), None)
        if plan:
            lead = f"{first}; ana konu 2031 hedefi için katkı hızında"
        else:
            lead = first
    elif commentary_synthesis:
        lead = commentary_synthesis.rstrip(".")
    if lead and opportunity_teaser:
        return f"{lead}. {opportunity_teaser}"
    return lead or opportunity_teaser


def present_today_priority(focus: PriorityFocus, priority: DashboardPrioritySection) -> TodayPriorityCard:
    if focus.primary is None:
        return TodayPriorityCard(
            healthy=True,
            severity=None,
            title=priority.empty_copy or HEALTHY_MESSAGE,
            current_metric=None,
            required_metric=None,
            overflow_label=None,
            empty_copy=HEALTHY_MESSAGE,
            explanation=None,
        )
    overflow = (
        PRIORITY_OVERFLOW_TEMPLATE.format(count=focus.overflow_count)
        if focus.overflow_count
        else None
    )
    return TodayPriorityCard(
        healthy=False,
        severity=focus.primary.severity,
        title=focus.primary.title,
        current_metric=focus.current_metric,
        required_metric=focus.required_metric,
        overflow_label=overflow,
        empty_copy=HEALTHY_MESSAGE,
        explanation=focus.primary.explanation,
    )


def _action(
    title: str,
    why: str,
    *,
    destination_label: str,
    destination_page: str,
) -> TodayAction:
    return TodayAction(
        title=title,
        why=why,
        destination_label=destination_label,
        destination_page=destination_page,
    )


def build_today_actions(
    *,
    focus: PriorityFocus,
    qualified_count: int,
    strong_count: int,
    waiting_research: int,
    new_money: TodayNewMoneyPreview,
    performance: TodayPerformancePreview,
    limit: int = MAX_TODAY_ACTIONS,
) -> Tuple[TodayAction, ...]:
    items: list[TodayAction] = []
    if focus.primary is not None and focus.primary.title == CONTRIBUTION_PLAN_TITLE:
        items.append(
            _action(
                ACTION_REVIEW_PLAN,
                WHY_PLAN_GAP,
                destination_label="2031 Hedef",
                destination_page=WEALTH_PAGE,
            )
        )
    if new_money.ready:
        items.append(
            _action(
                ACTION_REVIEW_ALLOCATION,
                new_money.line,
                destination_label="Wealth",
                destination_page=WEALTH_PAGE,
            )
        )
    if qualified_count > 0:
        title = ACTION_RESEARCH_STRONG if strong_count else ACTION_REVIEW_OPPORTUNITIES
        items.append(
            _action(
                title,
                WHY_OPPORTUNITIES.format(count=qualified_count),
                destination_label="Fırsatlar",
                destination_page=FIRSATLAR_PAGE,
            )
        )
    elif waiting_research > 0:
        items.append(
            _action(
                ACTION_FINISH_RESEARCH,
                WHY_RESEARCH.format(count=waiting_research),
                destination_label="Fırsatlar",
                destination_page=FIRSATLAR_PAGE,
            )
        )
    if not performance.comparable and len(items) < limit:
        items.append(
            _action(
                ACTION_WAIT_HISTORY,
                performance.copy or ONE_POINT_HISTORY,
                destination_label="Wealth",
                destination_page=WEALTH_PAGE,
            )
        )
    return tuple(items[: max(0, limit)])


def present_new_money_preview(money: BriefNewMoney) -> TodayNewMoneyPreview:
    if money.unavailable_reason and not money.recommendations:
        return TodayNewMoneyPreview(
            ready=False,
            line=money.unavailable_reason,
            symbols=(),
            limitation=money.unavailable_reason,
        )
    line = NEW_MONEY_READY_TEMPLATE.format(amount=money.amount_label)
    symbols = tuple(row.symbol for row in money.recommendations[:MAX_NEW_MONEY_PREVIEW] if row.symbol)
    return TodayNewMoneyPreview(ready=True, line=line, symbols=symbols, limitation=None)


def present_performance_preview(center: Optional[PerformanceCenterView]) -> TodayPerformancePreview:
    strip = build_performance_strip(center)
    if strip.comparable:
        return TodayPerformancePreview(
            comparable=True,
            period_return=strip.period_return,
            best=strip.best_product,
            weakest=strip.weakest_product,
            copy=None,
        )
    return TodayPerformancePreview(
        comparable=False,
        period_return=None,
        best=None,
        weakest=None,
        copy=ONE_POINT_HISTORY,
    )


def build_nabi_today_executive(
    *,
    wealth: DashboardWealthSection,
    cockpit: PortfolioCockpitView,
    goal_dashboard: GoalCenterDashboard,
    presented_actions: ActionCenterPresentation,
    candidates: Sequence[Mapping[str, Any]],
    new_money: BriefNewMoney,
    performance: Optional[PerformanceCenterView],
    decision: Optional[PortfolioDecisionView] = None,
    allocation: Optional[AllocationPlan] = None,
    portfolio_view: Any = None,
) -> NabiTodayExecutive:
    journey = _journey(goal_dashboard)
    full_priority = present_priority_section(presented_actions)
    focus = _priority_focus(full_priority, journey)
    shown_priority = present_today_priority(focus, full_priority)

    qualified = count_qualified_opportunities(candidates)
    strong = count_strong_opportunities(candidates)
    waiting = count_research_waiting(candidates)
    cards = present_today_opportunity_cards(candidates, limit=MAX_TODAY_OPPORTUNITIES)
    teaser = opportunity_teaser_copy(
        strong_count=strong,
        qualified_count=qualified,
        empty_copy=NO_OPPORTUNITY_COPY,
    )
    research_line = (
        f"{waiting} şirket araştırma bekliyor" if waiting and qualified == 0 else None
    )
    opportunities = TodayOpportunityPreview(
        qualified_count=qualified,
        strong_count=strong,
        waiting_research=waiting,
        cards=cards,
        teaser=teaser,
        research_line=research_line,
    )

    largest_weight_pct = _largest_weight_pct(cockpit)
    commentary = build_portfolio_commentary(
        largest_symbol=cockpit.hero.largest_symbol,
        largest_weight_pct=largest_weight_pct,
        gain_pct_label=cockpit.hero.gain_pct_label,
        winners=cockpit.winners,
        losers=cockpit.losers,
        journey=journey,
        priority=full_priority,
        decision_available=True,
        gain_available=cockpit.gain_available,
    )

    progress = (
        f"%{journey.progress_pct:.1f}" if journey.progress_pct is not None else "—"
    )
    try_caption = (
        wealth.try_equivalent.label
        if wealth.try_equivalent.available and wealth.try_equivalent.label
        else None
    )
    kpis = (
        TodayKpi(KPI_WEALTH, wealth.usd_label, try_caption),
        TodayKpi(
            KPI_GAIN,
            cockpit.hero.gain_usd_label or "—",
            cockpit.hero.gain_pct_label,
        ),
        TodayKpi(KPI_PROGRESS, progress, None),
        TodayKpi(KPI_OPPORTUNITIES, str(qualified), None),
    )

    largest_weight = cockpit.hero.largest_weight_label
    interpretation = next(
        (item for item in commentary.insights if item == NO_CONCENTRATION_COPY),
        commentary.insights[0] if commentary.insights else None,
    )
    portfolio = TodayPortfolioPreview(
        largest_symbol=cockpit.hero.largest_symbol,
        largest_weight=largest_weight,
        gain_usd=cockpit.hero.gain_usd_label,
        gain_pct=cockpit.hero.gain_pct_label,
        projected_label=journey.projected_label,
        reach_year=journey.earliest_label,
        interpretation=interpretation,
    )

    money = present_new_money_preview(new_money)
    perf = present_performance_preview(performance)
    actions = build_today_actions(
        focus=focus,
        qualified_count=qualified,
        strong_count=strong,
        waiting_research=waiting,
        new_money=money,
        performance=perf,
    )

    alert = None
    if not wealth.valuation_complete:
        alert = wealth.valuation_label
    elif not wealth.try_equivalent.available and not qualified:
        alert = None

    recommendation = build_nabi_recommendation(
        candidates=candidates,
        decision=decision,
        presented_actions=presented_actions,
        allocation=allocation,
        goal_dashboard=goal_dashboard,
        portfolio_view=portfolio_view,
        new_money_brief=new_money,
        valuation_complete=wealth.valuation_complete,
    )
    decision_v3 = build_nabi_decision_v3(
        candidates=candidates,
        decision=decision,
        presented_actions=presented_actions,
        allocation=allocation,
        goal_dashboard=goal_dashboard,
        portfolio_view=portfolio_view,
        new_money_brief=new_money,
        valuation_complete=wealth.valuation_complete,
        recommendation=recommendation,
    )
    details = tuple(
        item
        for item in (
            wealth.limitation,
            shown_priority.explanation,
            recommendation.why_now,
            *recommendation.evidence_refs,
            f"USD/TRY · {wealth.try_equivalent.rate or '—'}",
            f"Kur tarihi: {wealth.try_equivalent.rate_date or '—'}",
        )
        if item
    )

    return NabiTodayExecutive(
        title=TODAY_TITLE,
        synthesis=recommendation.summary,
        kpis=kpis,
        priority=shown_priority,
        actions=actions,
        opportunities=opportunities,
        portfolio=portfolio,
        new_money=money,
        performance=perf,
        material_alert=alert,
        wealth_usd=wealth.usd_label,
        details=details,
        recommendation=recommendation,
        decision_v3=decision_v3,
        tracking_status=present_tracking_status(None),
    )
