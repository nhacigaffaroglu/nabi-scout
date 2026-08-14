from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from services.company_intelligence_contract import CompanyIntelligenceView
from services.investment_thesis_builder import build_investment_thesis_view
from services.investment_thesis_change_engine import apply_change_summary
from services.investment_thesis_contract import (
    DecisionIntelligenceView,
    EvidenceCoverage,
    ExpectationTension,
    InvalidationCondition,
    InvestmentThesisView,
    MonitoringItem,
    THESIS_VERSION,
    ThesisAssumption,
    ThesisCatalyst,
    ThesisChangeItem,
    ThesisEvidence,
    ThesisRisk,
)
from services.research_eligibility_contract import ResearchEligibilityResult
from services.research_eligibility_service import require_research_allowed


def _tuple_from_dicts(items: Any, cls: Any) -> tuple:
    if not items:
        return ()
    result = []
    for item in items:
        if isinstance(item, cls):
            result.append(item)
            continue
        if not isinstance(item, dict):
            continue
        kwargs = {}
        for key, value in item.items():
            if key in {"evidence", "provenance"} and isinstance(value, dict):
                kwargs[key] = tuple(value.items())
            elif key in {"limitations", "linked_evidence_ids", "required_evidence"}:
                kwargs[key] = tuple(value or [])
            else:
                kwargs[key] = value
        result.append(cls(**kwargs))
    return tuple(result)


def thesis_view_from_dict(payload: Mapping[str, Any]) -> InvestmentThesisView:
    coverage = payload.get("evidence_coverage")
    evidence_coverage = None
    if isinstance(coverage, dict):
        evidence_coverage = EvidenceCoverage(**coverage)

    decision = payload.get("decision_intelligence")
    decision_intelligence = None
    if isinstance(decision, dict):
        decision_intelligence = DecisionIntelligenceView(**decision)

    return InvestmentThesisView(
        symbol=str(payload.get("symbol") or ""),
        company_name=payload.get("company_name"),
        as_of=payload.get("as_of"),
        thesis_version=str(payload.get("thesis_version") or ""),
        thesis_status=str(payload.get("thesis_status") or ""),
        thesis_summary=str(payload.get("thesis_summary") or ""),
        key_question=str(payload.get("key_question") or ""),
        supporting_evidence=_tuple_from_dicts(payload.get("supporting_evidence"), ThesisEvidence),
        weakening_evidence=_tuple_from_dicts(payload.get("weakening_evidence"), ThesisEvidence),
        risks=_tuple_from_dicts(payload.get("risks"), ThesisRisk),
        catalysts=_tuple_from_dicts(payload.get("catalysts"), ThesisCatalyst),
        invalidation_conditions=_tuple_from_dicts(
            payload.get("invalidation_conditions"),
            InvalidationCondition,
        ),
        assumptions=_tuple_from_dicts(payload.get("assumptions"), ThesisAssumption),
        valuation_context=str(payload.get("valuation_context") or ""),
        earnings_context=str(payload.get("earnings_context") or ""),
        peer_context=payload.get("peer_context"),
        news_context=payload.get("news_context"),
        expectation_tensions=_tuple_from_dicts(
            payload.get("expectation_tensions"),
            ExpectationTension,
        ),
        participation_context=payload.get("participation_context"),
        nabi_context=payload.get("nabi_context"),
        confidence=str(payload.get("confidence") or "LOW"),
        evidence_coverage=evidence_coverage,
        change_summary=_tuple_from_dicts(payload.get("change_summary"), ThesisChangeItem),
        monitoring_plan=_tuple_from_dicts(payload.get("monitoring_plan"), MonitoringItem),
        decision_intelligence=decision_intelligence,
        data_quality_notes=tuple(payload.get("data_quality_notes") or ()),
        provenance=tuple((payload.get("provenance") or {}).items())
        if isinstance(payload.get("provenance"), dict)
        else tuple(payload.get("provenance") or ()),
    )


class InvestmentThesisService:
    def build_view(
        self,
        intelligence_view: CompanyIntelligenceView,
        *,
        research_eligibility: ResearchEligibilityResult,
        candidate: Optional[Dict[str, Any]] = None,
        participation_context: Optional[str] = None,
        previous_snapshot: Optional[Mapping[str, Any]] = None,
    ) -> InvestmentThesisView:
        require_research_allowed(research_eligibility, symbol=intelligence_view.symbol)
        view = build_investment_thesis_view(
            intelligence_view,
            candidate=candidate,
            participation_context=participation_context,
        )
        return apply_change_summary(view, previous_snapshot)

    def blocked_view(
        self,
        *,
        symbol: str,
        research_eligibility: ResearchEligibilityResult,
    ) -> InvestmentThesisView:
        return InvestmentThesisView(
            symbol=str(symbol or "").strip().upper(),
            company_name=None,
            as_of=None,
            thesis_version=THESIS_VERSION,
            thesis_status="INSUFFICIENT_DATA",
            thesis_summary=research_eligibility.block_message,
            key_question="Katılım uygunluğu doğrulanmadan tez üretilmez.",
            supporting_evidence=(),
            weakening_evidence=(),
            risks=(),
            catalysts=(),
            invalidation_conditions=(),
            assumptions=(),
            valuation_context="",
            earnings_context="",
            peer_context=None,
            news_context=None,
            expectation_tensions=(),
            participation_context=research_eligibility.participation_status,
            nabi_context=None,
            confidence="LOW",
            evidence_coverage=EvidenceCoverage(
                financials="unavailable",
                earnings="unavailable",
                valuation="unavailable",
                peers="unavailable",
                news="unavailable",
                participation="unavailable",
            ),
            change_summary=(),
            monitoring_plan=(),
            decision_intelligence=None,
            data_quality_notes=research_eligibility.limitations,
            provenance=(("gate", "research_eligibility"),),
        )
