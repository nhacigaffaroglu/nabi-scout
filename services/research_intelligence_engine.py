from __future__ import annotations

from services.confidence_engine import calculate_confidence
from services.decision_engine import build_decision
from services.explain_engine import build_score_explanation


def enrich_research(candidate, errors=None):
    confidence = calculate_confidence(
        data_completeness=candidate.get("data_completeness"),
        annual_periods_found=candidate.get("annual_periods_found"),
        endpoint_errors=errors or [],
        score_penalty=candidate.get("score_penalty"),
        financial_period_end=candidate.get("financial_period_end"),
    )
    candidate.update(confidence)

    explanation = build_score_explanation(candidate)
    candidate.update(explanation)

    decision = build_decision(candidate)
    candidate.update(decision)

    candidate["research_engine_version"] = "Sprint 7 v1"
    return candidate
