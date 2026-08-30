"""Publish evaluated Security Intelligence through the canonical snapshot contract.

SecurityFacts → SecurityIntelligenceService.evaluate() → existing snapshot
repository. Does not score, change weights, write portfolios, Participation,
or New Money. Does not create a second SI store.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from services.bist_si_readiness import (
    EVAL_INSUFFICIENT,
    EVAL_SAFE,
    BistSiEligibility,
    assess_bist_si_eligibility,
    classify_shadow_evaluation,
)
from services.bist_symbol_mapping import BIST_EXCHANGES
from services.security_intelligence_contract import (
    SecurityFacts,
    SecurityIntelligenceView,
    SecurityParticipationContext,
)
from services.security_intelligence_service import SecurityIntelligenceService
from services.security_intelligence_snapshot_service import (
    SaveSecurityIntelligenceResult,
    may_persist_view,
    save_security_intelligence_snapshot,
)
from services.security_master_contract import INSTRUMENT_EQUITY
from services.signal_ingestion_universe import TR_MARKETS


REASON_ENGINE_EXCEPTION = "SI_ENGINE_EXCEPTION"
REASON_PRODUCTION_QUALITY = "PRODUCTION_QUALITY_INSUFFICIENT"
REASON_IDENTITY_MISSING = "MISSING_IDENTITY"
REASON_UNSAFE_PERIOD = "UNSAFE_PERIOD"
REASON_INSUFFICIENT_FACTS = "INSUFFICIENT_FACTS"


def bist_readiness_applies(facts: SecurityFacts) -> bool:
    """Generic BIST/TRY equity readiness, not a symbol allowlist."""
    exchange = str(facts.exchange or "").strip().upper()
    currency = str(facts.currency or "").strip().upper()
    instrument = str(facts.instrument_type or "").strip().upper()
    if exchange in TR_MARKETS or exchange in BIST_EXCHANGES:
        return True
    if currency in {"TRY", "TL"} and instrument in {"", INSTRUMENT_EQUITY}:
        return True
    return False


@dataclass(frozen=True)
class PublishSecurityIntelligenceResult:
    published: bool
    skipped_duplicate: bool = False
    blocked: bool = False
    persistence_failed: bool = False
    insufficient: bool = False
    dry_run: bool = False
    view: Optional[SecurityIntelligenceView] = None
    eligibility: Optional[BistSiEligibility] = None
    save: Optional[SaveSecurityIntelligenceResult] = None
    block_reason: str = ""
    message: str = ""


def publish_canonical_security_intelligence(
    facts: SecurityFacts,
    participation: SecurityParticipationContext,
    repo: Any,
    *,
    previous: Any = None,
    dry_run: bool = False,
    require_sufficient: bool = True,
    kap_bundle: Any = None,
    identity_ok: bool = True,
) -> PublishSecurityIntelligenceResult:
    """Evaluate canonical SI and persist through the existing snapshot contract."""
    try:
        view = SecurityIntelligenceService().evaluate(
            facts, participation, previous=previous
        )
    except Exception:
        return PublishSecurityIntelligenceResult(
            published=False,
            blocked=True,
            block_reason=REASON_ENGINE_EXCEPTION,
            message="Security Intelligence evaluation failed.",
        )

    eligibility = None
    if bist_readiness_applies(facts):
        eligibility = assess_bist_si_eligibility(
            facts,
            view,
            participation_status=participation.status,
            identity_ok=identity_ok,
            kap_bundle=kap_bundle,
        )
        shadow = classify_shadow_evaluation(facts, kap_bundle=kap_bundle)
        if not identity_ok:
            return PublishSecurityIntelligenceResult(
                published=False,
                blocked=True,
                view=view,
                eligibility=eligibility,
                block_reason=REASON_IDENTITY_MISSING,
                message="Security Master identity is required to publish SI.",
            )
        if shadow != EVAL_SAFE or not eligibility.production_quality_sufficient:
            reason = REASON_PRODUCTION_QUALITY
            if shadow != EVAL_SAFE:
                reason = (
                    REASON_INSUFFICIENT_FACTS
                    if shadow == EVAL_INSUFFICIENT
                    else REASON_UNSAFE_PERIOD
                )
            return PublishSecurityIntelligenceResult(
                published=False,
                blocked=True,
                view=view,
                eligibility=eligibility,
                block_reason=reason,
                message="Existing production-quality gate refused this snapshot.",
            )

    if require_sufficient and not may_persist_view(
        view, completeness_pct=facts.completeness_pct
    ):
        return PublishSecurityIntelligenceResult(
            published=False,
            insufficient=True,
            view=view,
            eligibility=eligibility,
            block_reason=REASON_INSUFFICIENT_FACTS,
            message="SecurityFacts too sparse to persist a snapshot.",
        )

    save = save_security_intelligence_snapshot(
        repo,
        view,
        as_of=facts.as_of,
        dry_run=dry_run,
        completeness_pct=facts.completeness_pct,
        require_sufficient=require_sufficient,
    )
    return PublishSecurityIntelligenceResult(
        published=bool(save.saved),
        skipped_duplicate=bool(save.skipped_duplicate),
        persistence_failed=bool(save.persistence_failed),
        insufficient=bool(save.insufficient),
        dry_run=bool(save.dry_run),
        view=view,
        eligibility=eligibility,
        save=save,
        message=save.message,
    )
