from __future__ import annotations

from typing import Any, Dict

from services.participation_assessment_service import ParticipationAssessmentResult
from services.participation_source_evidence import participation_source_evidence_mapping


def resolve_expansion_candidate_company_name(
    result: ParticipationAssessmentResult,
    symbol: str,
) -> str:
    """Resolve a display company name for minimal candidate upsert.

    ``ParticipationAssessmentResult.source_evidence`` is provenance metadata
    (provider/cik/sec field keys), not an FMP profile dict. When no dedicated
    company name is exposed on the assessment result, fall back to the symbol.
    """
    normalized = str(symbol or result.symbol or "").strip().upper()
    # Safe read validates tuple/mapping contract without assuming fmp_profile.
    _ = participation_source_evidence_mapping(result.source_evidence)
    return normalized


def build_expansion_candidate_payload(
    result: ParticipationAssessmentResult,
    symbol: str,
) -> Dict[str, Any]:
    normalized = str(symbol or result.symbol or "").strip().upper()
    status = ""
    assessment = getattr(result, "participation_assessment", None)
    if assessment is not None:
        status = str(getattr(assessment, "status", "") or "").strip()
    payload = {
        "symbol": normalized,
        "market": "US",
        "asset_type": "equity",
        "company_name": resolve_expansion_candidate_company_name(result, normalized),
        "data_source": "universe_expansion",
    }
    if status:
        payload["participation_status"] = status
    return payload
