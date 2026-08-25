"""Offline assessment helpers for a named pending/former-pending cohort.

Does not write participation snapshots, candidates, or queue rows.
Company Facts cache writes are explicit and separate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from repositories.sec_company_facts_cache import SecCompanyFactsCache
from services.global_participation_reconciliation import assess_from_cached_evidence
from services.participation_cik_resolver import is_usable_cik, normalize_resolved_cik
from services.participation_source_evidence import participation_source_evidence_mapping
from services.sec_company_facts_evidence import pad_cik
from services.sec_participation_evidence_population import AssessedEquityIdentity
from services.sec_participation_evidence_refresh import (
    SecEvidenceFetchResult,
    SecEvidenceRefreshPlan,
    fetch_sec_evidence,
)
from services.universe_expansion_contract import EXPANSION_STATUS_PENDING


@dataclass(frozen=True)
class CohortIdentity:
    symbol: str
    queue_status: str
    snapshot_status: Optional[str]
    cik: Optional[str]
    cik_source: str
    fetchable: bool
    problems: tuple[str, ...]
    still_pending: bool


@dataclass(frozen=True)
class CohortPreflight:
    expected: tuple[str, ...]
    identities: tuple[CohortIdentity, ...]
    pending_confirmed: tuple[str, ...]
    already_processed: tuple[str, ...]
    conflicts: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "expected": list(self.expected),
            "pending_confirmed": list(self.pending_confirmed),
            "already_processed": list(self.already_processed),
            "conflicts": list(self.conflicts),
            "identities": [
                {
                    "symbol": item.symbol,
                    "queue_status": item.queue_status,
                    "snapshot_status": item.snapshot_status,
                    "cik": item.cik,
                    "cik_source": item.cik_source,
                    "fetchable": item.fetchable,
                    "problems": list(item.problems),
                    "still_pending": item.still_pending,
                }
                for item in self.identities
            ],
        }


def _snapshot_cik(snapshot: Optional[Mapping[str, Any]]) -> Optional[str]:
    if not snapshot:
        return None
    payload = snapshot.get("assessment_payload") or {}
    for source in (payload.get("source_evidence"), snapshot.get("source_evidence")):
        cik = participation_source_evidence_mapping(source).get("cik")
        if is_usable_cik(cik):
            return pad_cik(normalize_resolved_cik(cik))
    return None


def _candidate_cik(candidate: Optional[Mapping[str, Any]]) -> Optional[str]:
    if not candidate:
        return None
    cik = candidate.get("cik")
    if is_usable_cik(cik):
        return pad_cik(normalize_resolved_cik(cik))
    return None


def preflight_named_cohort(
    symbols: Sequence[str],
    *,
    queue_rows: Mapping[str, Mapping[str, Any]],
    snapshots_by_symbol: Mapping[str, Mapping[str, Any]],
    candidates_by_symbol: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> CohortPreflight:
    candidates_by_symbol = candidates_by_symbol or {}
    expected = tuple(str(symbol).strip().upper() for symbol in symbols if str(symbol).strip())
    identities: list[CohortIdentity] = []
    pending: list[str] = []
    processed: list[str] = []
    conflicts: list[str] = []
    seen_ciks: dict[str, str] = {}

    for symbol in expected:
        queue = queue_rows.get(symbol) or {}
        snapshot = snapshots_by_symbol.get(symbol)
        candidate = candidates_by_symbol.get(symbol)
        queue_status = str(queue.get("status") or "").strip().upper()
        snap_cik = _snapshot_cik(snapshot)
        cand_cik = _candidate_cik(candidate)
        problems: list[str] = []
        cik = None
        source = "unresolved"
        if snap_cik and cand_cik and snap_cik != cand_cik:
            problems.append("snapshot_candidate_cik_conflict")
            source = "conflict"
        elif snap_cik:
            cik = snap_cik
            source = "snapshot"
        elif cand_cik:
            cik = cand_cik
            source = "candidate_record"
        else:
            problems.append("missing_cik")
        if cik and cik in seen_ciks:
            problems.append("duplicate_cik_identity")
        if cik:
            seen_ciks.setdefault(cik, symbol)
        still_pending = queue_status == EXPANSION_STATUS_PENDING and snapshot is None
        if still_pending:
            pending.append(symbol)
        elif snapshot is not None:
            processed.append(symbol)
        if problems:
            conflicts.append(symbol)
        identities.append(
            CohortIdentity(
                symbol=symbol,
                queue_status=queue_status,
                snapshot_status=str(snapshot.get("status") or "") if snapshot else None,
                cik=cik,
                cik_source=source,
                fetchable=cik is not None and not problems,
                problems=tuple(problems),
                still_pending=still_pending,
            )
        )

    return CohortPreflight(
        expected=expected,
        identities=tuple(identities),
        pending_confirmed=tuple(pending),
        already_processed=tuple(processed),
        conflicts=tuple(conflicts),
    )


def plan_cohort_company_facts(
    preflight: CohortPreflight,
    *,
    cache: SecCompanyFactsCache,
) -> SecEvidenceRefreshPlan:
    hits: list[str] = []
    misses: list[str] = []
    refresh: list[AssessedEquityIdentity] = []
    blocked: list[str] = []
    miss_ciks: list[str] = []
    for item in preflight.identities:
        identity = AssessedEquityIdentity(
            symbol=item.symbol,
            cik=item.cik,
            cik_source=item.cik_source,
            fetchable=item.fetchable,
            problems=item.problems,
        )
        if not item.fetchable:
            blocked.append(item.symbol)
            continue
        cached = cache.get_latest(symbol=item.symbol, cik=item.cik)
        if cached is not None and cached.cik == item.cik:
            hits.append(item.symbol)
            continue
        misses.append(item.symbol)
        refresh.append(identity)
        if item.cik and item.cik not in miss_ciks:
            miss_ciks.append(item.cik)
    from services.sec_participation_evidence_population import AssessedEquityPopulation

    return SecEvidenceRefreshPlan(
        population=AssessedEquityPopulation(
            assessed=tuple(refresh),
            catalog_excluded=(),
            pending_excluded=preflight.pending_confirmed,
            missing_cik=tuple(
                item.symbol for item in preflight.identities if "missing_cik" in item.problems
            ),
            cik_conflicts=tuple(
                item.symbol
                for item in preflight.identities
                if "snapshot_candidate_cik_conflict" in item.problems
            ),
            duplicate_ciks=(),
        ),
        cache_hits=tuple(hits),
        cache_misses=tuple(misses),
        refresh_candidates=tuple(refresh),
        expected_sec_calls=len(miss_ciks),
        identity_blocked=tuple(blocked),
    )


def fetch_cohort_company_facts(
    plan: SecEvidenceRefreshPlan,
    *,
    fetcher,
    cache: SecCompanyFactsCache,
) -> SecEvidenceFetchResult:
    return fetch_sec_evidence(plan, fetcher=fetcher, cache=cache)


def dry_run_cohort_from_cache(
    preflight: CohortPreflight,
    *,
    snapshots_by_symbol: Mapping[str, Mapping[str, Any]],
    cache: SecCompanyFactsCache,
) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for item in preflight.identities:
        snapshot = snapshots_by_symbol.get(item.symbol)
        evidence = cache.get_latest(symbol=item.symbol, cik=item.cik)
        if evidence is None or snapshot is None or not item.fetchable:
            rows.append(
                {
                    "symbol": item.symbol,
                    "old_status": item.snapshot_status,
                    "new_status": None,
                    "error": "missing_cache_or_snapshot_or_identity",
                }
            )
            continue
        cache.verify_digest(evidence.content_digest)
        extracted = cache.replay(evidence)
        replay = assess_from_cached_evidence(
            identity=AssessedEquityIdentity(
                symbol=item.symbol,
                cik=item.cik,
                cik_source=item.cik_source,
                fetchable=True,
                problems=(),
            ),
            evidence=evidence,
            snapshot=snapshot,
            extracted=extracted,
        )
        rows.append(
            {
                "symbol": item.symbol,
                "cik": item.cik,
                "old_status": replay.old_status,
                "new_status": replay.new_status,
                "npr": replay.result.financial_inputs.non_permissible_revenue,
                "financial": replay.result.financial_screen_result.overall_outcome
                if replay.result.financial_screen_result
                else None,
                "business": replay.result.business_screen_result.overall_outcome
                if replay.result.business_screen_result
                else None,
                "period": extracted.get("financial_period_end"),
                "currency": extracted.get("financial_currency"),
                "digest": evidence.content_digest,
                "missing": list(replay.result.missing_capabilities),
            }
        )
    return tuple(rows)
