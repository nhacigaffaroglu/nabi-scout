from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple

AI_RESEARCH_SUMMARY_VERSION = "ai-research-summary-v1"
AI_RESEARCH_SUMMARY_DISPLAY_VERSION = "display-polish-v3"

SUMMARY_STATUSES = ("AVAILABLE", "UNAVAILABLE", "VALIDATION_FAILED")
EVIDENCE_LEVELS = ("STRONG", "MODERATE", "LIMITED")

EVIDENCE_LEVEL_LABELS_TR = {
    "STRONG": "Güçlü",
    "MODERATE": "Orta",
    "LIMITED": "Sınırlı",
}


@dataclass(frozen=True)
class AIResearchSummaryMetadata:
    context_semantic_identity: str
    validation_outcome: str
    latency_ms: Optional[int] = None
    llm_call_count: int = 0
    cache_hit: bool = False
    valuation_semantics: Optional[Dict[str, Any]] = None
    display_polish_version: str = AI_RESEARCH_SUMMARY_DISPLAY_VERSION

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "context_semantic_identity": self.context_semantic_identity,
            "validation_outcome": self.validation_outcome,
            "latency_ms": self.latency_ms,
            "llm_call_count": self.llm_call_count,
            "cache_hit": self.cache_hit,
            "display_polish_version": self.display_polish_version,
        }
        if self.valuation_semantics is not None:
            payload["valuation_semantics"] = dict(self.valuation_semantics)
        return payload


    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AIResearchSummaryMetadata":
        return cls(
            context_semantic_identity=str(payload.get("context_semantic_identity") or ""),
            validation_outcome=str(payload.get("validation_outcome") or ""),
            latency_ms=payload.get("latency_ms"),
            llm_call_count=int(payload.get("llm_call_count") or 0),
            cache_hit=bool(payload.get("cache_hit")),
            valuation_semantics=(
                dict(payload["valuation_semantics"])
                if payload.get("valuation_semantics")
                else None
            ),
            display_polish_version=str(
                payload.get("display_polish_version") or AI_RESEARCH_SUMMARY_DISPLAY_VERSION
            ),
        )


@dataclass(frozen=True)
class AIResearchSummaryView:
    symbol: str
    status: str
    evidence_level: str
    financial_outlook: str = ""
    valuation_summary: str = ""
    key_strengths: Tuple[str, ...] = ()
    key_weaknesses: Tuple[str, ...] = ()
    risks_to_watch: Tuple[str, ...] = ()
    missing_evidence: Tuple[str, ...] = ()
    monitoring_points: Tuple[str, ...] = ()
    limitations: Tuple[str, ...] = ()
    generated_at: Optional[str] = None
    model_provider: Optional[str] = None
    model_name: Optional[str] = None
    source_context_version: str = AI_RESEARCH_SUMMARY_VERSION
    user_message: str = ""
    metadata: Optional[AIResearchSummaryMetadata] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "status": self.status,
            "evidence_level": self.evidence_level,
            "financial_outlook": self.financial_outlook,
            "valuation_summary": self.valuation_summary,
            "key_strengths": list(self.key_strengths),
            "key_weaknesses": list(self.key_weaknesses),
            "risks_to_watch": list(self.risks_to_watch),
            "missing_evidence": list(self.missing_evidence),
            "monitoring_points": list(self.monitoring_points),
            "limitations": list(self.limitations),
            "generated_at": self.generated_at,
            "model_provider": self.model_provider,
            "model_name": self.model_name,
            "source_context_version": self.source_context_version,
            "user_message": self.user_message,
            "metadata": self.metadata.to_dict() if self.metadata else None,
        }

    @classmethod
    def unavailable(
        cls,
        *,
        symbol: str,
        message: str,
        evidence_level: str = "LIMITED",
    ) -> "AIResearchSummaryView":
        return cls(
            symbol=str(symbol or "").strip().upper(),
            status="UNAVAILABLE",
            evidence_level=evidence_level,
            user_message=message,
            limitations=(message,),
        )

    @classmethod
    def validation_failed(
        cls,
        *,
        symbol: str,
        message: str,
        evidence_level: str = "LIMITED",
        metadata: Optional[AIResearchSummaryMetadata] = None,
    ) -> "AIResearchSummaryView":
        return cls(
            symbol=str(symbol or "").strip().upper(),
            status="VALIDATION_FAILED",
            evidence_level=evidence_level,
            user_message=message,
            limitations=(message,),
            metadata=metadata,
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AIResearchSummaryView":
        metadata_payload = payload.get("metadata")
        metadata = (
            AIResearchSummaryMetadata.from_dict(metadata_payload)
            if isinstance(metadata_payload, Mapping)
            else None
        )
        return cls(
            symbol=str(payload.get("symbol") or "").strip().upper(),
            status=str(payload.get("status") or "UNAVAILABLE"),
            evidence_level=str(payload.get("evidence_level") or "LIMITED"),
            financial_outlook=str(payload.get("financial_outlook") or ""),
            valuation_summary=str(payload.get("valuation_summary") or ""),
            key_strengths=tuple(str(item) for item in (payload.get("key_strengths") or ())),
            key_weaknesses=tuple(str(item) for item in (payload.get("key_weaknesses") or ())),
            risks_to_watch=tuple(str(item) for item in (payload.get("risks_to_watch") or ())),
            missing_evidence=tuple(str(item) for item in (payload.get("missing_evidence") or ())),
            monitoring_points=tuple(str(item) for item in (payload.get("monitoring_points") or ())),
            limitations=tuple(str(item) for item in (payload.get("limitations") or ())),
            generated_at=payload.get("generated_at"),
            model_provider=payload.get("model_provider"),
            model_name=payload.get("model_name"),
            source_context_version=str(
                payload.get("source_context_version") or AI_RESEARCH_SUMMARY_VERSION
            ),
            user_message=str(payload.get("user_message") or ""),
            metadata=metadata,
        )
