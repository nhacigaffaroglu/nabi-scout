from __future__ import annotations

from typing import Tuple

from services.portfolio_ai_adviser_contract import PortfolioAIAdviserResponse


def _trim(text: str, *, max_len: int = 1200) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 1].rstrip() + "…"


def _polish_tuple(values: Tuple[str, ...], *, max_items: int = 6) -> Tuple[str, ...]:
    rows = []
    for item in values[:max_items]:
        cleaned = _trim(item, max_len=500)
        if cleaned:
            rows.append(cleaned)
    return tuple(rows)


def polish_portfolio_ai_response(response: PortfolioAIAdviserResponse) -> PortfolioAIAdviserResponse:
    if response.status != "AVAILABLE":
        return response
    return PortfolioAIAdviserResponse(
        portfolio_id=response.portfolio_id,
        status=response.status,
        evidence_level=response.evidence_level,
        executive_summary=_trim(response.executive_summary),
        what_changed=_polish_tuple(response.what_changed),
        portfolio_implications=_polish_tuple(response.portfolio_implications),
        thesis_watch=_polish_tuple(response.thesis_watch),
        participation_watch=_polish_tuple(response.participation_watch),
        research_gaps=_polish_tuple(response.research_gaps),
        questions_to_review=_polish_tuple(response.questions_to_review),
        limitations=_polish_tuple(response.limitations),
        evidence_references=_polish_tuple(response.evidence_references, max_items=10),
        generated_at=response.generated_at,
        model_provider=response.model_provider,
        model_name=response.model_name,
        source_context_version=response.source_context_version,
        user_message=response.user_message,
        metadata=response.metadata,
    )
