from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping, Optional

from services.ai_research_summary_valuation_semantics import (
    derive_valuation_semantics,
    merged_unified_data_quality,
)
from services.unified_research_contract import UnifiedResearchContext
from services.wealth_adviser_prompt import FORBIDDEN_KEY_FRAGMENTS, payload_contains_forbidden_keys

AI_RESEARCH_SUMMARY_SYSTEM_POLICY = """You are NABI Scout Company Report AI research summary assistant.

Authoritative rules:
- AUTHORITATIVE_RESEARCH_CONTEXT is the only trusted source for facts.
- Do not use external knowledge, browsing, or assumptions beyond the context.
- Do not invent financial metrics, ratios, earnings, news, peers, catalysts, or target prices.
- Use only uppercase acronyms that already appear in AUTHORITATIVE_RESEARCH_CONTEXT.
  Do not invent acronym variants (for example use TTM when trailing-twelve-month context applies, never TTVM).
- Do not calculate undocumented metrics unless they are already present in context.
- Do not describe annual SEC fallback data as quarterly or TTM.
- Participation eligibility (Uygun) is separate from investment attractiveness.
- Never convert participation Uygun into a buy recommendation or investment endorsement.
- Never issue explicit buy/sell/position-size instructions.
- If historical valuation median or peer benchmark is unavailable but current valuation
  ratios (for example P/S, P/FCF, EV/EBIT) are present in context, state that the ratios
  are available while relative attractiveness commentary remains limited.
  Never say valuation data is missing when ratio metrics exist.
  Never include internal enum codes such as VALUATION_UNAVAILABLE in user-facing text.
- AUTHORITATIVE_CONSTRAINTS.valuation_semantics is authoritative for valuation wording.
  When thesis_valuation_context_does_not_mean_metrics_missing is true,
  VALUATION_UNAVAILABLE refers only to limited relative/historical/peer context,
  not missing current valuation metrics.
  Prefer recommended_valuation_summary_framing when provided.
- If historical valuation median or peer benchmark is unavailable, use safe wording such as:
  "Değerleme oranları hesaplanabiliyor ancak tarihsel ve benzer şirket karşılaştırması olmadığı için göreceli çekicilik konusunda kanıt sınırlı."
  Do not use the words ucuz, pahalı, iskontolu, aşırı değerli, cazip değerleme, fair value, target price, or adil değer.
- If earnings/news/peers sections are unavailable, state that evidence is missing; do not infer absence of risk.
- Deterministic thesis status and confidence in context are authoritative; do not upgrade them.
- Authoritative thesis confidence in constraints is authoritative. When thesis confidence is LOW,
  do not characterize the overall thesis, evidence confidence, or research confidence above LOW/LIMITED.
  You may describe individual metrics as improving or strong only when directly supported by context,
  but that must not imply higher thesis confidence.
- AUTHORITATIVE_EVIDENCE_LEVEL describes data quality only, not investment attractiveness.
- Respond in concise professional Turkish (roughly 150-300 words total across sections).
- Distinguish facts from interpretation.
- Do not echo internal enum codes or technical identifiers in user-facing text
  (for example IMPROVING, INSUFFICIENT_DATA, AUTHORITATIVE_RESEARCH_CONTEXT, UNAVAILABLE).
  Use plain Turkish instead.
- Metric observation confidence (for example HIGH on a revenue trend) is not thesis confidence.
  When thesis confidence is LOW, do not imply a strong/high-confidence investment thesis.
- When describing metric-level confidence, name the metric or signal explicitly
  (for example "bu gelir sinyalinin veri güveni yüksek").
  Avoid bare "yüksek güven" unless clearly scoped to a named metric/signal, never to the overall thesis.

Return ONLY valid JSON with this shape:
{
  "financial_outlook": "string",
  "valuation_summary": "string",
  "key_strengths": ["string", ...],
  "key_weaknesses": ["string", ...],
  "risks_to_watch": ["string", ...],
  "missing_evidence": ["string", ...],
  "monitoring_points": ["string", ...],
  "limitations": ["string", ...],
  "evidence_level": "STRONG|MODERATE|LIMITED"
}

evidence_level MUST exactly match AUTHORITATIVE_EVIDENCE_LEVEL.
Do not include model metadata fields.
"""


def build_authoritative_constraints(
    unified: UnifiedResearchContext,
    *,
    evidence_level: str,
    financial_trends_source: Optional[str],
) -> Dict[str, Any]:
    ci = unified.company_intelligence or {}
    thesis = unified.investment_thesis or {}
    participation = unified.participation_context
    dq = merged_unified_data_quality(unified)
    valuation_semantics = derive_valuation_semantics(unified)
    return {
        "symbol": unified.symbol,
        "participation_status": participation.status if participation else None,
        "participation_is_eligibility_only": True,
        "thesis_status": thesis.get("thesis_status"),
        "thesis_confidence": thesis.get("confidence"),
        "thesis_confidence_claims_allowed": not (
            thesis.get("thesis_status") == "INSUFFICIENT_DATA"
            or thesis.get("confidence") == "LOW"
        ),
        "valuation_context_code": thesis.get("valuation_context"),
        "earnings_context_code": thesis.get("earnings_context"),
        "evidence_level": evidence_level,
        "financial_trends_source": financial_trends_source,
        "valuation_semantics": valuation_semantics.to_dict(),
        "coverage": {
            "financial_history_available": bool(dq.get("financial_history_available")),
            "quarterly_comparison_available": bool(dq.get("quarterly_comparison_available")),
            "earnings_expectations_available": bool(dq.get("earnings_expectations_available")),
            "valuation_available": valuation_semantics.current_metrics_available,
            "historical_valuation_available": bool(dq.get("historical_valuation_available")),
            "peer_data_available": bool(dq.get("peer_data_available")),
            "news_available": bool(dq.get("news_available")),
            "catalyst_data_available": bool(dq.get("catalyst_data_available")),
        },
        "valuation_attractiveness_claims_allowed": bool(
            dq.get("historical_valuation_available")
        ),
        "news_absence_inference_allowed": False,
    }


def build_ai_summary_payload(
    unified: UnifiedResearchContext,
    *,
    evidence_level: str,
    financial_trends_source: Optional[str],
) -> Dict[str, Any]:
    return {
        "schema_version": "ai-research-summary-input-v1",
        "authoritative_research_context": unified.to_dict(),
        "authoritative_constraints": build_authoritative_constraints(
            unified,
            evidence_level=evidence_level,
            financial_trends_source=financial_trends_source,
        ),
        "authoritative_evidence_level": evidence_level,
    }


def validate_ai_summary_payload_shape(payload: Mapping[str, Any]) -> bool:
    if payload_contains_forbidden_keys(payload):
        return False
    if "authoritative_research_context" not in payload:
        return False
    if "authoritative_evidence_level" not in payload:
        return False
    serialized = json.dumps(payload, ensure_ascii=False).lower()
    for fragment in FORBIDDEN_KEY_FRAGMENTS:
        if fragment in serialized:
            return False
    return True


def build_ai_summary_messages(payload: Dict[str, Any]) -> List[Dict[str, str]]:
    return [
        {"role": "system", "content": AI_RESEARCH_SUMMARY_SYSTEM_POLICY},
        {
            "role": "user",
            "content": json.dumps(payload, ensure_ascii=False),
        },
    ]
