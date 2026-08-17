from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from services.wealth_contract import (
    TXN_TYPE_BUY,
    TXN_TYPE_DEPOSIT,
    TXN_TYPE_SELL,
    TXN_TYPE_WITHDRAW,
)
from services.wealth_contribution_intelligence import (
    ContributionEvidenceQuality,
    PerformanceEvidenceQuality,
)
from services.wealth_goal_models import quantize_money
from services.wealth_performance_engine import build_performance_period
from services.wealth_portfolio_return_engine import compute_subperiod_return_for_period
from services.wealth_timeline_contract import PortfolioSnapshotView

HISTORY_STARTED_COPY = (
    "Performans geçmişi başladı. Dönemsel getiri için en az iki "
    "karşılaştırılabilir snapshot gerekiyor."
)
ATTRIBUTION_INCOMPLETE_COPY = (
    "Katkı ve performans ayrıştırması için yeterli nakit akışı / snapshot kanıtı yok."
)
WAITING_SECOND_SNAPSHOT = "2. snapshot bekleniyor"


class WealthHistoryState(str, Enum):
    ZERO = "ZERO"
    STARTED = "STARTED"
    COMPARABLE = "COMPARABLE"


class HistoryAttributionStatus(str, Enum):
    CONTRIBUTION_ONLY = "CONTRIBUTION_ONLY"
    PERFORMANCE_ONLY = "PERFORMANCE_ONLY"
    BOTH = "BOTH"
    EVIDENCE_INCOMPLETE = "EVIDENCE_INCOMPLETE"


@dataclass(frozen=True)
class WealthHistoryPoint:
    captured_at: str
    priced_market_value: float
    is_partial: bool


@dataclass(frozen=True)
class WealthHistoryView:
    snapshot_count: int
    history_state: WealthHistoryState
    period_start: Optional[str]
    period_end: Optional[str]
    start_value: Optional[Decimal]
    end_value: Optional[Decimal]
    net_external_contributions: Optional[Decimal]
    investment_gain_loss: Optional[Decimal]
    return_pct: Optional[Decimal]
    valuation_complete_start: bool
    valuation_complete_end: bool
    evidence_quality: PerformanceEvidenceQuality
    contribution_evidence_quality: ContributionEvidenceQuality
    attribution_status: HistoryAttributionStatus
    attribution_summary: str
    limitations: Tuple[str, ...]
    curve_points: Tuple[WealthHistoryPoint, ...]
    bridge_available: bool
    latest_snapshot_at: Optional[str]
    latest_value: Optional[Decimal]
    latest_is_partial: bool
    currency: str
    summary: str


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


def _snapshot_complete(snap: PortfolioSnapshotView) -> bool:
    payload = dict(snap.valuation_payload or {})
    if "valuation_complete" in payload:
        return bool(payload.get("valuation_complete"))
    return (
        snap.unpriced_position_count == 0
        and snap.priced_position_coverage_pct >= 100.0
        and not snap.mixed_currency_warning
    )


def _chronological(snapshots: Sequence[PortfolioSnapshotView]) -> List[PortfolioSnapshotView]:
    return sorted(
        snapshots,
        key=lambda row: _parse_ts(row.captured_at) or datetime.min.replace(tzinfo=timezone.utc),
    )


def _contribution_evidence(
    transactions: Sequence[Dict[str, Any]],
    *,
    account_ids: set[str],
    currency: str,
    start: datetime,
    end: datetime,
) -> ContributionEvidenceQuality:
    ccy = currency.strip().upper()
    external = 0
    lots = 0
    for row in transactions:
        if str(row.get("account_id") or "") not in account_ids:
            continue
        executed = _parse_ts(row.get("executed_at"))
        if executed is None or not (start < executed <= end):
            continue
        txn_type = str(row.get("txn_type") or "").strip().lower()
        if txn_type in {TXN_TYPE_BUY, TXN_TYPE_SELL}:
            lots += 1
        if txn_type not in {TXN_TYPE_DEPOSIT, TXN_TYPE_WITHDRAW}:
            continue
        if str(row.get("currency") or "").strip().upper() != ccy:
            continue
        external += 1
    if external > 0:
        return ContributionEvidenceQuality.COMPLETE
    if lots > 0:
        return ContributionEvidenceQuality.PARTIAL
    return ContributionEvidenceQuality.UNAVAILABLE


def _attribution(
    contrib: ContributionEvidenceQuality,
    perf: PerformanceEvidenceQuality,
    net_flow: Optional[Decimal],
    gain: Optional[Decimal],
) -> HistoryAttributionStatus:
    if (
        contrib != ContributionEvidenceQuality.COMPLETE
        or perf != PerformanceEvidenceQuality.COMPLETE
        or net_flow is None
        or gain is None
    ):
        return HistoryAttributionStatus.EVIDENCE_INCOMPLETE
    contrib_material = abs(net_flow) > Decimal("0.005")
    perf_material = abs(gain) > Decimal("0.005")
    if contrib_material and perf_material:
        return HistoryAttributionStatus.BOTH
    if contrib_material:
        return HistoryAttributionStatus.CONTRIBUTION_ONLY
    return HistoryAttributionStatus.PERFORMANCE_ONLY


def _attribution_summary(status: HistoryAttributionStatus) -> str:
    return {
        HistoryAttributionStatus.CONTRIBUTION_ONLY: (
            "Servet değişimi katkılardan kaynaklanıyor."
        ),
        HistoryAttributionStatus.PERFORMANCE_ONLY: (
            "Servet değişimi yatırım değerlemesinden kaynaklanıyor."
        ),
        HistoryAttributionStatus.BOTH: (
            "Servet değişimi hem katkı hem yatırım performansından kaynaklanıyor."
        ),
        HistoryAttributionStatus.EVIDENCE_INCOMPLETE: ATTRIBUTION_INCOMPLETE_COPY,
    }[status]


def build_wealth_history(
    snapshots: Sequence[PortfolioSnapshotView],
    *,
    transactions: Iterable[Dict[str, Any]] = (),
    account_ids: Sequence[str] = (),
    transaction_history_complete: bool = True,
) -> WealthHistoryView:
    ordered = _chronological(snapshots)
    txn_list = list(transactions)
    ids = {str(item) for item in account_ids if str(item or "").strip()}
    points = tuple(
        WealthHistoryPoint(
            captured_at=row.captured_at,
            priced_market_value=float(row.priced_market_value),
            is_partial=not _snapshot_complete(row),
        )
        for row in ordered
    )
    currency = ordered[-1].base_currency if ordered else "USD"
    latest = ordered[-1] if ordered else None

    if not ordered:
        return WealthHistoryView(
            snapshot_count=0,
            history_state=WealthHistoryState.ZERO,
            period_start=None,
            period_end=None,
            start_value=None,
            end_value=None,
            net_external_contributions=None,
            investment_gain_loss=None,
            return_pct=None,
            valuation_complete_start=False,
            valuation_complete_end=False,
            evidence_quality=PerformanceEvidenceQuality.UNAVAILABLE,
            contribution_evidence_quality=ContributionEvidenceQuality.UNAVAILABLE,
            attribution_status=HistoryAttributionStatus.EVIDENCE_INCOMPLETE,
            attribution_summary=ATTRIBUTION_INCOMPLETE_COPY,
            limitations=("NO_SNAPSHOTS",),
            curve_points=(),
            bridge_available=False,
            latest_snapshot_at=None,
            latest_value=None,
            latest_is_partial=False,
            currency=currency,
            summary="Henüz snapshot yok.",
        )

    if len(ordered) == 1:
        value = quantize_money(Decimal(str(latest.priced_market_value)))
        partial = not _snapshot_complete(latest)
        return WealthHistoryView(
            snapshot_count=1,
            history_state=WealthHistoryState.STARTED,
            period_start=None,
            period_end=None,
            start_value=None,
            end_value=value,
            net_external_contributions=None,
            investment_gain_loss=None,
            return_pct=None,
            valuation_complete_start=False,
            valuation_complete_end=not partial,
            evidence_quality=PerformanceEvidenceQuality.UNAVAILABLE,
            contribution_evidence_quality=ContributionEvidenceQuality.UNAVAILABLE,
            attribution_status=HistoryAttributionStatus.EVIDENCE_INCOMPLETE,
            attribution_summary=ATTRIBUTION_INCOMPLETE_COPY,
            limitations=("SECOND_SNAPSHOT_REQUIRED",)
            + (("PARTIAL_VALUATION",) if partial else ()),
            curve_points=points,
            bridge_available=False,
            latest_snapshot_at=latest.captured_at,
            latest_value=value,
            latest_is_partial=partial,
            currency=currency,
            summary=HISTORY_STARTED_COPY,
        )

    start, end = ordered[0], ordered[-1]
    start_at = _parse_ts(start.captured_at)
    end_at = _parse_ts(end.captured_at)
    contrib = (
        _contribution_evidence(
            txn_list,
            account_ids=ids,
            currency=start.base_currency,
            start=start_at,
            end=end_at,
        )
        if start_at and end_at and ids
        else ContributionEvidenceQuality.UNAVAILABLE
    )
    period = build_performance_period(
        start=start,
        end=end,
        transactions=txn_list,
        account_ids=ids,
        transaction_history_complete=transaction_history_complete,
    )
    start_value = quantize_money(Decimal(str(period.start_priced_value)))
    end_value = quantize_money(Decimal(str(period.end_priced_value)))
    complete_start = _snapshot_complete(start)
    complete_end = _snapshot_complete(end)

    if not period.performance_comparable:
        return WealthHistoryView(
            snapshot_count=len(ordered),
            history_state=WealthHistoryState.STARTED,
            period_start=start.captured_at,
            period_end=end.captured_at,
            start_value=start_value,
            end_value=end_value,
            net_external_contributions=None,
            investment_gain_loss=None,
            return_pct=None,
            valuation_complete_start=complete_start,
            valuation_complete_end=complete_end,
            evidence_quality=PerformanceEvidenceQuality.PARTIAL,
            contribution_evidence_quality=contrib,
            attribution_status=HistoryAttributionStatus.EVIDENCE_INCOMPLETE,
            attribution_summary=ATTRIBUTION_INCOMPLETE_COPY,
            limitations=tuple(period.warnings) or ("PERFORMANCE_NOT_COMPARABLE",),
            curve_points=points,
            bridge_available=False,
            latest_snapshot_at=end.captured_at,
            latest_value=end_value,
            latest_is_partial=not complete_end,
            currency=period.base_currency,
            summary=HISTORY_STARTED_COPY,
        )

    net_flow = quantize_money(Decimal(str(period.net_external_flow)))
    gain = quantize_money(Decimal(str(period.investment_gain)))
    raw_return = compute_subperiod_return_for_period(
        period,
        transactions=txn_list,
        account_ids=ids,
    )
    return_pct = (
        None
        if raw_return is None
        else quantize_money(Decimal(str(raw_return)) * Decimal("100"))
    )
    if contrib != ContributionEvidenceQuality.COMPLETE:
        net_shown = None
        gain_shown = None
        bridge = False
        perf_evidence = PerformanceEvidenceQuality.PARTIAL
        limitations = ("CONTRIBUTION_EVIDENCE_INCOMPLETE",) + tuple(period.warnings)
    else:
        net_shown = net_flow
        gain_shown = gain
        bridge = True
        perf_evidence = PerformanceEvidenceQuality.COMPLETE
        limitations = tuple(period.warnings)

    attribution = _attribution(contrib, perf_evidence, net_shown, gain_shown)
    return WealthHistoryView(
        snapshot_count=len(ordered),
        history_state=WealthHistoryState.COMPARABLE,
        period_start=start.captured_at,
        period_end=end.captured_at,
        start_value=start_value,
        end_value=end_value,
        net_external_contributions=net_shown,
        investment_gain_loss=gain_shown,
        return_pct=return_pct if contrib == ContributionEvidenceQuality.COMPLETE else None,
        valuation_complete_start=complete_start,
        valuation_complete_end=complete_end,
        evidence_quality=perf_evidence,
        contribution_evidence_quality=contrib,
        attribution_status=attribution,
        attribution_summary=_attribution_summary(attribution),
        limitations=limitations,
        curve_points=points,
        bridge_available=bridge,
        latest_snapshot_at=end.captured_at,
        latest_value=end_value,
        latest_is_partial=not complete_end,
        currency=period.base_currency,
        summary=_attribution_summary(attribution),
    )
