from __future__ import annotations

from typing import Any, Dict, List, Optional

from services.company_intelligence_contract import CompanyIntelligenceView
from services.investment_thesis_contract import InvestmentThesisView

MAX_THESIS_EVIDENCE = 5
MAX_RISKS = 5
MAX_CATALYSTS = 5
MAX_NEWS = 3
MAX_MONITORING = 8
MAX_CHANGE_ITEMS = 8


def _compact_observations(section: Any, limit: int = 6) -> List[Dict[str, Any]]:
    if section is None:
        return []
    observations = getattr(section, "observations", ()) or ()
    return [
        {
            "code": item.code,
            "statement": item.statement,
            "direction": item.direction,
            "period": item.period,
            "confidence": item.confidence,
        }
        for item in observations[:limit]
    ]


def serialize_company_intelligence_for_adviser(
    view: Optional[CompanyIntelligenceView],
) -> Optional[Dict[str, Any]]:
    if view is None:
        return None
    material_news = []
    if view.news:
        for event in view.news.events:
            if event.materiality != "MATERIAL":
                continue
            material_news.append(
                {
                    "headline": event.headline,
                    "category": event.category,
                    "published_at": event.published_at,
                    "impact_domains": list(event.impact_domains),
                    "confidence": event.confidence,
                }
            )
            if len(material_news) >= MAX_NEWS:
                break
    valuation_metrics = []
    if view.valuation:
        for metric in view.valuation.metrics[:5]:
            if not metric.meaningful:
                continue
            valuation_metrics.append(
                {
                    "code": metric.code,
                    "label": metric.label,
                    "current_value": metric.current_value,
                    "position": metric.position,
                    "premium_to_median_pct": metric.premium_to_median_pct,
                }
            )
    return {
        "symbol": view.symbol,
        "company_name": view.company_name,
        "as_of": view.as_of,
        "financial_observations": _compact_observations(view.financial_trends),
        "earnings_observations": _compact_observations(view.earnings),
        "valuation_metrics": valuation_metrics,
        "valuation_observations": _compact_observations(view.valuation, limit=3),
        "peer_observations": _compact_observations(view.peers, limit=4),
        "peer_limitations": list(view.peers.limitations) if view.peers else [],
        "material_news": material_news,
        "factual_risks": [
            {"code": item.code, "statement": item.statement}
            for item in view.factual_risks[:MAX_RISKS]
        ],
        "catalysts": [
            item.to_dict() for item in view.catalysts[:MAX_CATALYSTS]
        ],
        "data_quality": view.data_quality.to_dict() if view.data_quality else {},
    }


def serialize_investment_thesis_for_adviser(
    view: Optional[InvestmentThesisView],
) -> Optional[Dict[str, Any]]:
    if view is None:
        return None
    return {
        "symbol": view.symbol,
        "thesis_status": view.thesis_status,
        "confidence": view.confidence,
        "thesis_summary": view.thesis_summary,
        "key_question": view.key_question,
        "valuation_context": view.valuation_context,
        "earnings_context": view.earnings_context,
        "supporting_evidence": [
            {"code": item.code, "statement": item.statement, "category": item.category}
            for item in view.supporting_evidence[:MAX_THESIS_EVIDENCE]
        ],
        "weakening_evidence": [
            {"code": item.code, "statement": item.statement, "category": item.category}
            for item in view.weakening_evidence[:MAX_THESIS_EVIDENCE]
        ],
        "risks": [
            {"risk_id": item.risk_id, "code": item.code, "statement": item.statement}
            for item in view.risks[:MAX_RISKS]
        ],
        "catalysts": [
            {
                "catalyst_id": item.catalyst_id,
                "description": item.description,
                "expected_date": item.expected_date,
                "status": item.status,
            }
            for item in view.catalysts[:MAX_CATALYSTS]
        ],
        "invalidation_conditions": [
            {
                "condition_id": item.condition_id,
                "code": item.code,
                "statement": item.statement,
            }
            for item in view.invalidation_conditions[:MAX_MONITORING]
        ],
        "assumptions": [
            {
                "assumption_id": item.assumption_id,
                "statement": item.statement,
                "status": item.status,
            }
            for item in view.assumptions[:5]
        ],
        "expectation_tensions": [
            {"code": item.code, "statement": item.statement}
            for item in view.expectation_tensions[:3]
        ],
        "change_summary": [
            item.to_dict() for item in view.change_summary[:MAX_CHANGE_ITEMS]
        ],
        "monitoring_plan": [
            item.to_dict() for item in view.monitoring_plan[:MAX_MONITORING]
        ],
        "evidence_coverage": (
            view.evidence_coverage.to_dict() if view.evidence_coverage else {}
        ),
        "nabi_context_note": view.nabi_context,
    }
