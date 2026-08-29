from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from repositories.candidate_repository import CandidateRepository
from repositories.participation_assessment_repository import (
    ParticipationAssessmentRepository,
)
from repositories.security_intelligence_snapshot_repository import (
    SecurityIntelligenceSnapshotRepository,
)
from repositories.universe_expansion_repository import UniverseExpansionRepository
from services.portfolio_security_decision_contract import PortfolioSecurityDecision
from services.security_intelligence_service import (
    SecurityIntelligenceService,
    build_canonical_security_intelligence_inputs,
)
from services.security_master_service import production_security_master
from services.signal_intelligence_contract import SignalIntelligenceContext, empty_signal_context
from services.signal_intelligence_service import SignalIntelligenceService


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
    sector_theme: Optional[str]
    industry: Optional[str]
    country: Optional[str]
    candidate_id: Optional[str]
    has_candidate: bool
    has_participation_snapshot: bool
    security_intelligence_overall: Optional[float] = None
    security_intelligence_status: Optional[str] = None
    security_intelligence_state: Optional[str] = None
    security_intelligence_confidence: Optional[float] = None
    has_security_intelligence: bool = False
    security_intelligence_snapshot_id: Optional[str] = None
    security_intelligence_snapshot_as_of: Optional[str] = None
    has_persisted_security_intelligence: bool = False
    signal_context: Optional[SignalIntelligenceContext] = None
    portfolio_security_decision: Optional[PortfolioSecurityDecision] = None


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

    si_overall = None
    si_status = None
    si_state = None
    si_confidence = None
    has_si = False
    queue_row = None
    try:
        loaded_queue = UniverseExpansionRepository(client).get_by_symbol(normalized_symbol)
        queue_row = loaded_queue if isinstance(loaded_queue, dict) else None
    except Exception:
        queue_row = None
    security_resolution = None
    try:
        security_resolution = production_security_master(client).resolve_security(
            normalized_symbol
        )
    except Exception:
        security_resolution = None
    facts, si_participation = build_canonical_security_intelligence_inputs(
        normalized_symbol,
        candidate=candidate,
        participation_snapshot=participation,
        queue_row=queue_row,
        security_resolution=security_resolution,
        client=client,
    )
    si_view = SecurityIntelligenceService().evaluate(facts, si_participation)
    si_overall = si_view.overall_score
    si_status = si_view.overall_status
    si_state = si_view.investment_state
    si_confidence = si_view.overall_confidence
    has_si = True
    persisted = None
    try:
        persisted = SecurityIntelligenceSnapshotRepository(client).get_latest(
            normalized_symbol
        )
    except Exception:
        persisted = None

    from services.portfolio_security_decision_service import (
        evaluate_portfolio_security_for_symbol,
        fail_closed_portfolio_security_decision,
    )

    try:
        portfolio_security_decision = evaluate_portfolio_security_for_symbol(
            client, normalized_symbol
        )
    except Exception:
        portfolio_security_decision = fail_closed_portfolio_security_decision(
            normalized_symbol
        )

    return InvestmentIntelligenceView(
        symbol=normalized_symbol,
        market=(candidate or {}).get("market") or market,
        company_name=(candidate or {}).get("company_name"),
        decision=(candidate or {}).get("decision"),
        nabi_score=(candidate or {}).get("nabi_score"),
        participation_status=snapshot_status or candidate_participation_status,
        participation_score=snapshot_score or candidate_participation_score,
        research_status=(candidate or {}).get("research_status"),
        sector_theme=(candidate or {}).get("sector_theme"),
        industry=(candidate or {}).get("industry"),
        country=(candidate or {}).get("country"),
        candidate_id=(candidate or {}).get("id"),
        has_candidate=candidate is not None,
        has_participation_snapshot=participation is not None,
        security_intelligence_overall=si_overall,
        security_intelligence_status=si_status,
        security_intelligence_state=si_state,
        security_intelligence_confidence=si_confidence,
        has_security_intelligence=has_si,
        security_intelligence_snapshot_id=(persisted or {}).get("id"),
        security_intelligence_snapshot_as_of=(persisted or {}).get("as_of"),
        has_persisted_security_intelligence=persisted is not None,
        signal_context=SignalIntelligenceService().context_for(normalized_symbol),
        portfolio_security_decision=portfolio_security_decision,
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
        "sector_theme": view.sector_theme,
        "industry": view.industry,
        "country": view.country,
        "candidate_id": view.candidate_id,
        "has_candidate": view.has_candidate,
        "has_participation_snapshot": view.has_participation_snapshot,
        "security_intelligence_overall": view.security_intelligence_overall,
        "security_intelligence_status": view.security_intelligence_status,
        "security_intelligence_state": view.security_intelligence_state,
        "security_intelligence_confidence": view.security_intelligence_confidence,
        "has_security_intelligence": view.has_security_intelligence,
        "security_intelligence_snapshot_id": view.security_intelligence_snapshot_id,
        "security_intelligence_snapshot_as_of": view.security_intelligence_snapshot_as_of,
        "has_persisted_security_intelligence": view.has_persisted_security_intelligence,
        "signal_context": (
            view.signal_context.to_dict()
            if view.signal_context is not None
            else empty_signal_context(view.symbol).to_dict()
        ),
        "portfolio_security_decision": (
            view.portfolio_security_decision.to_dict()
            if view.portfolio_security_decision is not None
            else None
        ),
    }
