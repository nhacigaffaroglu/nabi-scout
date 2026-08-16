from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional, Tuple

PORTFOLIO_AI_CONTEXT_VERSION = "portfolio_ai_context_v1"
PORTFOLIO_AI_SUMMARY_VERSION = "portfolio_ai_summary_v1"
PORTFOLIO_AI_DISPLAY_VERSION = "portfolio_ai_display_v1"
PORTFOLIO_AI_VALIDATION_VERSION = "portfolio_ai_validator_v1"


@dataclass(frozen=True)
class PortfolioAIAdviserMetadata:
    context_semantic_identity: str
    validation_outcome: str
    llm_call_count: int = 0
    cache_hit: bool = False
    latency_ms: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PortfolioAIAdviserResponse:
    portfolio_id: str
    status: str
    evidence_level: str
    executive_summary: str = ""
    what_changed: Tuple[str, ...] = ()
    portfolio_implications: Tuple[str, ...] = ()
    thesis_watch: Tuple[str, ...] = ()
    participation_watch: Tuple[str, ...] = ()
    research_gaps: Tuple[str, ...] = ()
    questions_to_review: Tuple[str, ...] = ()
    limitations: Tuple[str, ...] = ()
    evidence_references: Tuple[str, ...] = ()
    generated_at: str = ""
    model_provider: Optional[str] = None
    model_name: Optional[str] = None
    source_context_version: str = PORTFOLIO_AI_CONTEXT_VERSION
    user_message: str = ""
    metadata: Optional[PortfolioAIAdviserMetadata] = None

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "portfolio_id": self.portfolio_id,
            "status": self.status,
            "evidence_level": self.evidence_level,
            "executive_summary": self.executive_summary,
            "what_changed": list(self.what_changed),
            "portfolio_implications": list(self.portfolio_implications),
            "thesis_watch": list(self.thesis_watch),
            "participation_watch": list(self.participation_watch),
            "research_gaps": list(self.research_gaps),
            "questions_to_review": list(self.questions_to_review),
            "limitations": list(self.limitations),
            "evidence_references": list(self.evidence_references),
            "generated_at": self.generated_at,
            "model_provider": self.model_provider,
            "model_name": self.model_name,
            "source_context_version": self.source_context_version,
            "user_message": self.user_message,
        }
        if self.metadata is not None:
            payload["metadata"] = self.metadata.to_dict()
        return payload

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "PortfolioAIAdviserResponse":
        metadata_payload = payload.get("metadata")
        metadata = None
        if isinstance(metadata_payload, dict):
            metadata = PortfolioAIAdviserMetadata(
                context_semantic_identity=str(
                    metadata_payload.get("context_semantic_identity") or ""
                ),
                validation_outcome=str(metadata_payload.get("validation_outcome") or ""),
                llm_call_count=int(metadata_payload.get("llm_call_count") or 0),
                cache_hit=bool(metadata_payload.get("cache_hit")),
                latency_ms=metadata_payload.get("latency_ms"),
            )
        return cls(
            portfolio_id=str(payload.get("portfolio_id") or ""),
            status=str(payload.get("status") or "UNAVAILABLE"),
            evidence_level=str(payload.get("evidence_level") or "LIMITED"),
            executive_summary=str(payload.get("executive_summary") or ""),
            what_changed=tuple(str(item) for item in (payload.get("what_changed") or ())),
            portfolio_implications=tuple(
                str(item) for item in (payload.get("portfolio_implications") or ())
            ),
            thesis_watch=tuple(str(item) for item in (payload.get("thesis_watch") or ())),
            participation_watch=tuple(
                str(item) for item in (payload.get("participation_watch") or ())
            ),
            research_gaps=tuple(str(item) for item in (payload.get("research_gaps") or ())),
            questions_to_review=tuple(
                str(item) for item in (payload.get("questions_to_review") or ())
            ),
            limitations=tuple(str(item) for item in (payload.get("limitations") or ())),
            evidence_references=tuple(
                str(item) for item in (payload.get("evidence_references") or ())
            ),
            generated_at=str(payload.get("generated_at") or ""),
            model_provider=payload.get("model_provider"),
            model_name=payload.get("model_name"),
            source_context_version=str(
                payload.get("source_context_version") or PORTFOLIO_AI_CONTEXT_VERSION
            ),
            user_message=str(payload.get("user_message") or ""),
            metadata=metadata,
        )

    @classmethod
    def unavailable(cls, *, portfolio_id: str, message: str) -> "PortfolioAIAdviserResponse":
        return cls(
            portfolio_id=portfolio_id,
            status="UNAVAILABLE",
            evidence_level="LIMITED",
            user_message=message,
            limitations=(message,),
        )

    @classmethod
    def validation_failed(
        cls,
        *,
        portfolio_id: str,
        message: str,
    ) -> "PortfolioAIAdviserResponse":
        return cls(
            portfolio_id=portfolio_id,
            status="VALIDATION_FAILED",
            evidence_level="LIMITED",
            user_message=message,
            limitations=(message,),
        )
