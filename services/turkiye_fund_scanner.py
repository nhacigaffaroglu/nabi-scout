"""Turkish participation-fund scanner.

Discovers and ranks research candidates from official TEFAS/KAP evidence.
Does not own 8E, New Money, allocation, or Participation methodology.
Does not persist production snapshots.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Mapping, Optional, Sequence

from services.fund_intelligence_engine import evaluate_official_fund_intelligence
from services.fund_product_contract import (
    DIM_COST_EVAL,
    DIM_DIVERSIFICATION_EVAL,
    DIM_PERFORMANCE_EVAL,
    DIM_RISK_EVAL,
    MIN_READY_WEIGHT_COVERAGE,
    TURKISH_FI_PROFILES,
)
from services.official_tefas import normalize_fund_code
from services.official_tefas_product import default_tefas_fund_provider, try_mandate_from_kap
from services.official_turkiye_fund_exposure import classify_official_turkiye_fund_exposure
from services.official_turkiye_fund_participation import evaluate_turkiye_fund_participation
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)
from services.turkiye_fund_pdr_window import latest_applicable_pdr_period
from services.turkiye_fund_source_capture import (
    load_captured_kap_pdr_catalog,
    load_captured_tefas_snapshots,
)
from services.turkiye_fund_universe_contract import (
    PEER_VIEW_CATEGORY,
    PEER_VIEW_OVERALL,
    SCANNER_BLOCKED,
    SCANNER_NOT_A_BUY,
    SCANNER_NOT_EIGHT_E,
    SCANNER_NOT_NEW_MONEY,
    SCANNER_NOT_PARTICIPATION,
    SCANNER_PARTIAL,
    SCANNER_READY,
    SCANNER_REVIEW_REQUIRED,
    TEFAS_STATUS_ACTIVE,
    TurkiyeFundScannerResult,
    TurkiyeFundScannerRow,
    TurkiyeFundUniverseIdentity,
    UNIVERSE_ACTIVE,
    UNIVERSE_ANALYZABLE,
    UNIVERSE_DISCOVERED,
    UNIVERSE_PARTICIPATION_ELIGIBLE,
    UNIVERSE_SCANNABLE,
)
from services.turkiye_fund_universe_discovery import (
    discovery_category_from_official_title,
    discover_turkiye_participation_universe,
    select_representative_sample,
)

REQUIRED_FI_DIMENSIONS = {
    "LIQUIDITY_PARTICIPATION_FUND": (
        DIM_PERFORMANCE_EVAL,
        DIM_RISK_EVAL,
        DIM_COST_EVAL,
        DIM_DIVERSIFICATION_EVAL,
        "MATURITY",
    ),
    "EQUITY_PARTICIPATION_FUND": (
        DIM_PERFORMANCE_EVAL,
        "MOMENTUM",
        DIM_RISK_EVAL,
        DIM_COST_EVAL,
        DIM_DIVERSIFICATION_EVAL,
    ),
    "SUKUK_PARTICIPATION_FUND": (
        DIM_PERFORMANCE_EVAL,
        DIM_RISK_EVAL,
        DIM_COST_EVAL,
        "MATURITY",
        "ISSUER_CONCENTRATION",
    ),
    "PRECIOUS_METALS_PARTICIPATION_FUND": (
        DIM_PERFORMANCE_EVAL,
        DIM_RISK_EVAL,
        DIM_COST_EVAL,
        DIM_DIVERSIFICATION_EVAL,
    ),
}


def _as_of(value: Optional[date]) -> date:
    return value or date(2026, 8, 31)


def universe_states_for(
    identity: TurkiyeFundUniverseIdentity,
    *,
    participation_status: Optional[str],
    research_allowed: bool,
    fi_publishable: bool,
    exposure_known: bool,
    scanner_ready: bool,
) -> tuple[str, ...]:
    states = [UNIVERSE_DISCOVERED]
    if identity.tefas_status == TEFAS_STATUS_ACTIVE:
        states.append(UNIVERSE_ACTIVE)
        states.append(UNIVERSE_ANALYZABLE)
    if participation_status == PARTICIPATION_STATUS_UYGUN and research_allowed:
        states.append(UNIVERSE_PARTICIPATION_ELIGIBLE)
    if scanner_ready and fi_publishable and exposure_known:
        states.append(UNIVERSE_SCANNABLE)
    return tuple(states)


def _row_with(row: TurkiyeFundScannerRow, **changes: Any) -> TurkiyeFundScannerRow:
    payload = row.to_dict()
    payload.update(changes)
    payload["universe_states"] = tuple(payload.get("universe_states") or ())
    payload["missing_evidence"] = tuple(payload.get("missing_evidence") or ())
    return TurkiyeFundScannerRow(**payload)


def _rank_key(row: TurkiyeFundScannerRow) -> tuple:
    return (
        -(row.fi_score if row.fi_score is not None else -1.0),
        -(row.data_completeness if row.data_completeness is not None else -1.0),
        -(row.confidence if row.confidence is not None else -1.0),
        row.fund_code,
    )


def _row_status(
    *,
    active: bool,
    participation_status: Optional[str],
    research_allowed: bool,
    fi_publishable: bool,
    exposure_known: bool,
    completeness: Optional[float],
    missing: Sequence[str],
) -> str:
    if participation_status == PARTICIPATION_STATUS_UYGUN_DEGIL:
        return SCANNER_BLOCKED
    if not active:
        return SCANNER_BLOCKED
    if participation_status == PARTICIPATION_STATUS_KONTROL_ET or not research_allowed:
        return SCANNER_REVIEW_REQUIRED
    if not fi_publishable or not exposure_known:
        return SCANNER_REVIEW_REQUIRED
    if completeness is None or completeness < MIN_READY_WEIGHT_COVERAGE:
        return SCANNER_PARTIAL if missing else SCANNER_REVIEW_REQUIRED
    if missing:
        return SCANNER_PARTIAL
    return SCANNER_READY


def _evaluate_one(
    identity: TurkiyeFundUniverseIdentity,
    *,
    as_of: date,
    provider,
) -> TurkiyeFundScannerRow:
    code = identity.fund_code
    missing: list[str] = []
    active = identity.tefas_status == TEFAS_STATUS_ACTIVE
    if not active:
        missing.append("TEFAS_ACTIVE_UNPROVEN" if identity.tefas_status != "INACTIVE" else "TEFAS_INACTIVE")
    participation_status = None
    research_allowed = False
    fi_score = None
    fi_state = None
    confidence = None
    completeness = None
    publishable = False
    exposure = None
    return_1y = None
    max_drawdown = None
    profile_name = None
    reason = ""
    category = discovery_category_from_official_title(identity.fund_name)
    if not active:
        reason = "Inactive or unproven TEFAS status; fail closed from ranking."
        return TurkiyeFundScannerRow(
            fund_code=code,
            fund_name=identity.fund_name,
            category=category,
            rank=None,
            fi_score=None,
            fi_state=None,
            confidence=None,
            participation=None,
            research_allowed=False,
            exposure=None,
            return_1y=None,
            max_drawdown=None,
            data_completeness=None,
            scanner_status=SCANNER_BLOCKED,
            universe_states=universe_states_for(
                identity,
                participation_status=None,
                research_allowed=False,
                fi_publishable=False,
                exposure_known=False,
                scanner_ready=False,
            ),
            reason=reason,
            missing_evidence=tuple(missing),
            founder=identity.founder,
        )
    official_profile = None
    if provider.supports(code):
        identity_row = provider.turkiye_identity(code)
        kap = provider.kap_mandate(code)
        official_profile = kap.official_profile
        verdict = evaluate_turkiye_fund_participation(
            code,
            identity_status=identity_row.identity_status,
            official_name=identity_row.official_name,
            umbrella_type=kap.umbrella_type,
            as_of=as_of,
            official_profile=official_profile,
        )
        participation_status = verdict.participation_status
        research_allowed = bool(verdict.research_allowed)
        if verdict.blockers:
            missing.extend(verdict.blockers)
        mandate = try_mandate_from_kap(kap)
        if mandate is None:
            missing.append("FI_PROFILE_UNROUTED")
        else:
            profile_name = mandate.vehicle
            category = mandate.primary_layer or category
            pdr = None
            try:
                pdr = provider.pdr_holdings(code)
            except (FileNotFoundError, ValueError):
                pdr = None
            classification = classify_official_turkiye_fund_exposure(mandate, pdr)
            if classification is None:
                missing.append("ECONOMIC_EXPOSURE_UNKNOWN")
            else:
                exposure = classification.primary_exposure
            view = evaluate_official_fund_intelligence(code, provider=provider)
            fi_score = view.score
            fi_state = view.state
            confidence = view.confidence
            completeness = view.completeness
            publishable = bool(view.publishable)
            profile_name = view.fund_type_profile or profile_name
            performance = provider.performance(code)
            return_1y = performance.return_1y
            max_drawdown = performance.drawdown
            if not publishable:
                missing.append("FI_NOT_PUBLISHABLE")
    else:
        verdict = evaluate_turkiye_fund_participation(
            code,
            identity_status=None,
            official_name=identity.fund_name,
            umbrella_type=identity.umbrella_type,
            as_of=as_of,
        )
        participation_status = verdict.participation_status
        research_allowed = bool(verdict.research_allowed)
        missing.extend(verdict.blockers or ("KAP_YBF_MISSING", "TEFAS_HISTORY_MISSING"))
        if "GOVERNANCE_NOT_CONFIRMED" in (verdict.blockers or ()):
            missing.append("KAP_GOVERNANCE_EVIDENCE_MISSING")
        reason = "Official product evidence incomplete for canonical FI."
    completeness_ok = completeness is not None and completeness >= MIN_READY_WEIGHT_COVERAGE
    exposure_known = bool(exposure)
    scanner_status = _row_status(
        active=active,
        participation_status=participation_status,
        research_allowed=research_allowed,
        fi_publishable=publishable,
        exposure_known=exposure_known,
        completeness=completeness,
        missing=missing,
    )
    if scanner_status == SCANNER_READY:
        reason = "READY: canonical FI score; Participation is a gate, not an alpha factor."
    elif scanner_status == SCANNER_REVIEW_REQUIRED:
        reason = reason or "Review required: " + ",".join(missing[:6])
    elif scanner_status == SCANNER_PARTIAL:
        reason = "Partial official evidence; not ranked as a positive candidate."
    elif scanner_status == SCANNER_BLOCKED:
        reason = reason or "Blocked."
    _ = completeness_ok
    return TurkiyeFundScannerRow(
        fund_code=code,
        fund_name=identity.fund_name,
        category=category if exposure_known else category,
        rank=None,
        fi_score=fi_score,
        fi_state=fi_state,
        confidence=confidence,
        participation=participation_status,
        research_allowed=research_allowed,
        exposure=exposure,
        return_1y=return_1y,
        max_drawdown=max_drawdown,
        data_completeness=completeness,
        scanner_status=scanner_status,
        universe_states=universe_states_for(
            identity,
            participation_status=participation_status,
            research_allowed=research_allowed,
            fi_publishable=publishable,
            exposure_known=exposure_known,
            scanner_ready=scanner_status == SCANNER_READY,
        ),
        reason=reason,
        missing_evidence=tuple(dict.fromkeys(missing)),
        fi_profile=profile_name,
        peer_view=PEER_VIEW_CATEGORY,
        founder=identity.founder,
    )


def _assign_ranks(rows: Sequence[TurkiyeFundScannerRow]) -> tuple[TurkiyeFundScannerRow, ...]:
    ready = [row for row in rows if row.scanner_status == SCANNER_READY]
    ranked: list[TurkiyeFundScannerRow] = []
    by_category: dict[str, list[TurkiyeFundScannerRow]] = {}
    for row in ready:
        by_category.setdefault(row.category, []).append(row)
    assigned: dict[str, TurkiyeFundScannerRow] = {}
    for category, group in by_category.items():
        ordered = sorted(group, key=_rank_key)
        for index, row in enumerate(ordered, start=1):
            assigned[row.fund_code] = _row_with(row, rank=index, peer_view=PEER_VIEW_CATEGORY)
    out = []
    for row in rows:
        out.append(assigned.get(row.fund_code, row))
    return tuple(out)


def run_turkiye_fund_scanner(
    *,
    catalog_rows: Optional[Sequence[Mapping[str, Any]]] = None,
    tefas_snapshots: Optional[Mapping[str, Mapping[str, Any]]] = None,
    as_of: Optional[date] = None,
    persist: bool = False,
    sample_only: bool = True,
    extra_per_category: int = 1,
) -> TurkiyeFundScannerResult:
    if persist:
        raise ValueError("turkiye_fund_scanner_persist_refused")
    day = _as_of(as_of)
    rows = list(catalog_rows) if catalog_rows is not None else list(
        load_captured_kap_pdr_catalog().get("rows") or []
    )
    snapshots = dict(tefas_snapshots) if tefas_snapshots is not None else load_captured_tefas_snapshots()
    identities = discover_turkiye_participation_universe(rows, tefas_snapshots=snapshots)
    provider = default_tefas_fund_provider()
    include = tuple(code for code in snapshots if provider.supports(code))
    sample = select_representative_sample(
        identities,
        extra_per_category=extra_per_category,
        include_if_discovered=include,
    )
    evaluate_codes = set(sample if sample_only else (row.fund_code for row in identities))
    evaluate_codes.update(include)
    inactive_discovered = sorted(
        row.fund_code for row in identities if row.tefas_status != TEFAS_STATUS_ACTIVE
    )
    if sample_only and inactive_discovered:
        evaluate_codes.add(inactive_discovered[0])
    by_code = {row.fund_code: row for row in identities}
    evaluated: list[TurkiyeFundScannerRow] = []
    for code in sorted(evaluate_codes):
        identity = by_code.get(code)
        if identity is None:
            continue
        evaluated.append(_evaluate_one(identity, as_of=day, provider=provider))
    ranked_rows = _assign_ranks(evaluated)
    ready_rows = [row for row in ranked_rows if row.scanner_status == SCANNER_READY]
    ranked_by_category: dict[str, tuple[TurkiyeFundScannerRow, ...]] = {}
    for row in sorted(ready_rows, key=lambda item: (item.category, item.rank or 0, item.fund_code)):
        ranked_by_category.setdefault(row.category, []).append(row)
    ranked_by_category = {key: tuple(value) for key, value in ranked_by_category.items()}
    overall = tuple(
        _row_with(row, peer_view=PEER_VIEW_OVERALL, rank=index)
        for index, row in enumerate(sorted(ready_rows, key=_rank_key), start=1)
    )
    review = tuple(
        row
        for row in ranked_rows
        if row.scanner_status in {SCANNER_REVIEW_REQUIRED, SCANNER_PARTIAL, SCANNER_BLOCKED}
    )
    participation_counts = {
        PARTICIPATION_STATUS_UYGUN: 0,
        PARTICIPATION_STATUS_KONTROL_ET: 0,
        PARTICIPATION_STATUS_UYGUN_DEGIL: 0,
    }
    for row in ranked_rows:
        if row.participation in participation_counts:
            participation_counts[row.participation] += 1
    profile_counts: dict[str, int] = {}
    for row in ranked_rows:
        if row.fi_profile:
            profile_counts[row.fi_profile] = profile_counts.get(row.fi_profile, 0) + 1
    routing = tuple(
        (profile, count, REQUIRED_FI_DIMENSIONS.get(profile, ()))
        for profile, count in sorted(profile_counts.items())
        if profile in TURKISH_FI_PROFILES
    )
    _ = latest_applicable_pdr_period(day)
    return TurkiyeFundScannerResult(
        as_of=day.isoformat(),
        calculated_at=datetime.now(timezone.utc).date().isoformat(),
        discovered_count=len(identities),
        active_count=sum(1 for row in identities if row.tefas_status == TEFAS_STATUS_ACTIVE),
        analyzable_count=sum(1 for row in identities if row.tefas_status == TEFAS_STATUS_ACTIVE),
        participation_uygun_count=participation_counts[PARTICIPATION_STATUS_UYGUN],
        kontrol_et_count=participation_counts[PARTICIPATION_STATUS_KONTROL_ET],
        uygun_degil_count=participation_counts[PARTICIPATION_STATUS_UYGUN_DEGIL],
        fi_ready_count=sum(1 for row in ranked_rows if row.fi_score is not None and row.scanner_status == SCANNER_READY),
        scanner_ready_count=len(ready_rows),
        review_required_count=sum(1 for row in ranked_rows if row.scanner_status == SCANNER_REVIEW_REQUIRED),
        blocked_count=sum(1 for row in ranked_rows if row.scanner_status == SCANNER_BLOCKED),
        identities=identities,
        sample_codes=sample,
        rows=ranked_rows,
        review_queue=review,
        ranked_by_category=ranked_by_category,
        overall_shortlist=overall,
        profile_routing=routing,
        production_reads=("kap_pdr_universe_catalog", "tefas_participation_activity", "captured_tefas_kap_bundles"),
        production_writes=(),
        eight_e_calls=0,
        new_money_calls=0,
        trades=0,
        portfolio_writes=0,
        persist=False,
        limitations=(
            SCANNER_NOT_A_BUY,
            SCANNER_NOT_EIGHT_E,
            SCANNER_NOT_NEW_MONEY,
            SCANNER_NOT_PARTICIPATION,
        ),
    )


def load_default_scanner_result(*, as_of: Optional[date] = None) -> TurkiyeFundScannerResult:
    return run_turkiye_fund_scanner(as_of=as_of, persist=False, sample_only=True)
