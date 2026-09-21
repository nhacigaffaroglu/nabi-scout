"""Publish evaluated Security Intelligence through the canonical snapshot contract.

SecurityFacts → SecurityIntelligenceService.evaluate() → existing snapshot
repository. Does not score, change weights, write portfolios, Participation,
or New Money. Does not create a second SI store.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
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
    FRESHNESS_FRESH,
    PERIOD_INCOMPATIBLE,
    SecurityFacts,
    SecurityIntelligenceView,
    SecurityParticipationContext,
)
from services.security_intelligence_service import SecurityIntelligenceService
from services.security_intelligence_snapshot_service import (
    UNDATED_AS_OF_KEY,
    SaveSecurityIntelligenceResult,
    as_of_key,
    canonicalize_as_of,
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
REASON_AS_OF_MISSING = "AS_OF_MISSING"
REASON_FRESHNESS_NOT_FRESH = "FRESHNESS_NOT_FRESH"
REASON_SUPERSEDED_BY_NEWER = "SUPERSEDED_BY_NEWER_SNAPSHOT"
REASON_AUTHORITY_LOOKUP_FAILED = "PERSISTED_AUTHORITY_LOOKUP_FAILED"


def _as_of_instant(value: Any) -> Optional[datetime]:
    """Comparable UTC instant for monotonic publish checks.

    Date-only authority is treated as midnight UTC. Non-midnight timestamps
    preserve their evidence ordering; timezone-aware values are normalized.
    """
    canonical = canonicalize_as_of(value)
    if canonical is None:
        return None
    text = str(canonical).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _snapshot_data_quality_provenance(
    facts: SecurityFacts,
) -> dict[str, Any]:
    """Stable evidence identity for persisted SI audit.

    This metadata does not participate in scoring. Runtime timestamps are not
    invented here; only evidence dates already present on canonical facts are
    persisted.
    """
    metadata: dict[str, Any] = {
        "facts_as_of": facts.as_of,
        "facts_freshness_status": facts.freshness_status,
        "facts_authority_status": facts.authority_status,
        "facts_period_compatibility": facts.period_compatibility,
        "facts_period_kind": facts.period_kind,
    }

    sec_retrieved = sorted(
        {
            str(item.retrieved_at).strip()
            for item in tuple(facts.provenance or ())
            if str(getattr(item, "authority", "") or "").strip().upper()
            == "SEC"
            and str(getattr(item, "retrieved_at", "") or "").strip()
        }
    )
    if sec_retrieved:
        metadata["sec_evidence_retrieved_at"] = sec_retrieved[-1]

    valuation = facts.valuation_context
    if valuation is not None:
        metrics = tuple(valuation.metrics or ())

        fundamental_periods = sorted(
            {
                str(item.fundamental_period_end).strip()
                for item in metrics
                if str(item.fundamental_period_end or "").strip()
            }
        )
        market_dates = sorted(
            {
                str(item.market_data_as_of).strip()
                for item in metrics
                if str(item.market_data_as_of or "").strip()
            }
        )
        providers = sorted(
            {
                str(item.source_provider).strip()
                for item in metrics
                if str(item.source_provider or "").strip()
            }
        )
        families = sorted(
            {
                str(item.data_family).strip()
                for item in metrics
                if str(item.data_family or "").strip()
            }
        )

        metadata["valuation_as_of"] = valuation.as_of
        metadata["valuation_authority"] = valuation.authority
        metadata["valuation_source"] = valuation.source

        if fundamental_periods:
            metadata["valuation_fundamental_period_end"] = (
                fundamental_periods[-1]
            )
        if market_dates:
            metadata["valuation_market_data_as_of"] = market_dates[-1]
        if providers:
            metadata["valuation_source_providers"] = providers
        if families:
            metadata["valuation_data_families"] = families

    return metadata


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

    @property
    def failed_to_persist(self) -> bool:
        """UI-safe alias for persistence failure state."""
        return bool(self.persistence_failed)


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
    readiness_applies = bist_readiness_applies(facts)
    if readiness_applies:
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
    elif not identity_ok:
        return PublishSecurityIntelligenceResult(
            published=False,
            blocked=True,
            view=view,
            block_reason=REASON_IDENTITY_MISSING,
            message="Security Master identity is required to publish SI.",
        )

    publish_as_of_key = as_of_key(facts.as_of)
    if publish_as_of_key == UNDATED_AS_OF_KEY:
        return PublishSecurityIntelligenceResult(
            published=False,
            blocked=True,
            view=view,
            eligibility=eligibility,
            block_reason=REASON_AS_OF_MISSING,
            message="A dated SecurityFacts as_of is required for persisted SI authority.",
        )

    freshness = str(facts.freshness_status or "").strip().upper()
    if bool(facts.stale) or freshness != FRESHNESS_FRESH:
        return PublishSecurityIntelligenceResult(
            published=False,
            blocked=True,
            view=view,
            eligibility=eligibility,
            block_reason=REASON_FRESHNESS_NOT_FRESH,
            message=(
                "SecurityFacts freshness must be canonically FRESH before "
                "publishing persisted SI authority."
            ),
        )

    if str(facts.period_compatibility or "").strip().upper() == PERIOD_INCOMPATIBLE:
        return PublishSecurityIntelligenceResult(
            published=False,
            blocked=True,
            view=view,
            eligibility=eligibility,
            block_reason=REASON_UNSAFE_PERIOD,
            message="Incompatible fact periods cannot be published as SI authority.",
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

    try:
        latest_row = repo.get_latest(facts.symbol)
    except Exception:
        return PublishSecurityIntelligenceResult(
            published=False,
            blocked=True,
            persistence_failed=True,
            view=view,
            eligibility=eligibility,
            block_reason=REASON_AUTHORITY_LOOKUP_FAILED,
            message="Persisted SI authority could not be read before publish.",
        )

    latest_key = (
        as_of_key((latest_row or {}).get("as_of") or (latest_row or {}).get("as_of_key"))
        if latest_row
        else UNDATED_AS_OF_KEY
    )
    publish_instant = _as_of_instant(facts.as_of)
    latest_instant = _as_of_instant((latest_row or {}).get("as_of")) if latest_row else None
    backdated = (
        latest_key != UNDATED_AS_OF_KEY
        and (
            publish_as_of_key < latest_key
            or (
                publish_as_of_key == latest_key
                and publish_instant is not None
                and latest_instant is not None
                and publish_instant < latest_instant
            )
        )
    )
    if backdated:
        return PublishSecurityIntelligenceResult(
            published=False,
            blocked=True,
            view=view,
            eligibility=eligibility,
            block_reason=REASON_SUPERSEDED_BY_NEWER,
            message=(
                "A newer persisted SI snapshot already exists; backdated publish "
                "cannot replace canonical authority."
            ),
        )

    save = save_security_intelligence_snapshot(
        repo,
        view,
        as_of=facts.as_of,
        dry_run=dry_run,
        completeness_pct=facts.completeness_pct,
        require_sufficient=require_sufficient,
        data_quality_metadata=_snapshot_data_quality_provenance(facts),
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
