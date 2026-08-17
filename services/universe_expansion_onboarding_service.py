from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Mapping, Optional

from repositories.participation_assessment_repository import ParticipationAssessmentRepository
from services.company_report_participation_service import build_company_report_participation
from services.participation_assessment_persistence_service import (
    save_participation_assessment_snapshot,
)
from services.research_eligibility_service import evaluate_research_eligibility_from_assessment
from services.universe_expansion_contract import (
    ERROR_CATEGORY_PLAN_RESTRICTED,
    ERROR_CATEGORY_RATE_LIMIT,
    EXPANSION_STATUS_BLOCKED,
    EXPANSION_STATUS_COMPLETED,
    EXPANSION_STATUS_RETRYABLE,
    PROVIDER_FMP,
    PROVIDER_SEC,
)
from services.universe_expansion_error_classifier import (
    classify_fmp_error,
    classify_participation_outcome,
    classify_sec_error,
)
from services.universe_expansion_candidate_payload import build_expansion_candidate_payload
from services.universe_expansion_provider_wrappers import (
    map_participation_calls_to_providers,
)


@dataclass(frozen=True)
class OnboardingResult:
    symbol: str
    success: bool
    participation_status: str = ""
    research_allowed: bool = False
    provider_calls: Dict[str, int] | None = None
    error_category: Optional[str] = None
    error_message: Optional[str] = None
    snapshot_saved: bool = False
    candidate_upserted: bool = False
    company_intelligence_calls: int = 0

    def to_dict(self) -> Dict[str, object]:
        return {
            "symbol": self.symbol,
            "success": self.success,
            "participation_status": self.participation_status,
            "research_allowed": self.research_allowed,
            "provider_calls": dict(self.provider_calls or {}),
            "error_category": self.error_category,
            "error_message": self.error_message,
            "snapshot_saved": self.snapshot_saved,
            "candidate_upserted": self.candidate_upserted,
            "company_intelligence_calls": self.company_intelligence_calls,
        }


def run_participation_onboarding(
    symbol: str,
    *,
    fmp_client: Any = None,
    sec_client: Any = None,
    participation_repo: Optional[ParticipationAssessmentRepository] = None,
    candidate_repo: Any = None,
    persistence_available: bool = True,
    sec_ticker_lookup: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> OnboardingResult:
    normalized = str(symbol or "").strip().upper()
    candidate: Dict[str, Any] = {"symbol": normalized, "market": "US", "asset_type": "equity"}

    try:
        view = build_company_report_participation(
            candidate,
            sec_client=sec_client,
            fmp_client=fmp_client,
            persistence_available=persistence_available,
            sec_ticker_lookup=sec_ticker_lookup,
        )
    except Exception as exc:
        category = classify_fmp_error(exc)
        if sec_client is not None:
            category = classify_sec_error(exc)
        return OnboardingResult(
            symbol=normalized,
            success=False,
            error_category=category,
            error_message=exc.__class__.__name__,
        )

    if not view.available or view.result is None:
        category = classify_participation_outcome(
            available=view.available,
            error_message=view.error_message,
            participation_status="",
            sec_available=False,
        )
        return OnboardingResult(
            symbol=normalized,
            success=False,
            error_category=category,
            error_message=view.error_message or "participation_unavailable",
        )

    result = view.result
    eligibility = evaluate_research_eligibility_from_assessment(
        result,
        symbol=normalized,
    )
    provider_calls = dict(result.participation_provider_calls)
    ci_calls = int(provider_calls.pop("company_intelligence", 0) or 0)

    snapshot_saved = False
    if participation_repo is not None:
        save_result = save_participation_assessment_snapshot(
            participation_repo,
            view,
            skip_if_identical=True,
        )
        snapshot_saved = bool(save_result.saved or save_result.skipped_duplicate)

    candidate_upserted = False
    if candidate_repo is not None:
        payload = build_expansion_candidate_payload(result, normalized)
        try:
            writer = getattr(candidate_repo, "upsert_expansion_candidate", None)
            if callable(writer):
                writer(payload)
            else:
                candidate_repo.upsert_by_symbol(payload)
            candidate_upserted = True
        except Exception:
            candidate_upserted = False

    participation_status = result.participation_assessment.status
    error_category = classify_participation_outcome(
        available=True,
        error_message=None,
        participation_status=participation_status,
        sec_available=result.sec_available,
    )

    return OnboardingResult(
        symbol=normalized,
        success=error_category is None,
        participation_status=participation_status,
        research_allowed=eligibility.research_allowed,
        provider_calls=provider_calls,
        error_category=error_category,
        snapshot_saved=snapshot_saved,
        candidate_upserted=candidate_upserted,
        company_intelligence_calls=ci_calls,
    )


def onboarding_final_status(
    onboarding: OnboardingResult,
    *,
    budget_rate_limited: bool,
) -> str:
    if onboarding.success:
        return EXPANSION_STATUS_COMPLETED
    if budget_rate_limited or onboarding.error_category == ERROR_CATEGORY_RATE_LIMIT:
        return EXPANSION_STATUS_RETRYABLE
    if onboarding.error_category == ERROR_CATEGORY_PLAN_RESTRICTED:
        return EXPANSION_STATUS_BLOCKED
    if onboarding.participation_status:
        return EXPANSION_STATUS_COMPLETED
    return EXPANSION_STATUS_RETRYABLE


def compute_next_retry_at(
    now: datetime,
    *,
    error_category: Optional[str],
    attempt_count: int,
    default_hours: int,
    plan_restricted_days: int,
) -> Optional[str]:
    if not error_category:
        return None
    if error_category == ERROR_CATEGORY_RATE_LIMIT:
        hours = max(default_hours, min(24, 2 ** min(attempt_count, 4)))
        return (now + timedelta(hours=hours)).isoformat()
    if error_category == ERROR_CATEGORY_PLAN_RESTRICTED:
        return (now + timedelta(days=plan_restricted_days)).isoformat()
    return (now + timedelta(hours=default_hours)).isoformat()


def provider_call_totals(provider_calls: Mapping[str, int]) -> Dict[str, int]:
    totals = map_participation_calls_to_providers(provider_calls)
    totals.setdefault(PROVIDER_FMP, 0)
    totals.setdefault(PROVIDER_SEC, 0)
    return totals
