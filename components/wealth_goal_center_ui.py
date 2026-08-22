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
    projected_surplus,
    solve_required_starting_monthly,
)
from services.wealth_planning_fx import (
    PLANNING_FX_DISCLAIMER,
    PLANNING_FX_NONE_COPY,
    PlanningFxCompleteness,
    PlanningFxSchedule,
    load_planning_fx_schedule,
    missing_years_copy,
    parse_usdtry_assumption,
    required_planning_fx_years,
    save_planning_fx_schedule,
)
from services.wealth_contribution_intelligence import (
    CONTRIBUTION_HISTORY_PARTIAL_COPY,
    CONTRIBUTION_HISTORY_PARTIAL_DETAIL_COPY,
    CONTRIBUTION_HISTORY_UNAVAILABLE_COPY,
    CONTRIBUTION_RECONCILE_ACTION_LABEL,
    CONTRIBUTION_TRACKING_NOT_TRACKED_COPY,
    CONTRIBUTION_TRACKING_UNCONFIGURED_COPY,
    ContributionEvidenceQuality,
    ContributionIntelligenceView,
    PERFORMANCE_UNAVAILABLE_COPY,
    PerformanceEvidenceQuality,
    PlanAttributionStatus,
    build_contribution_intelligence,
    planning_end_snapshot,
    select_period_start_snapshot,
)
from services.wealth_external_cash_flow import (
    FLOW_DEPOSIT,
    FLOW_WITHDRAWAL,
    ContributionReconciliation,
    ContributionTrackingScope,
    contribution_reconciliations_for_wealth,
    load_contribution_tracking_start,
    mark_contribution_reconciled,
    record_tracked_external_cash_flow,
    set_contribution_tracking_start,
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


def format_contribution_actual_label(
    evidence: ContributionEvidenceQuality,
    actual: Optional[Decimal],
    currency: str,
    *,
    scope: ContributionTrackingScope = ContributionTrackingScope.TRACKED,
) -> str:
    if scope == ContributionTrackingScope.UNCONFIGURED:
        return CONTRIBUTION_TRACKING_UNCONFIGURED_COPY
    if scope == ContributionTrackingScope.NOT_TRACKED:
        return CONTRIBUTION_TRACKING_NOT_TRACKED_COPY
    if evidence == ContributionEvidenceQuality.COMPLETE:
        return _money(actual, currency)
    if evidence == ContributionEvidenceQuality.UNAVAILABLE:
        return CONTRIBUTION_HISTORY_UNAVAILABLE_COPY
    return CONTRIBUTION_HISTORY_PARTIAL_COPY


def format_contribution_remaining_label(
    evidence: ContributionEvidenceQuality,
    remaining: Optional[Decimal],
    currency: str,
    *,
    scope: ContributionTrackingScope = ContributionTrackingScope.TRACKED,
) -> str:
    if scope != ContributionTrackingScope.TRACKED:
        return "—"
    if evidence == ContributionEvidenceQuality.COMPLETE:
        return _money(remaining, currency)
    return "—"


def _pct(value: Optional[Decimal | float]) -> str:
    if value is None:
        return "—"
    return f"{float(value):.1f}%"


def _status_label(status: GoalEvidenceStatus) -> str:
    return GOAL_STATUS_LABELS[status]


def _db_only_goal_view(wealth) -> Optional[PortfolioIntelligenceView]:
    """2031 path reads persisted candidate prices + persisted current FX — no FMP/FX remote."""
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
    portfolio_id = str(view.portfolio_id or "")
    snapshot = current_wealth_from_portfolio_view(
        view,
        goal_currency=goal.currency,
        positions=positions,
        assets=assets,
    )
    tracking_start = load_contribution_tracking_start(wealth, portfolio_id)
    fx_schedule = load_planning_fx_schedule(wealth, portfolio_id)
    bands = project_wealth_goal_scenarios(
        goal=goal,
        as_of_date=as_of_date,
        current=snapshot,
        contribution_plan=plan,
        fx_schedule=fx_schedule,
    )
    status = _primary_status(bands)
    txns = wealth.list_transactions(limit=2000)
    account_ids = [str(row.get("id") or "") for row in accounts]
    reconciliations = contribution_reconciliations_for_wealth(wealth, portfolio_id)
    intelligence = build_contribution_intelligence(
        as_of_date=as_of_date,
        current=snapshot,
        transactions=txns,
        account_ids=account_ids,
        plan=plan,
        goal=goal,
        conversion=None,
        start_snapshot=_period_start_snapshot(wealth, view.portfolio_id, as_of_date),
        end_snapshot=planning_end_snapshot(as_of=as_of_date, current=snapshot),
        contribution_reconciliations=reconciliations,
        portfolio_id=portfolio_id or None,
        contribution_tracking_start=tracking_start,
        fx_schedule=fx_schedule,
    )
    current_recon = reconciliations[0] if reconciliations else None
    _render_goal_hero(goal, snapshot, status, bands)
    _render_this_month(intelligence)
    render_planning_fx_assumptions(
        wealth=wealth,
        portfolio_id=portfolio_id,
        as_of=as_of_date,
        goal=goal,
        plan=plan,
        current=fx_schedule,
    )
    render_contribution_tracking_start_setup(
        wealth=wealth,
        portfolio_id=portfolio_id,
        current=tracking_start,
        transactions=txns,
        account_ids=account_ids,
        reconciliations=reconciliations,
    )
    render_contribution_cash_flow_entry(
        wealth=wealth,
        portfolio_id=portfolio_id,
        accounts=accounts,
        tracking_start=tracking_start,
        plan_currency=plan.currency,
    )
    render_contribution_reconciliation_action(
        wealth=wealth,
        portfolio_id=portfolio_id,
        as_of=as_of_date,
        current=current_recon,
        tracking_start=tracking_start,
    )
    _render_plan_and_performance(intelligence)
    _render_scenario_table(bands, goal.currency)
    _render_contribution_plan(plan, as_of_date, goal.target_date.year)
    _render_plan_vs_actual(intelligence)
    _render_what_if_and_required(
        as_of_date=as_of_date,
        current=snapshot,
        plan=plan,
        goal=goal,
        fx_schedule=fx_schedule,
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
    actual = format_contribution_actual_label(
        view.monthly_evidence_quality,
        view.actual_monthly_net_contribution,
        view.currency,
        scope=view.monthly_tracking_scope,
    )
    remaining = format_contribution_remaining_label(
        view.monthly_evidence_quality,
        view.monthly_remaining,
        view.currency,
        scope=view.monthly_tracking_scope,
    )
    render_kpi_row(
        [
            ("Planlanan katkı", planned, None),
            ("Gerçekleşen katkı", actual, None),
            ("Kalan", remaining, None),
        ]
    )
    if view.monthly_tracking_scope == ContributionTrackingScope.UNCONFIGURED:
        st.caption(CONTRIBUTION_TRACKING_UNCONFIGURED_COPY)
    elif view.monthly_tracking_scope == ContributionTrackingScope.NOT_TRACKED:
        st.caption(CONTRIBUTION_TRACKING_NOT_TRACKED_COPY)
    elif view.monthly_evidence_quality == ContributionEvidenceQuality.UNAVAILABLE:
        st.caption(CONTRIBUTION_HISTORY_UNAVAILABLE_COPY)
    elif view.monthly_evidence_quality == ContributionEvidenceQuality.PARTIAL:
        st.caption(CONTRIBUTION_HISTORY_PARTIAL_DETAIL_COPY)
    if view.monthly_tracking_note:
        st.caption(view.monthly_tracking_note)
    if view.monthly_surplus:
        st.caption(f"Bu ay plan fazlası: {_money(view.monthly_surplus, view.currency)}")

    st.markdown("**Yıl ilerlemesi**")
    if view.ytd_tracking_scope == ContributionTrackingScope.UNCONFIGURED:
        st.caption(CONTRIBUTION_TRACKING_UNCONFIGURED_COPY)
    elif view.ytd_tracking_scope == ContributionTrackingScope.NOT_TRACKED:
        st.caption(CONTRIBUTION_TRACKING_NOT_TRACKED_COPY)
    else:
        st.caption(
            f"Takip edilen YTD planı: {_money(view.planned_ytd_contribution, view.currency)} · "
            f"Yıllık plan: {_money(view.planned_full_year_contribution, view.currency)}"
        )
        if view.ytd_evidence_quality == ContributionEvidenceQuality.COMPLETE:
            ytd_pct = float(view.ytd_completion_pct or 0) / 100.0
            st.progress(min(max(ytd_pct, 0.0), 1.0))
            st.caption(
                f"Gerçekleşen YTD: {_money(view.actual_ytd_net_contribution, view.currency)} · "
                f"Kalan YTD: {_money(view.ytd_remaining, view.currency)}"
            )
        elif view.ytd_evidence_quality == ContributionEvidenceQuality.UNAVAILABLE:
            st.caption(CONTRIBUTION_HISTORY_UNAVAILABLE_COPY)
        else:
            st.caption(CONTRIBUTION_HISTORY_PARTIAL_DETAIL_COPY)

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

    if view.monthly_tracking_scope == ContributionTrackingScope.TRACKED:
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
    if view.ytd_tracking_scope == ContributionTrackingScope.UNCONFIGURED:
        contrib_detail = CONTRIBUTION_TRACKING_UNCONFIGURED_COPY
    elif view.ytd_tracking_scope == ContributionTrackingScope.NOT_TRACKED:
        contrib_detail = CONTRIBUTION_TRACKING_NOT_TRACKED_COPY
    elif view.ytd_evidence_quality == ContributionEvidenceQuality.COMPLETE:
        contrib_detail = (
            f"YTD {_money(view.actual_ytd_net_contribution, view.currency)} / "
            f"{_money(view.planned_ytd_contribution, view.currency)}"
        )
    elif view.ytd_evidence_quality == ContributionEvidenceQuality.UNAVAILABLE:
        contrib_detail = CONTRIBUTION_HISTORY_UNAVAILABLE_COPY
    else:
        contrib_detail = CONTRIBUTION_HISTORY_PARTIAL_DETAIL_COPY
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


def render_contribution_tracking_start_setup(
    *,
    wealth,
    portfolio_id: str,
    current: Optional[date],
    transactions: Sequence[Dict[str, Any]] = (),
    account_ids: Sequence[str] = (),
    reconciliations: Sequence[ContributionReconciliation] = (),
) -> None:
    if wealth is None or not str(portfolio_id or "").strip():
        return
    from services.wealth_external_cash_flow import has_tracked_external_flows

    locked = current is not None and (
        bool(reconciliations)
        or has_tracked_external_flows(
            list(transactions),
            account_ids={str(item) for item in account_ids},
            tracking_start=current,
        )
    )
    with st.expander("Katkı takibi başlangıç tarihi", expanded=current is None):
        if current is None:
            st.caption(CONTRIBUTION_TRACKING_UNCONFIGURED_COPY)
            st.caption(
                "Tarih otomatik seçilmez. Katkı raporlaması bu tarihi sizin kaydetmenizle başlar."
            )
        else:
            st.caption(f"Mevcut başlangıç: {format_date_dmy(current)}")
        chosen = st.date_input(
            "Katkı takibi başlangıç tarihi",
            value=current,
            key=f"contrib_tracking_start_{portfolio_id}",
        )
        if locked:
            st.caption("Kayıt veya mutabakat sonrası başlangıç tarihi kilitlidir.")
        submitted = st.button(
            "Başlangıç tarihini kaydet",
            key=f"contrib_tracking_save_{portfolio_id}",
            disabled=locked or chosen is None,
        )
        if not submitted or chosen is None:
            return
        try:
            set_contribution_tracking_start(
                wealth,
                portfolio_id=str(portfolio_id),
                tracking_start=chosen,
                transactions=transactions,
                account_ids=account_ids,
                reconciliations=reconciliations,
            )
            st.success(f"Katkı takibi {format_date_dmy(chosen)} tarihinde başlatıldı.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))


def render_contribution_cash_flow_entry(
    *,
    wealth,
    portfolio_id: str,
    accounts: Sequence[Dict[str, Any]],
    tracking_start: Optional[date],
    plan_currency: str,
) -> None:
    if wealth is None or not str(portfolio_id or "").strip():
        return
    with st.expander("Katkı hareketi", expanded=False):
        confirm_key = f"contrib_flow_confirm_{portfolio_id}"
        if st.session_state.get(confirm_key):
            st.success(str(st.session_state[confirm_key]))
        if tracking_start is None:
            st.info(CONTRIBUTION_TRACKING_UNCONFIGURED_COPY)
            return
        portfolio_accounts = [
            row
            for row in accounts
            if str(row.get("portfolio_id") or "") == str(portfolio_id)
        ] or list(accounts)
        if not portfolio_accounts:
            st.caption("Önce bir hesap gerekir.")
            return
        flow_label = st.selectbox(
            "Hareket türü",
            ["Para Girişi", "Para Çıkışı"],
            key=f"contrib_flow_type_{portfolio_id}",
        )
        amount = st.number_input(
            "Tutar",
            min_value=0.0,
            step=1000.0,
            key=f"contrib_flow_amount_{portfolio_id}",
        )
        currency = st.text_input(
            "Para Birimi",
            value=plan_currency,
            key=f"contrib_flow_ccy_{portfolio_id}",
        )
        occurred = st.date_input(
            "Tarih",
            value=None,
            key=f"contrib_flow_date_{portfolio_id}",
        )
        notes = st.text_input("Not", value="", key=f"contrib_flow_notes_{portfolio_id}")
        account_id = st.selectbox(
            "Hesap",
            options=[str(row.get("id") or "") for row in portfolio_accounts],
            format_func=lambda value: next(
                (
                    str(row.get("name") or value)
                    for row in portfolio_accounts
                    if str(row.get("id") or "") == str(value)
                ),
                value,
            ),
            key=f"contrib_flow_account_{portfolio_id}",
        )
        submitted = st.button("Katkı hareketini kaydet", key=f"contrib_flow_save_{portfolio_id}")
        if not submitted:
            return
        if occurred is None:
            st.error("İşlem tarihi gerekli.")
            return
        flow_type = FLOW_DEPOSIT if flow_label == "Para Girişi" else FLOW_WITHDRAWAL
        try:
            row = record_tracked_external_cash_flow(
                wealth,
                portfolio_id=str(portfolio_id),
                account_id=str(account_id),
                flow_type=flow_type,
                amount=amount,
                currency=currency,
                occurred_at=f"{occurred.isoformat()}T12:00:00+00:00",
                tracking_start=tracking_start,
                notes=notes or None,
            )
            kind = "para girişi" if flow_type == FLOW_DEPOSIT else "para çıkışı"
            ident = str(row.get("id") or "")
            message = (
                f"{float(amount):,.2f} {str(currency).strip().upper()} {kind} kaydedildi."
                + (f" Kayıt: {ident}" if ident else "")
            )
            st.session_state[confirm_key] = message
            st.success(message)
            st.rerun()
        except Exception as exc:
            st.error(str(exc))


def render_contribution_reconciliation_action(
    *,
    wealth,
    portfolio_id: str,
    as_of: date,
    current: Optional[ContributionReconciliation] = None,
    tracking_start: Optional[date] = None,
) -> None:
    """Explicit attestation only. Does not create cash flows or mutate the ledger."""
    if wealth is None or not str(portfolio_id or "").strip():
        return
    with st.expander("Katkı geçmişi mutabakatı", expanded=False):
        st.caption(
            "Bu işlem yatırma, çekme veya alış kaydı oluşturmaz; "
            "yalnızca katkı geçmişinin bu tarihe kadar girildiğini doğrular."
        )
        if tracking_start is None:
            st.info(CONTRIBUTION_TRACKING_UNCONFIGURED_COPY)
            return
        st.caption(f"Takip başlangıcı: {format_date_dmy(tracking_start)}")
        if current is not None:
            st.caption(f"Mevcut mutabakat: {format_date_dmy(current.reconciled_through)}")
        default = current.reconciled_through if current is not None else as_of
        if default < tracking_start:
            default = tracking_start
        through = st.date_input(
            "Mutabakat tarihi",
            value=default,
            key=f"contrib_recon_date_{portfolio_id}",
        )
        submitted = st.button(
            CONTRIBUTION_RECONCILE_ACTION_LABEL,
            key=f"contrib_recon_btn_{portfolio_id}",
        )
        if not submitted:
            return
        try:
            from repositories.wealth_contribution_reconciliation_repository import (
                WealthContributionReconciliationRepository,
            )

            mark_contribution_reconciled(
                WealthContributionReconciliationRepository(wealth.client),
                user_id=str(wealth.user_id),
                portfolio_id=str(portfolio_id),
                reconciled_through=through,
                tracking_start=tracking_start,
            )
            st.success("Katkı geçmişi bu tarihe kadar doğrulandı.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))


def _render_plan_vs_actual(view: ContributionIntelligenceView) -> None:
    render_section_title(f"Plan vs gerçekleşen ({view.as_of_date.year})")
    if view.ytd_tracking_scope == ContributionTrackingScope.UNCONFIGURED:
        st.info(CONTRIBUTION_TRACKING_UNCONFIGURED_COPY)
        return
    if view.ytd_tracking_scope == ContributionTrackingScope.NOT_TRACKED:
        st.info(CONTRIBUTION_TRACKING_NOT_TRACKED_COPY)
        return
    if view.ytd_evidence_quality != ContributionEvidenceQuality.COMPLETE:
        if view.ytd_evidence_quality == ContributionEvidenceQuality.UNAVAILABLE:
            st.info(CONTRIBUTION_HISTORY_UNAVAILABLE_COPY)
        else:
            st.warning(CONTRIBUTION_HISTORY_PARTIAL_DETAIL_COPY)
        st.caption(
            f"Takip edilen YTD planı: {_money(view.planned_ytd_contribution, view.currency)}"
        )
        return
    metrics = [
        ("Takip edilen YTD planı", _money(view.planned_ytd_contribution, view.currency), None),
        (
            "Gerçekleşen net dış katkı",
            _money(view.actual_ytd_net_contribution, view.currency),
            None,
        ),
        ("Kalan", _money(view.ytd_remaining, view.currency), None),
        ("Tamamlanma", _pct(view.ytd_completion_pct), None),
    ]
    render_kpi_row(metrics)


def render_planning_fx_assumptions(
    *,
    wealth,
    portfolio_id: str,
    as_of: date,
    goal,
    plan: ContributionPlan,
    current: PlanningFxSchedule,
) -> None:
    render_section_title("Planlama Kur Varsayımları", description=PLANNING_FX_DISCLAIMER)
    st.caption("USDTRY = 1 USD için gereken TRY. Piyasa verisi değildir.")
    required = required_planning_fx_years(as_of, goal.target_date)
    completeness = current.completeness(
        as_of=as_of,
        target_date=goal.target_date,
        contribution_currency=plan.currency,
        goal_currency=goal.currency,
    )
    missing = current.missing_years(required)
    if completeness == PlanningFxCompleteness.NONE:
        st.info(PLANNING_FX_NONE_COPY)
    elif completeness == PlanningFxCompleteness.PARTIAL:
        st.warning(missing_years_copy(missing))
    elif completeness == PlanningFxCompleteness.COMPLETE:
        st.caption("Kur varsayımları tamam. 2031 değerleri planlama / projeksiyondur.")
    drafts: dict[int, str] = {}
    for year in required:
        existing = current.usdtry_for_year(year)
        drafts[year] = st.text_input(
            f"{year} USD/TRY",
            value="" if existing is None else format(existing, "f"),
            key=f"planning_fx_{portfolio_id}_{year}",
            help="Boş bırakılırsa o yıl eksik kalır. Otomatik doldurulmaz.",
        )
    if wealth is None or not str(portfolio_id or "").strip():
        return
    submitted = st.button(
        "Kur varsayımlarını kaydet",
        key=f"planning_fx_save_{portfolio_id}",
    )
    if not submitted:
        return
    parsed: dict[int, Decimal] = {}
    try:
        for year, raw in drafts.items():
            if not str(raw or "").strip():
                continue
            parsed[year] = parse_usdtry_assumption(raw)
        save_planning_fx_schedule(wealth, portfolio_id=str(portfolio_id), values=parsed)
        st.success("Planlama kur varsayımları kaydedildi.")
        st.rerun()
    except Exception as exc:
        st.error(str(exc))


def _render_what_if_and_required(
    *,
    as_of_date: date,
    current: CurrentWealthSnapshot,
    plan: ContributionPlan,
    goal,
    fx_schedule: PlanningFxSchedule,
) -> None:
    render_section_title("Ne olur, eğer?", description=USER_ASSUMPTION_NOTE)
    st.caption(
        "Gelecek TRY katkılar kaydedilmiş yıllık kur varsayımlarıyla USD'ye çevrilir; "
        "mevcut portföy değeri yeniden kurlandılmaz."
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
    target_date = right.date_input(
        "Hedef tarihi",
        value=goal.target_date,
        key="wealth_os_2031_target_date",
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
            conversion=None,
            fx_schedule=fx_schedule,
            goal=goal,
        )
    except Exception as exc:
        st.error(str(exc))
        return

    missing = fx_schedule.missing_years(required_planning_fx_years(as_of_date, target_date))
    if not what_if.projection_complete:
        if ProjectionLimitation.FX_CONVERSION_REQUIRED in what_if.limitations:
            st.warning(
                missing_years_copy(missing) if missing else PLANNING_FX_NONE_COPY
            )
        else:
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
                    "Hedef tarihi değeri (planlama)",
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
        st.caption(_status_label(what_if.status) + " · planlama / projeksiyon")

    render_section_title("Gerekli aylık katkı")
    required = solve_required_starting_monthly(
        as_of_date=as_of_date,
        current=current,
        contribution_currency=plan.currency,
        annual_increase_rate=Decimal(str(increase_pct)) / Decimal(100),
        annual_return_rate=Decimal(str(return_pct)) / Decimal(100),
        conversion=None,
        fx_schedule=fx_schedule,
        goal=goal,
    )
    if not required.available:
        if required.limitation == ProjectionLimitation.FX_CONVERSION_REQUIRED:
            st.info(missing_years_copy(missing) if missing else PLANNING_FX_NONE_COPY)
        else:
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
