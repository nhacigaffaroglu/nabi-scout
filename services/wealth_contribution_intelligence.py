from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

from services.wealth_goal_models import (
    ContributionPlan,
    ConversionAssumption,
    CurrentWealthSnapshot,
    GoalEvidenceStatus,
    ProjectionLimitation,
    ReturnScenario,
    WealthGoal,
    default_contribution_plan,
    default_wealth_goal_2031,
    quantize_money,
)
from services.wealth_goal_planning import (
    monthly_for_year,
    solve_required_starting_monthly,
)
from services.wealth_external_cash_flow import (
    CONTRIBUTION_TRACKING_MID_PERIOD_COPY,
    CONTRIBUTION_TRACKING_NOT_TRACKED_COPY,
    CONTRIBUTION_TRACKING_UNCONFIGURED_COPY,
    ContributionReconciliation,
    ContributionTrackingScope,
    contribution_period_evidence,
    period_starts_mid_tracking_month,
    resolve_tracked_window,
    tracked_ytd_month_count,
)
from services.wealth_performance_engine import (
    aggregate_cash_flows,
    build_performance_period,
)
from services.wealth_portfolio_return_engine import compute_subperiod_return_for_period
from services.wealth_projection_engine import project_wealth_goal
from services.wealth_timeline_contract import PortfolioSnapshotView

BASE_RETURN_RATE = Decimal("0.08")
PLANNING_BENCHMARK_LABEL = "8% yıllık getiri varsayımına dayalı planlama yolu"
PERFORMANCE_UNAVAILABLE_COPY = (
    "Performans ayrıştırması için yeterli dönem başlangıcı / nakit akışı kanıtı yok."
)
CONTRIBUTION_HISTORY_UNAVAILABLE_COPY = "Katkı geçmişi henüz mevcut değil."
CONTRIBUTION_HISTORY_PARTIAL_COPY = "Katkı kayıtları henüz doğrulanmadı."
CONTRIBUTION_HISTORY_PARTIAL_DETAIL_COPY = (
    "Katkı geçmişi kısmi — gerçekleşen tutar doğrulama sonrası hesaplanacak."
)
CONTRIBUTION_RECONCILE_ACTION_LABEL = "Bu tarihe kadar tüm katkı hareketlerim kayıtlı"


class ContributionEvidenceQuality(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"


class PlanAdequacyStatus(str, Enum):
    SUFFICIENT = "SUFFICIENT"
    BELOW_REQUIRED = "BELOW_REQUIRED"
    ABOVE_REQUIRED = "ABOVE_REQUIRED"
    INDETERMINATE = "INDETERMINATE"


class MonthlyActionStatus(str, Enum):
    ON_PLAN = "ON_PLAN"
    CONTRIBUTION_DUE = "CONTRIBUTION_DUE"
    AHEAD = "AHEAD"
    EVIDENCE_INCOMPLETE = "EVIDENCE_INCOMPLETE"
    PLAN_INDETERMINATE = "PLAN_INDETERMINATE"


class PerformanceEvidenceQuality(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"


class PlanAttributionStatus(str, Enum):
    CONTRIBUTION_GAP = "CONTRIBUTION_GAP"
    PERFORMANCE_GAP = "PERFORMANCE_GAP"
    BOTH = "BOTH"
    ON_TRACK = "ON_TRACK"
    AHEAD = "AHEAD"
    EVIDENCE_INCOMPLETE = "EVIDENCE_INCOMPLETE"
    PLAN_INDETERMINATE = "PLAN_INDETERMINATE"


@dataclass(frozen=True)
class ContributionIntelligenceView:
    as_of_date: date
    currency: str
    planned_monthly_contribution: Decimal
    actual_monthly_net_contribution: Optional[Decimal]
    monthly_remaining: Optional[Decimal]
    monthly_surplus: Optional[Decimal]
    monthly_completion_pct: Optional[Decimal]
    planned_ytd_contribution: Decimal
    actual_ytd_net_contribution: Optional[Decimal]
    ytd_remaining: Optional[Decimal]
    ytd_surplus: Optional[Decimal]
    ytd_completion_pct: Optional[Decimal]
    planned_full_year_contribution: Decimal
    required_starting_monthly_contribution: Optional[Decimal]
    plan_vs_required_difference: Optional[Decimal]
    plan_adequacy_status: PlanAdequacyStatus
    evidence_quality: ContributionEvidenceQuality
    monthly_evidence_quality: ContributionEvidenceQuality
    ytd_evidence_quality: ContributionEvidenceQuality
    monthly_action_status: MonthlyActionStatus
    monthly_action_summary: str
    adequacy_summary: str
    limitations: Tuple[str, ...]
    performance_evidence_quality: PerformanceEvidenceQuality
    period_start_value: Optional[Decimal]
    period_end_value: Optional[Decimal]
    net_external_contributions: Optional[Decimal]
    investment_gain_loss: Optional[Decimal]
    investment_return_pct: Optional[Decimal]
    planning_path_value: Optional[Decimal]
    planning_benchmark_available: bool
    planning_benchmark_label: str
    attribution_status: PlanAttributionStatus
    attribution_summary: str
    data_confidence_summary: str
    performance_limitations: Tuple[str, ...]
    contribution_tracking_start: Optional[date] = None
    monthly_tracking_scope: ContributionTrackingScope = ContributionTrackingScope.UNCONFIGURED
    ytd_tracking_scope: ContributionTrackingScope = ContributionTrackingScope.UNCONFIGURED
    monthly_tracking_note: Optional[str] = None


def _parse_ts(value: Any) -> Optional[datetime]:
    text = str(value or "").replace("Z", "+00:00")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _month_window(as_of: date) -> Tuple[datetime, datetime]:
    start = datetime(as_of.year, as_of.month, 1, tzinfo=timezone.utc) - timedelta(
        microseconds=1
    )
    end = datetime.combine(as_of, time(23, 59, 59), tzinfo=timezone.utc)
    return start, end


def _year_window(as_of: date) -> Tuple[datetime, datetime]:
    start = datetime(as_of.year, 1, 1, tzinfo=timezone.utc) - timedelta(microseconds=1)
    end = datetime.combine(as_of, time(23, 59, 59), tzinfo=timezone.utc)
    return start, end


def _in_window(executed_at: datetime, start: datetime, end: datetime) -> bool:
    return start < executed_at <= end


def _evidence_quality(
    transactions: Sequence[Dict[str, Any]],
    *,
    account_ids: set[str],
    plan_currency: str,
    start: datetime,
    end: datetime,
    reconciliations: Sequence[ContributionReconciliation] | None = None,
    portfolio_id: Optional[str] = None,
) -> ContributionEvidenceQuality:
    return ContributionEvidenceQuality(
        contribution_period_evidence(
            transactions,
            account_ids=account_ids,
            plan_currency=plan_currency,
            start=start,
            end=end,
            reconciliations=reconciliations,
            portfolio_id=portfolio_id,
        )
    )


def _gap_and_surplus(
    planned: Decimal,
    actual: Optional[Decimal],
) -> Tuple[Optional[Decimal], Optional[Decimal], Optional[Decimal]]:
    if actual is None:
        return None, None, None
    remaining = quantize_money(max(Decimal(0), planned - actual))
    surplus = quantize_money(max(Decimal(0), actual - planned))
    completion = (
        quantize_money((actual / planned) * Decimal(100)) if planned > 0 else None
    )
    return remaining, surplus, completion


def _actual_net(
    *,
    evidence: ContributionEvidenceQuality,
    inflows: float,
    outflows: float,
) -> Optional[Decimal]:
    if evidence != ContributionEvidenceQuality.COMPLETE:
        return None
    return quantize_money(Decimal(str(inflows - outflows)))


def _monthly_action(
    evidence: ContributionEvidenceQuality,
    remaining: Optional[Decimal],
    surplus: Optional[Decimal],
) -> MonthlyActionStatus:
    if evidence != ContributionEvidenceQuality.COMPLETE:
        return MonthlyActionStatus.EVIDENCE_INCOMPLETE
    if remaining is None or surplus is None:
        return MonthlyActionStatus.PLAN_INDETERMINATE
    if remaining > 0:
        return MonthlyActionStatus.CONTRIBUTION_DUE
    if surplus > 0:
        return MonthlyActionStatus.AHEAD
    return MonthlyActionStatus.ON_PLAN


def _monthly_summary(
    status: MonthlyActionStatus,
    *,
    remaining: Optional[Decimal],
    currency: str,
) -> str:
    if status == MonthlyActionStatus.EVIDENCE_INCOMPLETE:
        return (
            "Bu ay için güvenilir katkı geçmişi eksik; kalan tutar kesin hesaplanamıyor."
        )
    if status == MonthlyActionStatus.CONTRIBUTION_DUE and remaining is not None:
        return (
            f"Bu ay planı tamamlamak için {remaining:,.2f} {currency} katkı gerekiyor."
        )
    if status in {MonthlyActionStatus.ON_PLAN, MonthlyActionStatus.AHEAD}:
        return "Bu ayki katkı planı karşılandı."
    return "Bu ay katkı planı belirlenemedi."


def _adequacy_status(
    *,
    current: CurrentWealthSnapshot,
    planned_monthly: Decimal,
    required: Optional[Decimal],
    projection_status: Optional[GoalEvidenceStatus],
    projection_complete: bool,
) -> PlanAdequacyStatus:
    if not projection_complete or required is None:
        return PlanAdequacyStatus.INDETERMINATE
    if projection_status in {
        GoalEvidenceStatus.REACHED,
        GoalEvidenceStatus.PROJECTED_TO_REACH,
    }:
        if planned_monthly > required:
            return PlanAdequacyStatus.ABOVE_REQUIRED
        return PlanAdequacyStatus.SUFFICIENT
    if not current.valuation_complete:
        return PlanAdequacyStatus.INDETERMINATE
    if planned_monthly < required:
        return PlanAdequacyStatus.BELOW_REQUIRED
    if planned_monthly > required:
        return PlanAdequacyStatus.ABOVE_REQUIRED
    return PlanAdequacyStatus.SUFFICIENT


def _adequacy_summary(
    status: PlanAdequacyStatus,
    *,
    fx_missing: bool,
) -> str:
    if fx_missing or status == PlanAdequacyStatus.INDETERMINATE:
        return (
            "2031 için gereken katkı karşılaştırması USDTRY planlama varsayımı "
            "olmadan hesaplanamıyor."
            if fx_missing
            else "2031 plan yeterliliği mevcut kanıtla belirlenemiyor."
        )
    if status == PlanAdequacyStatus.BELOW_REQUIRED:
        return "Mevcut katkı planı, Base varsayımıyla gereken aylık katkının altında."
    if status == PlanAdequacyStatus.ABOVE_REQUIRED:
        return "Mevcut katkı planı, Base varsayımıyla gereken aylık katkının üzerinde."
    return "Mevcut katkı planı, Base varsayımıyla hedef için yeterli görünüyor."


def planning_end_snapshot(
    *,
    as_of: date,
    current: CurrentWealthSnapshot,
) -> PortfolioSnapshotView:
    """Ephemeral as-of valuation point. Not persisted and not a historical start."""
    complete = bool(current.valuation_complete)
    unpriced = 0 if complete else max(1, len(current.unvalued_symbols))
    captured = datetime.combine(as_of, time(23, 59, 59), tzinfo=timezone.utc).isoformat()
    value = float(current.current_value_lower_bound)
    return PortfolioSnapshotView(
        id="planning-end",
        user_id="planning",
        portfolio_id="planning",
        captured_at=captured,
        base_currency=current.currency,
        priced_market_value=value,
        total_cost_basis=0.0,
        unrealized_pl=0.0,
        cash_value=0.0,
        invested_value=value,
        liabilities_total=None,
        net_wealth_partial=None,
        priced_position_coverage_pct=100.0 if complete else 0.0,
        unpriced_position_count=unpriced,
        mixed_currency_warning=False,
        valuation_payload={},
        created_at=captured,
    )


def select_period_start_snapshot(
    snapshots: Sequence[PortfolioSnapshotView],
    *,
    as_of: date,
) -> Optional[PortfolioSnapshotView]:
    """Use a real snapshot on or before 1 Jan of as_of.year. Do not invent one."""
    year_start = date(as_of.year, 1, 1)
    eligible: list[Tuple[datetime, PortfolioSnapshotView]] = []
    for snap in snapshots:
        captured = _parse_ts(snap.captured_at)
        if captured is None:
            continue
        captured_date = captured.date()
        if captured_date > as_of or captured_date > year_start:
            continue
        eligible.append((captured, snap))
    if not eligible:
        return None
    eligible.sort(key=lambda item: item[0])
    return eligible[-1][1]


def _snapshot_start_complete(start: PortfolioSnapshotView) -> bool:
    return (
        start.unpriced_position_count == 0
        and start.priced_position_coverage_pct >= 100.0
        and not start.mixed_currency_warning
    )


def _planning_path_value(
    *,
    start: PortfolioSnapshotView,
    as_of: date,
    plan: ContributionPlan,
    goal: WealthGoal,
    conversion: Optional[ConversionAssumption],
    annual_return_rate: Decimal,
) -> Optional[Decimal]:
    if not _snapshot_start_complete(start):
        return None
    start_at = _parse_ts(start.captured_at)
    if start_at is None:
        return None
    start_date = start_at.date()
    if start_date >= as_of:
        return None
    start_ccy = str(start.base_currency or "").strip().upper()
    goal_ccy = goal.currency.strip().upper()
    if start_ccy != goal_ccy:
        return None
    if plan.currency.strip().upper() != goal_ccy and conversion is None:
        return None
    start_value = quantize_money(Decimal(str(start.priced_market_value)))
    start_wealth = CurrentWealthSnapshot(
        currency=start_ccy,
        current_value_lower_bound=start_value,
        valuation_complete=True,
        unvalued_symbols=(),
    )
    path_goal = WealthGoal(
        name="planning-benchmark",
        target_amount=max(goal.target_amount, start_value) * Decimal("10") + Decimal("1"),
        target_date=as_of,
        currency=goal_ccy,
    )
    result = project_wealth_goal(
        goal=path_goal,
        as_of_date=start_date,
        current=start_wealth,
        contribution_plan=plan,
        scenario=ReturnScenario("Base", annual_return_rate),
        conversion=conversion,
    )
    if not result.projection_complete or result.projected_target_date_value is None:
        return None
    return result.projected_target_date_value


def _performance_view(
    *,
    start: Optional[PortfolioSnapshotView],
    end: Optional[PortfolioSnapshotView],
    transactions: Sequence[Dict[str, Any]],
    account_ids: set[str],
    history_complete: bool,
) -> Tuple[
    PerformanceEvidenceQuality,
    Optional[Decimal],
    Optional[Decimal],
    Optional[Decimal],
    Optional[Decimal],
    Optional[Decimal],
    Tuple[str, ...],
]:
    if start is None or end is None:
        return (
            PerformanceEvidenceQuality.UNAVAILABLE,
            None,
            None,
            None,
            None,
            None,
            ("NO_PERIOD_START_SNAPSHOT",),
        )
    period = build_performance_period(
        start=start,
        end=end,
        transactions=transactions,
        account_ids=account_ids,
        transaction_history_complete=history_complete,
    )
    start_value = quantize_money(Decimal(str(period.start_priced_value)))
    end_value = quantize_money(Decimal(str(period.end_priced_value)))
    if not period.performance_comparable:
        return (
            PerformanceEvidenceQuality.PARTIAL,
            start_value,
            end_value,
            None,
            None,
            None,
            tuple(period.warnings) or ("PERFORMANCE_NOT_COMPARABLE",),
        )
    gain = quantize_money(Decimal(str(period.investment_gain)))
    net_flow = quantize_money(Decimal(str(period.net_external_flow)))
    raw_return = compute_subperiod_return_for_period(
        period,
        transactions=transactions,
        account_ids=account_ids,
    )
    return_pct = (
        None
        if raw_return is None
        else quantize_money(Decimal(str(raw_return)) * Decimal("100"))
    )
    return (
        PerformanceEvidenceQuality.COMPLETE,
        start_value,
        end_value,
        net_flow,
        gain,
        return_pct,
        tuple(period.warnings),
    )


def _attribution(
    *,
    ytd_evidence: ContributionEvidenceQuality,
    ytd_remaining: Optional[Decimal],
    ytd_surplus: Optional[Decimal],
    perf_evidence: PerformanceEvidenceQuality,
    planning_benchmark_available: bool,
    period_end_value: Optional[Decimal],
    planning_path_value: Optional[Decimal],
    fx_missing: bool,
    already_reached: bool,
) -> PlanAttributionStatus:
    if already_reached:
        return PlanAttributionStatus.AHEAD
    contrib_ok = ytd_evidence == ContributionEvidenceQuality.COMPLETE
    perf_ok = perf_evidence == PerformanceEvidenceQuality.COMPLETE
    contrib_short = contrib_ok and ytd_remaining is not None and ytd_remaining > 0
    contrib_ahead = contrib_ok and ytd_surplus is not None and ytd_surplus > 0
    contrib_on = contrib_ok and not contrib_short and not contrib_ahead
    perf_below = False
    perf_above = False
    if (
        perf_ok
        and planning_benchmark_available
        and period_end_value is not None
        and planning_path_value is not None
    ):
        if period_end_value + Decimal("1.00") < planning_path_value:
            perf_below = True
        elif period_end_value > planning_path_value + Decimal("1.00"):
            perf_above = True
    if contrib_short and perf_below:
        return PlanAttributionStatus.BOTH
    if contrib_short:
        return PlanAttributionStatus.CONTRIBUTION_GAP
    if contrib_on and perf_below:
        return PlanAttributionStatus.PERFORMANCE_GAP
    if (contrib_ahead and not perf_below) or (contrib_on and perf_above):
        return PlanAttributionStatus.AHEAD
    if contrib_on and fx_missing and not perf_ok:
        return PlanAttributionStatus.PLAN_INDETERMINATE
    if contrib_on and not perf_below:
        return PlanAttributionStatus.ON_TRACK
    if not contrib_ok and perf_below:
        return PlanAttributionStatus.PERFORMANCE_GAP
    if not contrib_ok and perf_above:
        return PlanAttributionStatus.AHEAD
    if not contrib_ok and not perf_ok:
        return PlanAttributionStatus.EVIDENCE_INCOMPLETE
    if fx_missing:
        return PlanAttributionStatus.PLAN_INDETERMINATE
    return PlanAttributionStatus.EVIDENCE_INCOMPLETE


def _attribution_summary(status: PlanAttributionStatus) -> str:
    return {
        PlanAttributionStatus.CONTRIBUTION_GAP: (
            "Sapma katkından kaynaklanıyor; performans bu sonucu kanıtlamıyor."
        ),
        PlanAttributionStatus.PERFORMANCE_GAP: (
            "Katkı planı tutuluyor; ölçülebilen yatırım performansı planlama yolunun altında."
        ),
        PlanAttributionStatus.BOTH: (
            "Hem katkı hem ölçülebilen performans planın altında."
        ),
        PlanAttributionStatus.ON_TRACK: "Mevcut kanıtla katkı planı yolunda.",
        PlanAttributionStatus.AHEAD: "Mevcut kanıtla planın üzerinde.",
        PlanAttributionStatus.EVIDENCE_INCOMPLETE: (
            "Katkı veya dönem performansı için kanıt yetersiz; sapma nedeni kesinleştirilemiyor."
        ),
        PlanAttributionStatus.PLAN_INDETERMINATE: (
            "2031 plan karşılaştırması mevcut kur/değerleme kanıtıyla belirlenemiyor."
        ),
    }[status]


def _data_confidence(
    *,
    contrib: ContributionEvidenceQuality,
    perf: PerformanceEvidenceQuality,
    valuation_complete: bool,
    fx_missing: bool,
) -> str:
    parts = [
        f"Katkı kanıtı: {contrib.value}",
        f"Performans kanıtı: {perf.value}",
        "Değerleme: tam" if valuation_complete else "Değerleme: kısmi (BIST fiyatı yok)",
        "USDTRY planlama varsayımı yok" if fx_missing else "USDTRY planlama varsayımı var",
    ]
    return " · ".join(parts)


def build_contribution_intelligence(
    *,
    as_of_date: date,
    current: CurrentWealthSnapshot,
    transactions: Iterable[Dict[str, Any]],
    account_ids: Sequence[str],
    plan: Optional[ContributionPlan] = None,
    goal: Optional[WealthGoal] = None,
    conversion: Optional[ConversionAssumption] = None,
    annual_return_rate: Decimal = BASE_RETURN_RATE,
    start_snapshot: Optional[PortfolioSnapshotView] = None,
    end_snapshot: Optional[PortfolioSnapshotView] = None,
    transaction_history_complete: bool = True,
    contribution_reconciliations: Sequence[ContributionReconciliation] | None = None,
    portfolio_id: Optional[str] = None,
    contribution_tracking_start: Optional[date] = None,
    fx_schedule=None,
) -> ContributionIntelligenceView:
    plan = plan or default_contribution_plan()
    goal = goal or default_wealth_goal_2031()
    plan.validate()
    goal.validate()
    txn_list = list(transactions)
    ids = {str(item) for item in account_ids if str(item or "").strip()}
    monthly = monthly_for_year(plan, as_of=as_of_date, year=as_of_date.year)
    month_start, month_end = _month_window(as_of_date)
    year_start, year_end = _year_window(as_of_date)
    monthly_scope, month_flow_start, month_flow_end = resolve_tracked_window(
        month_start, month_end, contribution_tracking_start
    )
    ytd_scope, year_flow_start, year_flow_end = resolve_tracked_window(
        year_start, year_end, contribution_tracking_start
    )
    if contribution_tracking_start is None:
        months_elapsed = 0
        planned_ytd = quantize_money(Decimal("0"))
    else:
        months_elapsed = tracked_ytd_month_count(as_of_date, contribution_tracking_start)
        planned_ytd = quantize_money(monthly * Decimal(months_elapsed))
    planned_year = quantize_money(monthly * Decimal(12))
    monthly_note = None
    if (
        contribution_tracking_start is not None
        and monthly_scope == ContributionTrackingScope.TRACKED
        and period_starts_mid_tracking_month(as_of_date, contribution_tracking_start)
    ):
        monthly_note = CONTRIBUTION_TRACKING_MID_PERIOD_COPY

    def _scoped_evidence(scope, start, end) -> ContributionEvidenceQuality:
        if scope != ContributionTrackingScope.TRACKED or not ids or start is None or end is None:
            return ContributionEvidenceQuality.UNAVAILABLE
        return _evidence_quality(
            txn_list,
            account_ids=ids,
            plan_currency=plan.currency,
            start=start,
            end=end,
            reconciliations=contribution_reconciliations,
            portfolio_id=portfolio_id,
        )

    monthly_evidence = _scoped_evidence(monthly_scope, month_flow_start, month_flow_end)
    ytd_evidence = _scoped_evidence(ytd_scope, year_flow_start, year_flow_end)
    overall = (
        ContributionEvidenceQuality.UNAVAILABLE
        if ytd_scope != ContributionTrackingScope.TRACKED
        else ytd_evidence
    )

    def _scoped_flows(scope, start, end):
        if scope != ContributionTrackingScope.TRACKED or not ids or start is None or end is None:
            return 0.0, 0.0, 0.0, 0.0, []
        return aggregate_cash_flows(
            txn_list,
            account_ids=ids,
            base_currency=plan.currency,
            period_start=start,
            period_end=end,
        )

    month_in, month_out, _d, _f, _w = _scoped_flows(
        monthly_scope, month_flow_start, month_flow_end
    )
    year_in, year_out, _d2, _f2, _w2 = _scoped_flows(
        ytd_scope, year_flow_start, year_flow_end
    )
    actual_month = _actual_net(
        evidence=monthly_evidence, inflows=month_in, outflows=month_out
    )
    actual_ytd = _actual_net(evidence=ytd_evidence, inflows=year_in, outflows=year_out)
    month_remaining, month_surplus, month_pct = _gap_and_surplus(monthly, actual_month)
    ytd_remaining, ytd_surplus, ytd_pct = _gap_and_surplus(planned_ytd, actual_ytd)

    required = solve_required_starting_monthly(
        as_of_date=as_of_date,
        current=current,
        contribution_currency=plan.currency,
        annual_increase_rate=plan.annual_increase_rate,
        annual_return_rate=annual_return_rate,
        conversion=conversion,
        fx_schedule=fx_schedule,
        goal=goal,
    )
    projection = project_wealth_goal(
        goal=goal,
        as_of_date=as_of_date,
        current=current,
        contribution_plan=plan,
        scenario=ReturnScenario("Base", annual_return_rate),
        conversion=conversion,
        fx_schedule=fx_schedule,
    )
    fx_missing = (
        plan.currency.strip().upper() != goal.currency.strip().upper()
        and conversion is None
        and (
            fx_schedule is None
            or not fx_schedule.is_complete(
                as_of=as_of_date,
                target_date=goal.target_date,
                contribution_currency=plan.currency,
                goal_currency=goal.currency,
            )
        )
    )
    adequacy = _adequacy_status(
        current=current,
        planned_monthly=monthly,
        required=required.starting_monthly if required.available else None,
        projection_status=projection.status,
        projection_complete=projection.projection_complete,
    )
    plan_vs_required = None
    if required.available and required.starting_monthly is not None:
        plan_vs_required = quantize_money(monthly - required.starting_monthly)

    action = _monthly_action(monthly_evidence, month_remaining, month_surplus)
    limitations: list[str] = []
    if monthly_scope != ContributionTrackingScope.TRACKED:
        limitations.append("CONTRIBUTION_PERIOD_NOT_TRACKED")
    if ytd_scope != ContributionTrackingScope.TRACKED:
        limitations.append("CONTRIBUTION_YTD_NOT_TRACKED")
    if monthly_evidence != ContributionEvidenceQuality.COMPLETE:
        limitations.append("MONTHLY_EVIDENCE_INCOMPLETE")
    if ytd_evidence != ContributionEvidenceQuality.COMPLETE:
        limitations.append("YTD_EVIDENCE_INCOMPLETE")
    if fx_missing:
        limitations.append(ProjectionLimitation.FX_CONVERSION_REQUIRED.value)
    if not current.valuation_complete:
        limitations.append(ProjectionLimitation.PARTIAL_VALUATION.value)

    end_snap = end_snapshot or (
        planning_end_snapshot(as_of=as_of_date, current=current)
        if start_snapshot is not None
        else None
    )
    (
        perf_evidence,
        period_start_value,
        period_end_value,
        period_net_flow,
        investment_gain,
        investment_return_pct,
        perf_limits,
    ) = _performance_view(
        start=start_snapshot,
        end=end_snap,
        transactions=txn_list,
        account_ids=ids,
        history_complete=transaction_history_complete,
    )
    planning_path = None
    if start_snapshot is not None and perf_evidence == PerformanceEvidenceQuality.COMPLETE:
        planning_path = _planning_path_value(
            start=start_snapshot,
            as_of=as_of_date,
            plan=plan,
            goal=goal,
            conversion=conversion,
            annual_return_rate=annual_return_rate,
        )
    benchmark_available = planning_path is not None
    attribution = _attribution(
        ytd_evidence=ytd_evidence,
        ytd_remaining=ytd_remaining,
        ytd_surplus=ytd_surplus,
        perf_evidence=perf_evidence,
        planning_benchmark_available=benchmark_available,
        period_end_value=period_end_value,
        planning_path_value=planning_path,
        fx_missing=fx_missing,
        already_reached=projection.status == GoalEvidenceStatus.REACHED,
    )
    if perf_evidence != PerformanceEvidenceQuality.COMPLETE:
        limitations.append("PERFORMANCE_EVIDENCE_INCOMPLETE")

    return ContributionIntelligenceView(
        as_of_date=as_of_date,
        currency=plan.currency,
        planned_monthly_contribution=monthly,
        actual_monthly_net_contribution=actual_month,
        monthly_remaining=month_remaining,
        monthly_surplus=month_surplus,
        monthly_completion_pct=month_pct,
        planned_ytd_contribution=planned_ytd,
        actual_ytd_net_contribution=actual_ytd,
        ytd_remaining=ytd_remaining,
        ytd_surplus=ytd_surplus,
        ytd_completion_pct=ytd_pct,
        planned_full_year_contribution=planned_year,
        required_starting_monthly_contribution=(
            required.starting_monthly if required.available else None
        ),
        plan_vs_required_difference=plan_vs_required,
        plan_adequacy_status=adequacy,
        evidence_quality=overall,
        monthly_evidence_quality=monthly_evidence,
        ytd_evidence_quality=ytd_evidence,
        monthly_action_status=action,
        monthly_action_summary=_monthly_summary(
            action, remaining=month_remaining, currency=plan.currency
        ),
        adequacy_summary=_adequacy_summary(adequacy, fx_missing=fx_missing),
        limitations=tuple(limitations),
        performance_evidence_quality=perf_evidence,
        period_start_value=period_start_value,
        period_end_value=period_end_value,
        net_external_contributions=period_net_flow,
        investment_gain_loss=investment_gain,
        investment_return_pct=investment_return_pct,
        planning_path_value=planning_path,
        planning_benchmark_available=benchmark_available,
        planning_benchmark_label=PLANNING_BENCHMARK_LABEL,
        attribution_status=attribution,
        attribution_summary=_attribution_summary(attribution),
        data_confidence_summary=_data_confidence(
            contrib=overall,
            perf=perf_evidence,
            valuation_complete=current.valuation_complete,
            fx_missing=fx_missing,
        ),
        performance_limitations=perf_limits,
        contribution_tracking_start=contribution_tracking_start,
        monthly_tracking_scope=monthly_scope,
        ytd_tracking_scope=ytd_scope,
        monthly_tracking_note=monthly_note,
    )
