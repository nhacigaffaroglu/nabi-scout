"""Explicit recommendation history recording. Never called by UI render paths."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from services.nabi_decision_contract import DecisionAuditRecord, NabiDecisionV3
from services.nabi_recommendation_history_contract import (
    RecommendationHistoryRecord,
    logical_event_identity_from_audit,
)
from services.nabi_recommendation_history_store import InMemoryRecommendationHistoryStore


def _optional_text(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    return text or None


def _optional_price(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None
    return price


def extract_candidate_price(
    candidate: Optional[Mapping[str, Any]],
) -> tuple[Optional[float], Optional[str]]:
    if not candidate:
        return None, None
    price = _optional_price(candidate.get("current_price"))
    currency = _optional_text(
        candidate.get("price_currency") or candidate.get("currency")
    )
    if price is None:
        return None, None
    return price, currency


def record_recommendation(
    audit: DecisionAuditRecord,
    store: InMemoryRecommendationHistoryStore,
    *,
    why: Optional[str] = None,
    portfolio_snapshot_reference: Optional[str] = None,
    participation_snapshot_reference: Optional[str] = None,
    research_reference: Optional[str] = None,
    evaluation_reference: Optional[str] = None,
    price_at_recommendation: Optional[float] = None,
    price_currency: Optional[str] = None,
    candidate: Optional[Mapping[str, Any]] = None,
) -> RecommendationHistoryRecord:
    """Append a history event, or reuse the existing logical observation.

    UI render paths must not call this. Persistence is explicit.
    """
    logical_id = logical_event_identity_from_audit(audit)
    existing = store.find_by_logical_id(logical_id)
    if existing is not None:
        return existing
    if price_at_recommendation is None:
        price_at_recommendation, inferred_ccy = extract_candidate_price(candidate)
        if price_currency is None:
            price_currency = inferred_ccy
    record = RecommendationHistoryRecord(
        recommendation_id=audit.recommendation_id,
        logical_event_id=logical_id,
        generated_at=audit.generated_at,
        symbol=audit.symbol,
        final_action=audit.final_action,
        participation_status=audit.participation_status,
        research_completeness=audit.research_completeness,
        decision_class=audit.decision_class,
        nabi_score=audit.nabi_score,
        timing_state=audit.timing_state,
        portfolio_fit=audit.portfolio_fit,
        wealth_action=audit.wealth_action,
        reason_codes=tuple(audit.reason_codes),
        evidence_references=tuple(audit.evidence_references),
        why=_optional_text(why),
        portfolio_snapshot_reference=_optional_text(portfolio_snapshot_reference),
        participation_snapshot_reference=_optional_text(
            participation_snapshot_reference
        ),
        research_reference=_optional_text(research_reference),
        evaluation_reference=_optional_text(evaluation_reference),
        price_at_recommendation=price_at_recommendation,
        price_currency=_optional_text(price_currency),
        persisted=True,
    )
    return store.append_record(record)


def record_decision_v3(
    view: NabiDecisionV3,
    store: InMemoryRecommendationHistoryStore,
    *,
    candidate: Optional[Mapping[str, Any]] = None,
    portfolio_snapshot_reference: Optional[str] = None,
    participation_snapshot_reference: Optional[str] = None,
    research_reference: Optional[str] = None,
    evaluation_reference: Optional[str] = None,
) -> RecommendationHistoryRecord:
    return record_recommendation(
        view.audit,
        store,
        why=view.why,
        candidate=candidate,
        portfolio_snapshot_reference=portfolio_snapshot_reference,
        participation_snapshot_reference=participation_snapshot_reference,
        research_reference=research_reference,
        evaluation_reference=evaluation_reference,
    )
