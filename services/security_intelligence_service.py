"""Canonical Security Intelligence entry point.

Consumers: Scanner, Company Report, Adviser, Wealth Brain, Dashboard,
Signal Intelligence, New Money diagnostics.

Does not write portfolios, candidates, Participation, or Hybrid state.
Facts are assembled only through SecurityFactsService.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from services.security_facts_service import (
    SecurityFactsService,
    facts_from_candidate,
)
from services.security_intelligence_contract import (
    SecurityFacts,
    SecurityIntelligenceSnapshot,
    SecurityIntelligenceView,
    SecurityParticipationContext,
)
from services.security_intelligence_engine import evaluate_security_intelligence

__all__ = (
    "SecurityIntelligenceService",
    "facts_from_candidate",
    "participation_from_sources",
)


def participation_from_sources(
    *,
    queue_or_snapshot: Optional[Mapping[str, Any]] = None,
    candidate: Optional[Mapping[str, Any]] = None,
    research_allowed: Optional[bool] = None,
) -> SecurityParticipationContext:
    row = dict(queue_or_snapshot or {})
    cand = dict(candidate or {})
    payload = row.get("assessment_payload")
    nested = payload if isinstance(payload, Mapping) else {}
    assessment = nested.get("participation_assessment")
    status_from_payload = ""
    if isinstance(assessment, Mapping):
        status_from_payload = str(assessment.get("status") or "")
    status = str(
        row.get("participation_status")
        or row.get("status")
        or status_from_payload
        or cand.get("participation_status")
        or ""
    )
    allowed = research_allowed
    if allowed is None and "research_allowed" in row:
        raw = row.get("research_allowed")
        allowed = None if raw is None else bool(raw)
    return SecurityParticipationContext(
        status=status,
        research_allowed=allowed,
        methodology=str(row.get("methodology_id") or nested.get("methodology_id") or ""),
        as_of=str(row.get("as_of") or row.get("assessed_at") or "") or None,
    )


class SecurityIntelligenceService:
    """Single evaluate() entry. No provider calls. No writes."""

    def __init__(self, facts_service: Optional[SecurityFactsService] = None) -> None:
        self._facts = facts_service or SecurityFactsService()

    def build_facts(self, symbol: str, **kwargs: Any) -> SecurityFacts:
        return self._facts.build(symbol, **kwargs)

    def evaluate(
        self,
        facts: SecurityFacts,
        participation: Optional[SecurityParticipationContext] = None,
        *,
        previous: Optional[SecurityIntelligenceSnapshot] = None,
    ) -> SecurityIntelligenceView:
        return evaluate_security_intelligence(
            facts,
            participation,
            previous=previous,
        )

    def evaluate_symbol(
        self,
        symbol: str,
        *,
        participation: Optional[SecurityParticipationContext] = None,
        previous: Optional[SecurityIntelligenceSnapshot] = None,
        **fact_kwargs: Any,
    ) -> SecurityIntelligenceView:
        facts = self.build_facts(symbol, **fact_kwargs)
        return self.evaluate(facts, participation, previous=previous)
