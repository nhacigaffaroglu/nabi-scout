"""Controlled US Company Intelligence → canonical SI refresh.

Default mode is PLAN: zero FMP calls and zero writes.
Provider execution is explicit. Persisted SI writes additionally require
persist_si + allow_live + dry_run=False.

No Participation, candidate, portfolio, New Money or trade writes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Optional, Sequence

from repositories.candidate_repository import CandidateRepository
from repositories.participation_assessment_repository import (
    ParticipationAssessmentRepository,
)
from repositories.sec_company_facts_cache import SecCompanyFactsCache
from repositories.security_intelligence_snapshot_repository import (
    SecurityIntelligenceSnapshotRepository,
)
from repositories.universe_expansion_repository import UniverseExpansionRepository
from services.company_intelligence_core_service import CompanyIntelligenceCoreService
from services.participation_cik_resolver import normalize_resolved_cik
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.research_eligibility_contract import (
    RESEARCH_STATUS_PASS,
    ResearchEligibilityResult,
)
from services.security_intelligence_publish import (
    publish_canonical_security_intelligence,
)
from services.security_intelligence_service import (
    build_canonical_security_intelligence_inputs,
    explicit_persisted_research_allowed,
    participation_from_sources,
)
from services.security_intelligence_snapshot_service import latest_snapshot
from services.security_master_contract import (
    INSTRUMENT_EQUITY,
    RESOLUTION_RESOLVED,
    SOURCE_BIST,
)
from services.security_master_service import production_security_master


JOB_NAME = "us_security_intelligence_refresh"
MAX_SYMBOLS_DEFAULT = 5

STATUS_PLANNED = "PLANNED"
STATUS_WOULD_PUBLISH = "WOULD_PUBLISH"
STATUS_PUBLISHED = "PUBLISHED"
STATUS_BLOCKED = "BLOCKED"
STATUS_ERROR = "ERROR"
STATUS_NO_CHANGE = "NO_CHANGE"

REASON_PLAN_ONLY = "PLAN_ONLY_NO_PROVIDER_CALLS"
REASON_CANDIDATE_MISSING = "CANDIDATE_MISSING"
REASON_RESEARCH_NOT_ALLOWED = "RESEARCH_NOT_ALLOWED"
REASON_PARTICIPATION_NOT_UYGUN = "PARTICIPATION_NOT_UYGUN"
REASON_FRESHNESS_NOT_FRESH = "CANDIDATE_FRESHNESS_NOT_FRESH"
REASON_IDENTITY_UNSAFE = "SECURITY_MASTER_IDENTITY_UNSAFE"
REASON_SEC_CACHE_MISSING = "SEC_CACHE_MISSING"
REASON_SEC_CACHE_CIK_MISMATCH = "SEC_CACHE_CIK_MISMATCH"
REASON_SEC_CACHE_PERIOD_OLD = "SEC_CACHE_PERIOD_OLDER_THAN_CANDIDATE"
REASON_SEC_CACHE_INVALID = "SEC_CACHE_INVALID"
REASON_FMP_UNAVAILABLE = "FMP_CLIENT_UNAVAILABLE"
REASON_LIVE_UNSAFE = "LIVE_PERSIST_UNSAFE"
REASON_BROAD_SCOPE = "BROAD_SCOPE_REFUSED"
REASON_COMPANY_INTELLIGENCE_FAILED = "COMPANY_INTELLIGENCE_FAILED"


@dataclass(frozen=True)
class UsSiRefreshItem:
    symbol: str
    status: str
    reason: str = ""
    provider_calls: int = 0
    published: bool = False
    would_publish: bool = False
    si_score: Optional[float] = None
    si_state: Optional[str] = None
    block_reason: str = ""
    cache_period: Optional[str] = None
    candidate_period: Optional[str] = None
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class UsSiRefreshRun:
    job_name: str
    dry_run: bool
    execute_providers: bool
    persist_si: bool
    allow_live: bool
    symbols_checked: int
    provider_calls: int
    writes: int
    published: int
    would_publish: int
    blocked: int
    errors: int
    items: tuple[UsSiRefreshItem, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["items"] = [item.to_dict() for item in self.items]
        return payload


def _period(value: Any) -> str:
    text = str(value or "").strip()
    return text[:10] if len(text) >= 10 else ""


def _research_eligibility(
    symbol: str,
    participation_status: str,
) -> ResearchEligibilityResult:
    return ResearchEligibilityResult(
        symbol=symbol,
        status=RESEARCH_STATUS_PASS,
        research_allowed=True,
        participation_status=participation_status,
        reason_codes=("persisted_research_allowed",),
        limitations=(),
        provenance=(("gate", "persisted_participation_and_queue"),),
    )


def _safe_identity(resolution: Any) -> bool:
    if resolution is None:
        return False
    if str(getattr(resolution, "status", "") or "") != RESOLUTION_RESOLVED:
        return False
    if str(getattr(resolution, "instrument_type", "") or "") != INSTRUMENT_EQUITY:
        return False
    if str(getattr(resolution, "source", "") or "") == SOURCE_BIST:
        return False
    return True


def run_us_security_intelligence_refresh(
    symbols: Sequence[str],
    *,
    client: Any,
    fmp_client: Any = None,
    dry_run: bool = True,
    execute_providers: bool = False,
    persist_si: bool = False,
    allow_live: bool = False,
    max_symbols: int = MAX_SYMBOLS_DEFAULT,
    candidate_repo: Any = None,
    participation_repo: Any = None,
    queue_repo: Any = None,
    snapshot_repo: Any = None,
    facts_cache: Any = None,
    security_master: Any = None,
    company_intelligence_service: Any = None,
) -> UsSiRefreshRun:
    normalized = tuple(
        dict.fromkeys(
            str(symbol or "").strip().upper()
            for symbol in symbols
            if str(symbol or "").strip()
        )
    )

    if len(normalized) > max(1, int(max_symbols)):
        raise ValueError(REASON_BROAD_SCOPE)

    live_write = bool(
        persist_si
        and allow_live
        and not dry_run
        and execute_providers
    )
    if persist_si and not allow_live:
        raise ValueError(REASON_LIVE_UNSAFE)
    if not dry_run and persist_si and not execute_providers:
        raise ValueError(REASON_LIVE_UNSAFE)

    candidate_repo = candidate_repo or CandidateRepository(client)
    participation_repo = participation_repo or ParticipationAssessmentRepository(client)
    queue_repo = queue_repo or UniverseExpansionRepository(client)
    snapshot_repo = snapshot_repo or SecurityIntelligenceSnapshotRepository(client)
    facts_cache = facts_cache or SecCompanyFactsCache()
    security_master = security_master or production_security_master(client)

    ci_service = company_intelligence_service
    if execute_providers and ci_service is None:
        if fmp_client is None:
            ci_service = None
        else:
            ci_service = CompanyIntelligenceCoreService(fmp_client)

    items: list[UsSiRefreshItem] = []

    for symbol in normalized:
        provider_calls = 0
        try:
            candidate = candidate_repo.get_by_symbol(symbol)
            if not candidate:
                items.append(
                    UsSiRefreshItem(
                        symbol=symbol,
                        status=STATUS_BLOCKED,
                        reason=REASON_CANDIDATE_MISSING,
                    )
                )
                continue

            participation = participation_repo.get_latest(symbol)
            try:
                queue_row = queue_repo.get_by_symbol(symbol)
            except Exception:
                queue_row = None

            research_allowed = explicit_persisted_research_allowed(
                queue_row=queue_row,
                snapshot=participation,
            )
            participation_context = participation_from_sources(
                queue_or_snapshot=participation,
                candidate=candidate,
                research_allowed=research_allowed,
            )

            if participation_context.status != PARTICIPATION_STATUS_UYGUN:
                items.append(
                    UsSiRefreshItem(
                        symbol=symbol,
                        status=STATUS_BLOCKED,
                        reason=REASON_PARTICIPATION_NOT_UYGUN,
                    )
                )
                continue

            if research_allowed is not True:
                items.append(
                    UsSiRefreshItem(
                        symbol=symbol,
                        status=STATUS_BLOCKED,
                        reason=REASON_RESEARCH_NOT_ALLOWED,
                    )
                )
                continue

            candidate_freshness = str(
                candidate.get("freshness_status") or ""
            ).strip().upper()
            if candidate_freshness != "FRESH":
                items.append(
                    UsSiRefreshItem(
                        symbol=symbol,
                        status=STATUS_BLOCKED,
                        reason=REASON_FRESHNESS_NOT_FRESH,
                    )
                )
                continue

            resolution = security_master.resolve_security(symbol)
            if not _safe_identity(resolution):
                items.append(
                    UsSiRefreshItem(
                        symbol=symbol,
                        status=STATUS_BLOCKED,
                        reason=REASON_IDENTITY_UNSAFE,
                    )
                )
                continue

            evidence = facts_cache.get_latest(symbol=symbol)
            if evidence is None:
                items.append(
                    UsSiRefreshItem(
                        symbol=symbol,
                        status=STATUS_BLOCKED,
                        reason=REASON_SEC_CACHE_MISSING,
                    )
                )
                continue

            candidate_cik = normalize_resolved_cik(candidate.get("cik"))
            evidence_cik = normalize_resolved_cik(
                getattr(evidence, "cik", None)
            )
            if (
                candidate_cik is not None
                and evidence_cik is not None
                and candidate_cik != evidence_cik
            ):
                items.append(
                    UsSiRefreshItem(
                        symbol=symbol,
                        status=STATUS_BLOCKED,
                        reason=REASON_SEC_CACHE_CIK_MISMATCH,
                    )
                )
                continue

            try:
                sec_financials = dict(facts_cache.replay(evidence) or {})
                evidence_retrieved_at = str(
                    getattr(evidence, "retrieved_at", "") or ""
                ).strip()
                if evidence_retrieved_at:
                    sec_financials["_evidence_retrieved_at"] = (
                        evidence_retrieved_at
                    )
            except Exception as exc:
                items.append(
                    UsSiRefreshItem(
                        symbol=symbol,
                        status=STATUS_BLOCKED,
                        reason=REASON_SEC_CACHE_INVALID,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
                continue

            candidate_period = _period(candidate.get("financial_period_end"))
            cache_period = _period(
                sec_financials.get("financial_period_end")
                or sec_financials.get("balance_sheet_period_end")
            )

            if candidate_period and (
                not cache_period or cache_period < candidate_period
            ):
                items.append(
                    UsSiRefreshItem(
                        symbol=symbol,
                        status=STATUS_BLOCKED,
                        reason=REASON_SEC_CACHE_PERIOD_OLD,
                        cache_period=cache_period or None,
                        candidate_period=candidate_period,
                    )
                )
                continue

            if not execute_providers:
                items.append(
                    UsSiRefreshItem(
                        symbol=symbol,
                        status=STATUS_PLANNED,
                        reason=REASON_PLAN_ONLY,
                        cache_period=cache_period or None,
                        candidate_period=candidate_period or None,
                    )
                )
                continue

            if ci_service is None:
                items.append(
                    UsSiRefreshItem(
                        symbol=symbol,
                        status=STATUS_BLOCKED,
                        reason=REASON_FMP_UNAVAILABLE,
                        cache_period=cache_period or None,
                        candidate_period=candidate_period or None,
                    )
                )
                continue

            eligibility = _research_eligibility(
                symbol,
                participation_context.status,
            )

            try:
                ci_view = ci_service.build_view(
                    symbol,
                    research_eligibility=eligibility,
                    refresh=True,
                    sec_financials=sec_financials,
                    market_cap_fallback=candidate.get("market_cap"),
                )
                counts = ci_service.call_budget(
                    symbol,
                    research_eligibility=eligibility,
                )
                provider_calls = sum(
                    int(value or 0)
                    for value in dict(counts or {}).values()
                )
            except Exception as exc:
                items.append(
                    UsSiRefreshItem(
                        symbol=symbol,
                        status=STATUS_ERROR,
                        reason=REASON_COMPANY_INTELLIGENCE_FAILED,
                        provider_calls=provider_calls,
                        cache_period=cache_period or None,
                        candidate_period=candidate_period or None,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
                continue

            facts, canonical_participation = (
                build_canonical_security_intelligence_inputs(
                    symbol,
                    candidate=candidate,
                    participation_snapshot=participation,
                    queue_row=queue_row,
                    security_resolution=resolution,
                    company_intelligence=ci_view,
                    sec_financials=sec_financials,
                    client=client,
                )
            )

            try:
                previous = latest_snapshot(snapshot_repo, symbol)
            except Exception:
                previous = None

            publish = publish_canonical_security_intelligence(
                facts,
                canonical_participation,
                snapshot_repo,
                previous=previous,
                dry_run=not live_write,
                identity_ok=True,
            )

            view = getattr(publish, "view", None)
            score = getattr(view, "overall_score", None)
            state = getattr(view, "investment_state", None)

            if getattr(publish, "published", False):
                status = STATUS_PUBLISHED
            elif getattr(publish, "skipped_duplicate", False):
                status = STATUS_NO_CHANGE
            elif getattr(publish, "dry_run", False) and not getattr(
                publish, "blocked", False
            ):
                status = STATUS_WOULD_PUBLISH
            else:
                status = STATUS_BLOCKED

            items.append(
                UsSiRefreshItem(
                    symbol=symbol,
                    status=status,
                    reason=getattr(publish, "block_reason", "") or "",
                    provider_calls=provider_calls,
                    published=bool(getattr(publish, "published", False)),
                    would_publish=status == STATUS_WOULD_PUBLISH,
                    si_score=score,
                    si_state=state,
                    block_reason=getattr(publish, "block_reason", "") or "",
                    cache_period=cache_period or None,
                    candidate_period=candidate_period or None,
                )
            )

        except Exception as exc:
            items.append(
                UsSiRefreshItem(
                    symbol=symbol,
                    status=STATUS_ERROR,
                    reason=type(exc).__name__,
                    provider_calls=provider_calls,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )

    return UsSiRefreshRun(
        job_name=JOB_NAME,
        dry_run=bool(dry_run),
        execute_providers=bool(execute_providers),
        persist_si=bool(persist_si),
        allow_live=bool(allow_live),
        symbols_checked=len(normalized),
        provider_calls=sum(item.provider_calls for item in items),
        writes=sum(1 for item in items if item.published),
        published=sum(item.status == STATUS_PUBLISHED for item in items),
        would_publish=sum(item.status == STATUS_WOULD_PUBLISH for item in items),
        blocked=sum(item.status == STATUS_BLOCKED for item in items),
        errors=sum(item.status == STATUS_ERROR for item in items),
        items=tuple(items),
    )
