from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Dict, Optional, Sequence

import pandas as pd
import streamlit as st

from components.nabi_design_system import (
    render_data_quality_banner,
    render_executive_hero,
    render_kpi_row,
    render_section_title,
    render_status_badge,
)
from services.portfolio_intelligence_contract import PortfolioIntelligenceView
from services.ui_formatters import format_date_dmy
from services.wealth_goal_models import (
    ContributionPlan,
    CurrentWealthSnapshot,
    GoalEvidenceStatus,
    ProjectionLimitation,
    ProjectionResult,
    current_wealth_from_portfolio_view,
    default_contribution_plan,
    default_wealth_goal_2031,
)
from services.wealth_goal_planning import (
    PLANNING_ASSUMPTION_NOTE,
    USER_ASSUMPTION_NOTE,
    build_what_if_projection,
    contribution_year_schedule,
    current_year_plan_row,
    plan_vs_actual_for_year,
    planning_conversion,
    projected_surplus,
    solve_required_starting_monthly,
)
from services.wealth_contribution_intelligence import (
    ContributionEvidenceQuality,
    ContributionIntelligenceView,
    PERFORMANCE_UNAVAILABLE_COPY,
    PerformanceEvidenceQuality,
    PlanAttributionStatus,
    build_contribution_intelligence,
    planning_end_snapshot,
    select_period_start_snapshot,
)
from services.wealth_projection_engine import project_wealth_goal_scenarios

GOAL_STATUS_LABELS = {
    GoalEvidenceStatus.REACHED: "Hedefe ulaşıldı",
    GoalEvidenceStatus.PROJECTED_TO_REACH: "Mevcut varsayımla hedefe ulaşılıyor",
    GoalEvidenceStatus.PROJECTED_SHORTFALL: "Mevcut varsayımla hedef altında",
    GoalEvidenceStatus.INDETERMINATE: "Yetersiz değerleme / kur varsayımı",
}

GOAL_STATUS_TONES = {
    GoalEvidenceStatus.REACHED: "success",
    GoalEvidenceStatus.PROJECTED_TO_REACH: "info",
    GoalEvidenceStatus.PROJECTED_SHORTFALL: "warning",
    GoalEvidenceStatus.INDETERMINATE: "warning",
}

LIMITATION_COPY = {
    ProjectionLimitation.PARTIAL_VALUATION: (
        "USD portföy değerli; BIST piyasa değeri yok. İlerleme alt sınırdır."
    ),
    ProjectionLimitation.FX_CONVERSION_REQUIRED: (
        "TRY→USD projeksiyonu için açık kur varsayımı gerekli. "
        "Sahte 2031 değeri yok."
    ),
    ProjectionLimitation.CONTRIBUTION_CURRENCY_MISMATCH: (
        "Katkı kur varsayımı para birimleri eşleşmiyor."
    ),
    ProjectionLimitation.BASE_CURRENCY_MISMATCH: (
        "Ölçülen servet hedef para biriminde değil."
    ),
}


def _money(value: Optional[Decimal | float], currency: str) -> str:
    if value is None:
        return "—"
    amount = float(value)
    if currency.upper() == "USD":
        return f"${amount:,.2f}"
    return f"{amount:,.2f} {currency}"


def _pct(value: Optional[Decimal | float]) -> str:
    if value is None:
        return "—"
    return f"{float(value):.1f}%"


def _status_label(status: GoalEvidenceStatus) -> str:
    return GOAL_STATUS_LABELS[status]


def _db_only_goal_view(wealth) -> Optional[PortfolioIntelligenceView]:
    """2031 path reads persisted candidate prices only — no FMP/FX remote."""
    try:
        from services.candidate_price_service import CandidatePriceService
        from services.portfolio_intelligence_service import PortfolioIntelligenceService

        portfolio = wealth.portfolios.get_default_for_user(wealth.user_id)
        if not portfolio or wealth.client is None:
            return None
        intelligence = PortfolioIntelligenceService(
            wealth,
            CandidatePriceService(wealth.client),
            nabi_client=None,
        )
        return intelligence.build_view(portfolio, enrich_nabi=False)
    except Exception:
        return None


def _primary_status(bands: Sequence[ProjectionResult]) -> GoalEvidenceStatus:
    if not bands:
        return GoalEvidenceStatus.INDETERMINATE
    base = next((row for row in bands if row.scenario_name == "Base"), bands[0])
    return base.status


def render_wealth_goal_center(
    *,
    portfolio_view: PortfolioIntelligenceView,
    wealth,
    accounts: Sequence[Dict[str, Any]],
    as_of: Optional[date] = None,
) -> None:
    as_of_date = as_of or date.today()
    goal = default_wealth_goal_2031()
    plan = default_contribution_plan()
    assets = wealth.list_assets()
    positions = wealth.list_positions()
    view = _db_only_goal_view(wealth) or portfolio_view
    snapshot = current_wealth_from_portfolio_view(
        view,
        goal_currency=goal.currency,
        positions=positions,
        assets=assets,
    )
    bands = project_wealth_goal_scenarios(
        goal=goal,
        as_of_date=as_of_date,
        current=snapshot,
        contribution_plan=plan,
    )
    status = _primary_status(bands)
    txns = wealth.list_transactions(limit=2000)
    account_ids = [str(row.get("id") or "") for row in accounts]
    raw_fx = st.session_state.get("wealth_os_2031_usdtry")
    conversion = planning_conversion(
        Decimal(str(raw_fx)) if raw_fx else None,
        contribution_currency=plan.currency,
        goal_currency=goal.currency,
    )
    intelligence = build_contribution_intelligence(
        as_of_date=as_of_date,
        current=snapshot,
        transactions=txns,
        account_ids=account_ids,
        plan=plan,
        goal=goal,
        conversion=conversion,
        start_snapshot=_period_start_snapshot(wealth, view.portfolio_id, as_of_date),
        end_snapshot=planning_end_snapshot(as_of=as_of_date, current=snapshot),
    )
    _render_goal_hero(goal, snapshot, status, bands)
    _render_this_month(intelligence)
    _render_plan_and_performance(intelligence)
    _render_scenario_table(bands, goal.currency)
    _render_contribution_plan(plan, as_of_date, goal.target_date.year)
    comparison = plan_vs_actual_for_year(
        plan,
        as_of=as_of_date,
        transactions=txns,
        account_ids=account_ids,
    )
    _render_plan_vs_actual(comparison)
    _render_what_if_and_required(
        as_of_date=as_of_date,
        current=snapshot,
        plan=plan,
        goal=goal,
    )


def _render_goal_hero(
    goal,
    snapshot: CurrentWealthSnapshot,
    status: GoalEvidenceStatus,
    bands: Sequence[ProjectionResult],
) -> None:
    partial = not snapshot.valuation_complete
    lower = snapshot.current_value_lower_bound
    if partial:
        primary = f"en az {_money(lower, snapshot.currency)}"
        subtitle = (
            f"Ölçülebilen servet: en az {_money(lower, snapshot.currency)} · "
            f"Hedef {_money(goal.target_amount, goal.currency)} · "
            f"{format_date_dmy(goal.target_date)}"
        )
        partial_note = (
            "Kısmi değerleme: USD portföy değerli, BIST piyasa değeri yok. "
            "Hedef ilerlemesi alt sınırdır; eksik varlıklar sıfır sayılmaz."
        )
    else:
        primary = _money(lower, snapshot.currency)
        subtitle = (
            f"Ölçülebilen servet: {_money(lower, snapshot.currency)} · "
            f"Hedef {_money(goal.target_amount, goal.currency)} · "
            f"{format_date_dmy(goal.target_date)}"
        )
        partial_note = None

    base = next((row for row in bands if row.scenario_name == "Base"), bands[0])
    render_executive_hero(
        primary_label="2031 Servet Hedefi",
        primary_value=primary,
        subtitle=subtitle,
        partial=partial,
        partial_note=partial_note,
        delta_lines=[
            (_status_label(status), GOAL_STATUS_TONES[status]),
        ],
    )
    st.markdown(
        render_status_badge(_status_label(status), GOAL_STATUS_TONES[status]),
        unsafe_allow_html=True,
    )
    issues: list[str] = []
    if partial:
        issues.append("USD değerli · BIST piyasa değeri yok")
    if snapshot.unvalued_symbols:
        issues.append("BIST: " + ", ".join(snapshot.unvalued_symbols))
    if ProjectionLimitation.FX_CONVERSION_REQUIRED in base.limitations:
        issues.append("TRY→USD kur varsayımı yok")
    render_data_quality_banner(issues=issues, partial=partial)
    progress = min(max(float(base.progress_pct_lower_bound) / 100.0, 0.0), 1.0)
    st.progress(progress)
    st.caption(
        f"Alt sınır ilerleme: {_pct(base.progress_pct_lower_bound)} · "
        f"Hedefe kalan ölçülebilir fark: {_money(base.measurable_gap, goal.currency)}"
    )
    st.caption("Değerleme ayrıntısı için Portföy Zekâsı sayfasına bakın.")


def _render_this_month(view: ContributionIntelligenceView) -> None:
    render_section_title("Bu Ay")
    planned = _money(view.planned_monthly_contribution, view.currency)
    if view.monthly_evidence_quality == ContributionEvidenceQuality.COMPLETE:
        actual = _money(view.actual_monthly_net_contribution, view.currency)
        remaining = _money(view.monthly_remaining, view.currency)
    else:
        actual = "Kanıt eksik"
        remaining = "—"
    render_kpi_row(
        [
            ("Planlanan katkı", planned, None),
            ("Gerçekleşen katkı", actual, None),
            ("Kalan", remaining, None),
        ]
    )
    if view.monthly_evidence_quality != ContributionEvidenceQuality.COMPLETE:
        st.caption("Gerçekleşen katkı verisi eksik — 0 olarak gösterilmez.")
    if view.monthly_surplus:
        st.caption(f"Bu ay plan fazlası: {_money(view.monthly_surplus, view.currency)}")

    st.markdown("**Yıl ilerlemesi**")
    st.caption(
        f"Plan YTD: {_money(view.planned_ytd_contribution, view.currency)} · "
        f"Yıllık plan: {_money(view.planned_full_year_contribution, view.currency)}"
    )
    if view.ytd_evidence_quality == ContributionEvidenceQuality.COMPLETE:
        ytd_pct = float(view.ytd_completion_pct or 0) / 100.0
        st.progress(min(max(ytd_pct, 0.0), 1.0))
        st.caption(
            f"Gerçekleşen YTD: {_money(view.actual_ytd_net_contribution, view.currency)} · "
            f"Kalan YTD: {_money(view.ytd_remaining, view.currency)}"
        )
    else:
        st.caption("Yıl içi gerçekleşen katkı kanıtı eksik; plan sapması etiketlenmez.")

    st.markdown("**2031 plan yeterliliği**")
    st.caption(USER_ASSUMPTION_NOTE)
    if view.required_starting_monthly_contribution is None:
        st.caption(view.adequacy_summary)
    else:
        st.caption(
            f"Gerekli aylık (Base %8): "
            f"{_money(view.required_starting_monthly_contribution, view.currency)} · "
            f"Plan: {_money(view.planned_monthly_contribution, view.currency)}"
        )
        st.caption(view.adequacy_summary)

    st.info(view.monthly_action_summary)


def _period_start_snapshot(wealth, portfolio_id: str, as_of_date: date):
    try:
        from services.wealth_timeline_service import WealthTimelineService

        snapshots = WealthTimelineService(wealth).list_snapshots(
            str(portfolio_id or ""),
            limit=50,
        )
    except Exception:
        return None
    return select_period_start_snapshot(snapshots, as_of=as_of_date)


def _render_plan_and_performance(view: ContributionIntelligenceView) -> None:
    render_section_title("Plan ve Performans")
    contrib = view.ytd_evidence_quality.value
    if view.ytd_evidence_quality == ContributionEvidenceQuality.COMPLETE:
        contrib_detail = (
            f"YTD {_money(view.actual_ytd_net_contribution, view.currency)} / "
            f"{_money(view.planned_ytd_contribution, view.currency)}"
        )
    else:
        contrib_detail = "Gerçekleşen katkı kanıtı eksik — 0 varsayılmaz."
    if view.performance_evidence_quality == PerformanceEvidenceQuality.COMPLETE:
        if view.investment_return_pct is None:
            perf_detail = (
                f"Kazanç/kayıp {_money(view.investment_gain_loss, 'USD')}"
            )
        else:
            perf_detail = f"{_pct(view.investment_return_pct)} dönem getirisi"
    elif view.performance_evidence_quality == PerformanceEvidenceQuality.PARTIAL:
        perf_detail = "Kısmi — getiri uydurulmaz."
    else:
        perf_detail = PERFORMANCE_UNAVAILABLE_COPY
    goal_detail = view.adequacy_summary
    render_kpi_row(
        [
            ("Katkı durumu", contrib, contrib_detail),
            ("Portföy performansı", view.performance_evidence_quality.value, perf_detail),
            ("Hedef planı durumu", view.plan_adequacy_status.value, goal_detail),
        ]
    )
    st.markdown("**Ana sapma nedeni**")
    st.info(view.attribution_summary)
    st.caption(f"Veri güveni: {view.data_confidence_summary}")
    st.caption(view.planning_benchmark_label)
    if view.planning_benchmark_available:
        st.caption(
            f"Planlama yolu: {_money(view.planning_path_value, 'USD')} · "
            f"Ölçülen dönem sonu: {_money(view.period_end_value, 'USD')}"
        )
    else:
        st.caption("Planlama yolu karşılaştırması mevcut başlangıç kanıtıyla yapılamıyor.")
    if view.performance_evidence_quality == PerformanceEvidenceQuality.UNAVAILABLE:
        st.caption(PERFORMANCE_UNAVAILABLE_COPY)
    if view.attribution_status == PlanAttributionStatus.EVIDENCE_INCOMPLETE:
        st.caption("Eksik kanıt tek başına olumsuz tanı değildir.")


def _render_scenario_table(bands: Sequence[ProjectionResult], currency: str) -> None:
    render_section_title("Senaryo karşılaştırması", description=PLANNING_ASSUMPTION_NOTE)
    rows = []
    for row in bands:
        incomplete = not row.projection_complete
        projection_cell = "—"
        if incomplete:
            if ProjectionLimitation.FX_CONVERSION_REQUIRED in row.limitations:
                projection_cell = LIMITATION_COPY[ProjectionLimitation.FX_CONVERSION_REQUIRED]
            elif row.limitations:
                projection_cell = LIMITATION_COPY.get(row.limitations[0], "Projeksiyon eksik")
            else:
                projection_cell = "Projeksiyon eksik"
        else:
            projection_cell = _money(row.projected_target_date_value, currency)
        rows.append(
            {
                "Senaryo": row.scenario_name,
                "Getiri": f"{float(row.annual_rate) * 100:.0f}%",
                "2031 projeksiyon": projection_cell,
                "Durum": _status_label(row.status),
                "Tahmini ulaşım": (
                    "—"
                    if incomplete or row.projected_goal_reach_date is None
                    else format_date_dmy(row.projected_goal_reach_date)
                ),
                "Toplam katkı": (
                    "—"
                    if incomplete
                    else _money(row.total_projected_contributions, currency)
                ),
                "Yatırım artışı": (
                    "—"
                    if incomplete
                    else _money(row.projected_investment_growth, currency)
                ),
            }
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


def _render_contribution_plan(plan: ContributionPlan, as_of: date, through_year: int) -> None:
    render_section_title("Katkı planı")
    current = current_year_plan_row(plan, as_of=as_of, through_year=through_year)
    render_kpi_row(
        [
            ("Bu yıl aylık plan", _money(current.monthly, plan.currency), None),
            ("Yıllık artış", _pct(plan.annual_increase_rate * 100), None),
            ("Bu yıl plan toplamı", _money(current.annual_total, plan.currency), None),
        ]
    )
    schedule = contribution_year_schedule(plan, as_of=as_of, through_year=through_year)
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Yıl": row.year,
                    "Aylık": _money(row.monthly, plan.currency),
                    "Yıllık toplam": _money(row.annual_total, plan.currency),
                }
                for row in schedule
            ]
        ),
        hide_index=True,
        use_container_width=True,
    )


def _render_plan_vs_actual(comparison) -> None:
    render_section_title(f"Plan vs gerçekleşen ({comparison.year})")
    if comparison.evidence_partial:
        st.warning(
            "Gerçekleşen nakit katkı kanıtı kısmi. "
            "Mevcut pozisyonlar alış/açılış kaydıdır; maliyet nakit katkı sayılmaz."
        )
    if not comparison.available:
        st.info(
            "Gerçekleşen dış katkı bu plan para biriminde ölçülemedi. "
            + (" ".join(comparison.warnings[:2]) if comparison.warnings else "")
        )
        st.caption(
            f"Planlanan {comparison.year} toplamı: "
            f"{_money(comparison.planned_year_total, comparison.currency)}"
        )
        return
    metrics = [
        ("Plan", _money(comparison.planned_year_total, comparison.currency), None),
        (
            "Gerçekleşen net dış katkı",
            _money(comparison.actual_net_external, comparison.currency),
            None,
        ),
    ]
    if not comparison.evidence_partial:
        metrics.extend(
            [
                ("Fark", _money(comparison.difference, comparison.currency), None),
                ("Tamamlanma", _pct(comparison.completion_pct), None),
            ]
        )
    render_kpi_row(metrics)
    if comparison.warnings:
        st.caption(" · ".join(comparison.warnings[:3]))


def _render_what_if_and_required(
    *,
    as_of_date: date,
    current: CurrentWealthSnapshot,
    plan: ContributionPlan,
    goal,
) -> None:
    render_section_title("Ne olur, eğer?", description=USER_ASSUMPTION_NOTE)
    st.caption(
        "Bu kur varsayımı yalnızca gelecek katkı projeksiyonu içindir; "
        "mevcut BIST piyasa değerini üretmez."
    )
    left, right = st.columns(2)
    monthly = left.number_input(
        "Aylık katkı",
        min_value=0.0,
        value=float(plan.starting_monthly),
        step=1000.0,
        key="wealth_os_2031_monthly",
    )
    increase_pct = right.number_input(
        "Yıllık artış %",
        min_value=-99.0,
        value=float(plan.annual_increase_rate * 100),
        step=1.0,
        key="wealth_os_2031_increase_pct",
    )
    return_pct = left.number_input(
        "Yıllık getiri varsayımı %",
        min_value=-99.0,
        value=8.0,
        step=0.5,
        key="wealth_os_2031_return_pct",
    )
    usdtry = right.number_input(
        "USDTRY planlama kuru (1 USD = ? TRY)",
        min_value=0.0,
        value=0.0,
        step=0.1,
        key="wealth_os_2031_usdtry",
        help="0 = kur yok. NABI tahmini değildir.",
    )
    target_date = st.date_input(
        "Hedef tarihi",
        value=goal.target_date,
        key="wealth_os_2031_target_date",
    )
    conversion = planning_conversion(
        Decimal(str(usdtry)) if usdtry else None,
        contribution_currency=plan.currency,
        goal_currency=goal.currency,
    )
    try:
        what_if = build_what_if_projection(
            as_of_date=as_of_date,
            current=current,
            monthly_contribution=Decimal(str(monthly)),
            contribution_currency=plan.currency,
            annual_increase_rate=Decimal(str(increase_pct)) / Decimal(100),
            annual_return_rate=Decimal(str(return_pct)) / Decimal(100),
            target_date=target_date,
            conversion=conversion,
            goal=goal,
        )
    except Exception as exc:
        st.error(str(exc))
        return

    if not what_if.projection_complete:
        detail = LIMITATION_COPY.get(
            what_if.limitations[0],
            "Projeksiyon için kanıt yetersiz.",
        ) if what_if.limitations else "Projeksiyon için kanıt yetersiz."
        st.warning(detail)
    else:
        surplus = projected_surplus(what_if)
        surplus_label = "Fazla" if surplus is not None and surplus >= 0 else "Açık"
        render_kpi_row(
            [
                (
                    "Hedef tarihi değeri",
                    _money(what_if.projected_target_date_value, goal.currency),
                    None,
                ),
                (
                    "Tahmini ulaşım",
                    format_date_dmy(what_if.projected_goal_reach_date)
                    if what_if.projected_goal_reach_date
                    else "—",
                    None,
                ),
                (surplus_label, _money(surplus, goal.currency), None),
                (
                    "Toplam gelecek katkı",
                    _money(what_if.total_projected_contributions, goal.currency),
                    None,
                ),
                (
                    "Yatırım artışı",
                    _money(what_if.projected_investment_growth, goal.currency),
                    None,
                ),
            ]
        )
        st.caption(_status_label(what_if.status))

    render_section_title("Gerekli aylık katkı")
    required = solve_required_starting_monthly(
        as_of_date=as_of_date,
        current=current,
        contribution_currency=plan.currency,
        annual_increase_rate=Decimal(str(increase_pct)) / Decimal(100),
        annual_return_rate=Decimal(str(return_pct)) / Decimal(100),
        conversion=conversion,
        goal=goal,
    )
    if not required.available:
        st.info(
            LIMITATION_COPY.get(
                required.limitation,
                "Gerekli katkı hesaplanamadı — kanıt yetersiz veya hedef bu varsayımlarla ulaşılamaz.",
            )
        )
        return
    st.metric(
        f"Gerekli başlangıç aylık katkı ({required.currency})",
        _money(required.starting_monthly, required.currency),
    )
    st.caption(
        f"Bu katkı ile projeksiyon: {_money(required.projected_target_date_value, goal.currency)}"
    )
    if required.starting_monthly is not None and required.starting_monthly >= Decimal("1000000"):
        st.caption("Bu gerekli katkı çok yüksek; varsayımları gözden geçirin.")
