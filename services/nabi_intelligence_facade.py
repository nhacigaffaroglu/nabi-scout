from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from repositories.candidate_repository import CandidateRepository
from repositories.participation_assessment_repository import (
    ParticipationAssessmentRepository,
)


@dataclass(frozen=True)
class InvestmentIntelligenceView:
    """Read-only NABI research snapshot for a symbol.

    Wealth Core may consume this facade only; it must not trigger scoring,
    participation recomputation, or any writes to NABI tables.
    """

    symbol: str
    market: Optional[str]
    company_name: Optional[str]
    decision: Optional[str]
    nabi_score: Optional[float]
    participation_status: Optional[str]
    participation_score: Optional[int]
    research_status: Optional[str]
    candidate_id: Optional[str]
    has_candidate: bool
    has_participation_snapshot: bool


def get_investment_intelligence(
    client,
    symbol: str,
    *,
    market: Optional[str] = None,
) -> InvestmentIntelligenceView:
    normalized_symbol = str(symbol or "").strip().upper()
    candidate_repo = CandidateRepository(client)
    participation_repo = ParticipationAssessmentRepository(client)

    candidate = candidate_repo.get_by_symbol(normalized_symbol, market=market)
    participation = participation_repo.get_latest(normalized_symbol)

    candidate_participation_status = (
        candidate.get("participation_status") if candidate else None
    )
    candidate_participation_score = (
        candidate.get("participation_score") if candidate else None
    )

    snapshot_status = participation.get("participation_status") if participation else None
    snapshot_score = participation.get("participation_score") if participation else None

    return InvestmentIntelligenceView(
        symbol=normalized_symbol,
        market=(candidate or {}).get("market") or market,
        company_name=(candidate or {}).get("company_name"),
        decision=(candidate or {}).get("decision"),
        nabi_score=(candidate or {}).get("nabi_score"),
        participation_status=snapshot_status or candidate_participation_status,
        participation_score=snapshot_score or candidate_participation_score,
        research_status=(candidate or {}).get("research_status"),
        candidate_id=(candidate or {}).get("id"),
        has_candidate=candidate is not None,
        has_participation_snapshot=participation is not None,
    )


def investment_intelligence_to_dict(view: InvestmentIntelligenceView) -> Dict[str, Any]:
    return {
        "symbol": view.symbol,
        "market": view.market,
        "company_name": view.company_name,
        "decision": view.decision,
        "nabi_score": view.nabi_score,
        "participation_status": view.participation_status,
        "participation_score": view.participation_score,
        "research_status": view.research_status,
        "candidate_id": view.candidate_id,
        "has_candidate": view.has_candidate,
        "has_participation_snapshot": view.has_participation_snapshot,
    }
