from __future__ import annotations

from typing import Any, Mapping, Optional

from services.ai_research_summary_contract import AIResearchSummaryView
from services.ai_research_summary_valuation_semantics import ValuationSemantics
from services.company_intelligence_contract import CompanyIntelligenceView
from services.investment_thesis_contract import InvestmentThesisView
from services.unified_research_contract import UnifiedResearchContext

_LAST_TRACE: Optional[dict[str, Any]] = None


def _metric_rows(view: Optional[CompanyIntelligenceView]) -> list[dict[str, Any]]:
    if view is None or view.valuation is None:
        return []
    rows: list[dict[str, Any]] = []
    for metric in view.valuation.metrics:
        rows.append(
            {
                "code": metric.code,
                "label": metric.label,
                "current_value": metric.current_value,
                "meaningful": metric.meaningful,
                "source_provider": metric.source_provider,
                "data_family": metric.data_family,
                "alignment_status": metric.alignment_status,
            }
        )
    return rows


def _valuation_payload_slice(payload: Mapping[str, Any]) -> dict[str, Any]:
    constraints = payload.get("authoritative_constraints") or {}
    context = payload.get("authoritative_research_context") or {}
    ci = context.get("company_intelligence") or {}
    return {
        "valuation_semantics": constraints.get("valuation_semantics"),
        "coverage": constraints.get("coverage"),
        "company_intelligence_valuation_metrics": ci.get("valuation_metrics"),
        "company_intelligence_data_quality": ci.get("data_quality"),
        "context_data_quality": context.get("data_quality"),
        "investment_thesis_valuation_context": (context.get("investment_thesis") or {}).get(
            "valuation_context"
        ),
    }


def capture_ai_summary_generation_trace(
    *,
    company_intelligence_view: CompanyIntelligenceView,
    investment_thesis_view: InvestmentThesisView,
    unified: UnifiedResearchContext,
    valuation_semantics: ValuationSemantics,
    payload: Mapping[str, Any],
    raw_llm_response: Optional[str] = None,
    parsed_valuation_summary: Optional[str] = None,
    final_valuation_summary: Optional[str] = None,
    validation_failure: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    global _LAST_TRACE
    ci = unified.company_intelligence or {}
    dq = company_intelligence_view.data_quality
    trace = {
        "company_intel_view": {
            "symbol": company_intelligence_view.symbol,
            "valuation_metrics": _metric_rows(company_intelligence_view),
            "valuation_available": dq.valuation_available if dq else None,
            "historical_valuation_available": dq.historical_valuation_available if dq else None,
            "provider_failures": list(dq.provider_failures) if dq else [],
            "valuation_provenance": (
                company_intelligence_view.valuation.provenance.to_dict()
                if company_intelligence_view.valuation
                else None
            ),
        },
        "investment_thesis_view": {
            "valuation_context": investment_thesis_view.valuation_context,
            "confidence": investment_thesis_view.confidence,
            "thesis_status": investment_thesis_view.thesis_status,
        },
        "unified_research_context": {
            "valuation_metrics": ci.get("valuation_metrics"),
            "data_quality": unified.data_quality,
            "company_intelligence_data_quality": ci.get("data_quality"),
        },
        "valuation_semantics": valuation_semantics.to_dict(),
        "prompt_valuation_payload": _valuation_payload_slice(payload),
        "raw_llm_valuation_summary": raw_llm_response,
        "parsed_valuation_summary": parsed_valuation_summary,
        "final_valuation_summary": final_valuation_summary,
        "validation_failure": dict(validation_failure) if validation_failure else None,
    }
    _LAST_TRACE = trace
    return trace


def get_last_ai_summary_generation_trace() -> Optional[dict[str, Any]]:
    return _LAST_TRACE


def trace_from_view(view: AIResearchSummaryView) -> Optional[dict[str, Any]]:
    if view.metadata is None:
        return None
    semantics = view.metadata.valuation_semantics
    if semantics is None:
        return None
    return {
        "stored_valuation_semantics": semantics,
        "final_valuation_summary": view.valuation_summary,
        "validation_outcome": view.metadata.validation_outcome,
    }
