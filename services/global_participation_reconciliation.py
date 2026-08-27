from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from typing import Any, Mapping, Optional, Sequence

from repositories.sec_company_facts_cache import SecCompanyFactsCache
from services.participation_assessment_persistence_service import (
    build_snapshot_payload,
)
from services.participation_assessment_service import ParticipationAssessmentResult
from services.participation_business_contract import (
    BusinessActivityRuleResult,
    BusinessActivityScreenResult,
)
from services.participation_completeness import build_assessment_completeness
from services.participation_financial_engine import evaluate_financial_rules
from services.participation_intelligence_contract import (
    ASSET_KIND_EQUITY,
    CONFIDENCE_MEDIUM,
    RULE_OUTCOME_INSUFFICIENT_DATA,
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)
from services.participation_intelligence_service import (
    build_combined_methodology_assessment,
)
from services.participation_methodology_capabilities import blocking_missing_capabilities
from services.participation_methodology_registry import get_default_equity_methodology_id
from services.participation_screening_context import (
    DEFAULT_EQUITY_SCREENING_CONTEXT,
    normalize_screening_context,
)
from services.participation_sec_input_resolver import (
    build_participation_inputs_from_sec,
    market_values_share_reporting_currency,
)
from services.research_eligibility_service import (
    evaluate_research_eligibility_from_assessment,
)
from services.sec_company_facts_evidence import (
    SecCompanyFactsEvidence,
    pad_cik,
    verify_evidence_digest,
)
from services.sec_financial_client import SEC_FINANCIAL_EXTRACTOR_VERSION
from services.sec_participation_evidence_population import (
    AssessedEquityIdentity,
    resolve_assessed_equity_population,
)
from services.universe_expansion_contract import (
    EXPANSION_STATUS_COMPLETED,
    EXPANSION_STATUS_PENDING,
    EXPANSION_STATUS_RETRYABLE,
)
from services.universe_expansion_onboarding_service import (
    OnboardingResult,
    compute_next_retry_at,
    is_canonical_participation_status,
    onboarding_final_status,
)


EVIDENCE_SOURCE_CACHE = "sec_company_facts_cache"
RECONCILE_IDEMPOTENCY_KEY = "reconcile_idempotency_key"
SEC_EVIDENCE_DIGEST_KEY = "sec_company_facts_digest"
SEC_EXTRACTOR_VERSION_KEY = "sec_extractor_version"


@dataclass(frozen=True)
class ReconcileReplayItem:
    symbol: str
    cik: str
    evidence_digest: str
    extractor_version: str
    retrieved_at: str
    old_status: str
    new_status: str
    idempotency_key: str
    result: ParticipationAssessmentResult
    queue_status: str
    research_allowed: bool
    error_category: Optional[str]


@dataclass(frozen=True)
class ReconcileApplyItem:
    symbol: str
    old_status: str
    new_status: str
    snapshot_action: str
    candidate_action: str
    queue_action: str
    snapshot_id: Optional[str] = None
    error: Optional[str] = None


@dataclass(frozen=True)
class GlobalReconcilePlan:
    items: tuple[ReconcileReplayItem, ...]
    failed: tuple[tuple[str, str], ...] = ()
    identity_blocked: tuple[str, ...] = ()
    pending_excluded: tuple[str, ...] = ()

    @property
    def transition_matrix(self) -> dict[str, tuple[str, ...]]:
        grouped: dict[str, list[str]] = {}
        for item in self.items:
            key = f"{item.old_status} → {item.new_status}"
            grouped.setdefault(key, []).append(item.symbol)
        return {key: tuple(sorted(symbols)) for key, symbols in grouped.items()}


@dataclass
class GlobalReconcileApplyResult:
    created: list[str] = field(default_factory=list)
    reused: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    candidate_synced: list[str] = field(default_factory=list)
    queue_changed: list[str] = field(default_factory=list)
    items: list[ReconcileApplyItem] = field(default_factory=list)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def compute_reconcile_idempotency_key(
    *,
    symbol: str,
    methodology_id: str,
    methodology_version: str,
    evidence_digest: str,
    extractor_version: str,
    status: str,
    financial_overall: Optional[str],
    business_overall: Optional[str],
    financial_rule_outcomes: Sequence[tuple[str, str]],
    business_rule_outcomes: Sequence[tuple[str, str]],
) -> str:
    payload = {
        "symbol": str(symbol or "").strip().upper(),
        "methodology_id": methodology_id,
        "methodology_version": methodology_version,
        "evidence_digest": evidence_digest,
        "extractor_version": extractor_version,
        "status": status,
        "financial_overall": financial_overall,
        "business_overall": business_overall,
        "financial_rule_outcomes": list(financial_rule_outcomes),
        "business_rule_outcomes": list(business_rule_outcomes),
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _parse_date(value: Any) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value).strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _snapshot_payload(snapshot: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    if not snapshot:
        return {}
    payload = snapshot.get("assessment_payload")
    return dict(payload) if isinstance(payload, Mapping) else {}


def _snapshot_source_evidence(snapshot: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    if not snapshot:
        return {}
    payload = _snapshot_payload(snapshot)
    evidence = payload.get("source_evidence") or snapshot.get("source_evidence") or {}
    return dict(evidence) if isinstance(evidence, Mapping) else {}


def business_screen_from_snapshot(
    symbol: str,
    snapshot: Optional[Mapping[str, Any]],
) -> Optional[BusinessActivityScreenResult]:
    biz = _snapshot_payload(snapshot).get("business_screen_result")
    if not isinstance(biz, Mapping):
        return None
    rules = []
    for row in biz.get("rule_results") or []:
        if not isinstance(row, Mapping):
            continue
        refs = row.get("source_refs") or {}
        if isinstance(refs, Mapping):
            source_refs = tuple((str(k), str(v)) for k, v in refs.items())
        else:
            source_refs = tuple(tuple(item) for item in refs)
        rules.append(
            BusinessActivityRuleResult(
                rule_id=str(row.get("rule_id") or ""),
                category=str(row.get("category") or ""),
                outcome=str(row.get("outcome") or RULE_OUTCOME_INSUFFICIENT_DATA),
                evidence_type=str(row.get("evidence_type") or ""),
                matched_values=tuple(row.get("matched_values") or ()),
                source_refs=source_refs,
                confidence=str(row.get("confidence") or ""),
                threshold_pct=row.get("threshold_pct"),
                comparator=row.get("comparator"),
                ratio_pct=row.get("ratio_pct"),
                warnings=tuple(row.get("warnings") or ()),
            )
        )
    return BusinessActivityScreenResult(
        symbol=symbol,
        methodology_id=str(biz.get("methodology_id") or "msci_islamic_index_series"),
        methodology_version=str(biz.get("methodology_version") or ""),
        rule_results=tuple(rules),
        overall_outcome=str(biz.get("overall_outcome") or RULE_OUTCOME_INSUFFICIENT_DATA),
        evidence_completeness=str(biz.get("evidence_completeness") or ""),
        business_rules_evaluated=bool(biz.get("business_rules_evaluated")),
        methodology_complete=bool(biz.get("methodology_complete")),
        as_of_date=_parse_date(biz.get("as_of_date")),
        warnings=tuple(biz.get("warnings") or ()),
    )


def _rule_outcomes(rules: Any) -> tuple[tuple[str, str], ...]:
    if not rules:
        return ()
    return tuple((rule.rule_id, rule.outcome) for rule in rules)


def _queue_onboarding_for_status(
    *,
    symbol: str,
    status: str,
    research_allowed: bool,
    snapshot_saved: bool,
) -> OnboardingResult:
    participation_status = status or PARTICIPATION_STATUS_KONTROL_ET
    canonical = is_canonical_participation_status(participation_status)
    return OnboardingResult(
        symbol=symbol,
        success=canonical,
        participation_status=participation_status,
        research_allowed=bool(research_allowed) if participation_status == PARTICIPATION_STATUS_UYGUN else False,
        error_category=None,
        snapshot_saved=snapshot_saved,
        candidate_upserted=False,
    )


def assess_from_cached_evidence(
    *,
    identity: AssessedEquityIdentity,
    evidence: SecCompanyFactsEvidence,
    snapshot: Mapping[str, Any],
    extracted: Mapping[str, Any],
) -> ReconcileReplayItem:
    verify_evidence_digest(evidence)
    symbol = identity.symbol
    payload = _snapshot_payload(snapshot)
    old_fin = payload.get("financial_inputs") or {}
    screening_context = normalize_screening_context(
        payload.get("screening_context") or DEFAULT_EQUITY_SCREENING_CONTEXT
    )
    methodology_id = get_default_equity_methodology_id() or "msci_islamic_index_series"
    resolution = build_participation_inputs_from_sec(
        symbol,
        extracted,
        cik=identity.cik,
        market_capitalization=old_fin.get("market_capitalization"),
    )
    npr = old_fin.get("non_permissible_revenue")
    market_values_ok = market_values_share_reporting_currency(
        extracted.get("financial_currency")
    )
    inputs = replace(
        resolution.inputs,
        non_permissible_revenue=npr
        if npr is not None
        else resolution.inputs.non_permissible_revenue,
        market_capitalization=resolution.inputs.market_capitalization,
        average_market_cap_24m=(
            old_fin.get("average_market_cap_24m") if market_values_ok else None
        ),
        average_market_value_of_equity_36m=(
            old_fin.get("average_market_value_of_equity_36m") if market_values_ok else None
        ),
    )
    financial = evaluate_financial_rules(
        methodology_id,
        inputs,
        screening_context=screening_context,
    )
    business = business_screen_from_snapshot(symbol, snapshot)
    assessment = build_combined_methodology_assessment(
        financial,
        business,
        asset_kind=ASSET_KIND_EQUITY,
    )
    assessment = replace(assessment, confidence=CONFIDENCE_MEDIUM)
    missing = blocking_missing_capabilities(
        methodology_id,
        financial_inputs=inputs,
        business_screen=business,
        business_evidence_provided=business is not None,
    )
    evidence_pairs = list(inputs.source_evidence)
    extra = {
        "cik": pad_cik(identity.cik or evidence.cik),
        "provider": "SEC",
        SEC_EVIDENCE_DIGEST_KEY: evidence.content_digest,
        SEC_EXTRACTOR_VERSION_KEY: SEC_FINANCIAL_EXTRACTOR_VERSION,
        "evidence_source": EVIDENCE_SOURCE_CACHE,
        "retrieved_at": evidence.retrieved_at,
    }
    for key, value in extra.items():
        if value and (key, str(value)) not in evidence_pairs:
            evidence_pairs.append((key, str(value)))
    idempotency_key = compute_reconcile_idempotency_key(
        symbol=symbol,
        methodology_id=methodology_id,
        methodology_version=str(
            assessment.methodology_version or financial.methodology_version or ""
        ),
        evidence_digest=evidence.content_digest,
        extractor_version=SEC_FINANCIAL_EXTRACTOR_VERSION,
        status=assessment.status,
        financial_overall=financial.overall_outcome,
        business_overall=business.overall_outcome if business else None,
        financial_rule_outcomes=_rule_outcomes(financial.rule_results),
        business_rule_outcomes=_rule_outcomes(
            business.rule_results if business else ()
        ),
    )
    evidence_pairs.append((RECONCILE_IDEMPOTENCY_KEY, idempotency_key))
    result = ParticipationAssessmentResult(
        symbol=symbol,
        methodology_id=methodology_id,
        resolved_methodology_version=assessment.methodology_version,
        participation_assessment=assessment,
        financial_screen_result=financial,
        financial_inputs=inputs,
        business_screen_result=business,
        source_evidence=tuple(evidence_pairs),
        warnings=tuple(
            dict.fromkeys((*resolution.warnings, *financial.warnings, *(business.warnings if business else ())))
        ),
        errors=(),
        provider_status=(("sec", "cached"),),
        sec_available=True,
        used_market_capitalization=inputs.market_capitalization,
        missing_capabilities=missing,
        participation_provider_calls={},
        screening_context=screening_context,
        sec_financials=dict(extracted),
    )
    completeness = build_assessment_completeness(result)
    result = replace(result, assessment_completeness=completeness)
    eligibility = evaluate_research_eligibility_from_assessment(result, symbol=symbol)
    onboarding = _queue_onboarding_for_status(
        symbol=symbol,
        status=assessment.status,
        research_allowed=eligibility.research_allowed,
        snapshot_saved=True,
    )
    queue_status = onboarding_final_status(onboarding, budget_rate_limited=False)
    return ReconcileReplayItem(
        symbol=symbol,
        cik=pad_cik(identity.cik or evidence.cik),
        evidence_digest=evidence.content_digest,
        extractor_version=SEC_FINANCIAL_EXTRACTOR_VERSION,
        retrieved_at=evidence.retrieved_at,
        old_status=str(snapshot.get("status") or ""),
        new_status=assessment.status,
        idempotency_key=idempotency_key,
        result=result,
        queue_status=queue_status,
        research_allowed=eligibility.research_allowed,
        error_category=onboarding.error_category,
    )


def _select_identities(
    identities: Sequence[AssessedEquityIdentity],
    *,
    symbol: Optional[str] = None,
    start_after: Optional[str] = None,
    limit: Optional[int] = None,
) -> tuple[AssessedEquityIdentity, ...]:
    selected = [item for item in identities if item.fetchable]
    selected.sort(key=lambda item: item.symbol)
    if symbol:
        wanted = str(symbol).strip().upper()
        selected = [item for item in selected if item.symbol == wanted]
    if start_after:
        marker = str(start_after).strip().upper()
        selected = [item for item in selected if item.symbol > marker]
    if limit is not None:
        selected = selected[: max(0, int(limit))]
    return tuple(selected)


def plan_global_participation_reconciliation(
    *,
    queue_rows: Sequence[Mapping[str, Any]],
    snapshots_by_symbol: Mapping[str, Mapping[str, Any]],
    candidates_by_symbol: Optional[Mapping[str, Mapping[str, Any]]] = None,
    cache: Optional[SecCompanyFactsCache] = None,
    symbol: Optional[str] = None,
    start_after: Optional[str] = None,
    limit: Optional[int] = None,
) -> GlobalReconcilePlan:
    cache = cache or SecCompanyFactsCache()
    population = resolve_assessed_equity_population(
        queue_rows=queue_rows,
        snapshots_by_symbol=snapshots_by_symbol,
        candidates_by_symbol=candidates_by_symbol,
    )
    items: list[ReconcileReplayItem] = []
    failed: list[tuple[str, str]] = []
    for identity in _select_identities(
        population.assessed,
        symbol=symbol,
        start_after=start_after,
        limit=limit,
    ):
        snapshot = snapshots_by_symbol.get(identity.symbol)
        if not snapshot:
            failed.append((identity.symbol, "missing_snapshot"))
            continue
        evidence = cache.get_latest(symbol=identity.symbol, cik=identity.cik)
        if evidence is None:
            failed.append((identity.symbol, "cache_miss"))
            continue
        try:
            extracted = cache.replay(evidence)
            items.append(
                assess_from_cached_evidence(
                    identity=identity,
                    evidence=evidence,
                    snapshot=snapshot,
                    extracted=extracted,
                )
            )
        except Exception as exc:
            failed.append((identity.symbol, str(exc)))
    return GlobalReconcilePlan(
        items=tuple(items),
        failed=tuple(failed),
        identity_blocked=tuple(population.cik_conflicts)
        + tuple(population.duplicate_ciks)
        + tuple(population.missing_cik),
        pending_excluded=tuple(population.pending_excluded),
    )


def _latest_idempotency_key(snapshot: Optional[Mapping[str, Any]]) -> str:
    evidence = _snapshot_source_evidence(snapshot)
    return str(evidence.get(RECONCILE_IDEMPOTENCY_KEY) or "").strip()


def _candidate_id(candidate: Optional[Mapping[str, Any]]) -> Optional[str]:
    if not candidate:
        return None
    value = candidate.get("id")
    return str(value) if value else None


def apply_global_participation_reconciliation(
    plan: GlobalReconcilePlan,
    *,
    participation_repo,
    candidate_repo=None,
    queue_repo=None,
    candidates_by_symbol: Optional[Mapping[str, Mapping[str, Any]]] = None,
    queue_rows: Optional[Sequence[Mapping[str, Any]]] = None,
    now: Optional[datetime] = None,
) -> GlobalReconcileApplyResult:
    timestamp = now or _utcnow()
    candidates_by_symbol = candidates_by_symbol or {}
    queue_by_symbol = {
        str(row.get("symbol") or "").strip().upper(): row
        for row in (queue_rows or [])
        if str(row.get("symbol") or "").strip()
    }
    result = GlobalReconcileApplyResult()

    for item in plan.items:
        try:
            latest = participation_repo.get_latest(item.symbol)
            snapshot_action = "created"
            snapshot_id = None
            if _latest_idempotency_key(latest) == item.idempotency_key:
                snapshot_action = "reused"
                snapshot_id = str((latest or {}).get("id") or "") or None
                result.reused.append(item.symbol)
            else:
                payload = build_snapshot_payload(item.result, assessed_at=timestamp)
                row = participation_repo.append_snapshot(payload)
                snapshot_id = str((row or {}).get("id") or "") or None
                result.created.append(item.symbol)

            candidate_action = "none"
            candidate = candidates_by_symbol.get(item.symbol)
            candidate_id = _candidate_id(candidate)
            if candidate_id and candidate_repo is not None:
                current = str(candidate.get("participation_status") or "").strip()
                if current != item.new_status:
                    candidate_repo.update(
                        candidate_id,
                        {"participation_status": item.new_status},
                    )
                    candidate_action = "synced"
                    result.candidate_synced.append(item.symbol)
                else:
                    candidate_action = "unchanged"

            queue_action = "none"
            queue_row = queue_by_symbol.get(item.symbol)
            if queue_repo is not None and queue_row:
                current_queue = str(queue_row.get("status") or "").strip().upper()
                if current_queue == EXPANSION_STATUS_PENDING:
                    queue_action = "pending_out_of_scope"
                else:
                    desired_status = item.queue_status
                    current_part = str(queue_row.get("participation_status") or "").strip()
                    current_research = bool(queue_row.get("research_allowed"))
                    next_retry = compute_next_retry_at(
                        timestamp,
                        error_category=item.error_category,
                        attempt_count=int(queue_row.get("attempt_count") or 1),
                        default_hours=6,
                        plan_restricted_days=7,
                    )
                    updates = {
                        "status": desired_status,
                        "participation_status": item.new_status,
                        "research_allowed": item.research_allowed,
                        "last_error_category": item.error_category,
                        "next_retry_at": next_retry
                        if desired_status == EXPANSION_STATUS_RETRYABLE
                        else None,
                        "completed_at": timestamp.isoformat()
                        if desired_status == EXPANSION_STATUS_COMPLETED
                        else None,
                        "claimed_at": None,
                        "claim_run_id": None,
                    }
                    unchanged = (
                        current_queue == desired_status
                        and current_part == item.new_status
                        and current_research == item.research_allowed
                    )
                    if unchanged:
                        queue_action = "unchanged"
                    else:
                        queue_repo.finalize(str(queue_row["id"]), updates)
                        queue_action = "updated"
                        result.queue_changed.append(item.symbol)

            result.items.append(
                ReconcileApplyItem(
                    symbol=item.symbol,
                    old_status=item.old_status,
                    new_status=item.new_status,
                    snapshot_action=snapshot_action,
                    candidate_action=candidate_action,
                    queue_action=queue_action,
                    snapshot_id=snapshot_id,
                )
            )
        except Exception as exc:
            result.failed.append((item.symbol, str(exc)))
            result.items.append(
                ReconcileApplyItem(
                    symbol=item.symbol,
                    old_status=item.old_status,
                    new_status=item.new_status,
                    snapshot_action="failed",
                    candidate_action="failed",
                    queue_action="failed",
                    error=str(exc),
                )
            )
    for symbol, error in plan.failed:
        result.skipped.append(symbol)
        result.failed.append((symbol, error))
    return result
