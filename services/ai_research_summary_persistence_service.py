from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional, Tuple

from repositories.ai_research_summary_repository import AIResearchSummaryRepository
from services.ai_research_summary_contract import (
    AI_RESEARCH_SUMMARY_DISPLAY_VERSION,
    AI_RESEARCH_SUMMARY_VERSION,
    AIResearchSummaryMetadata,
    AIResearchSummaryView,
)
from services.wealth_adviser_prompt import FORBIDDEN_KEY_FRAGMENTS

AI_SUMMARY_VALIDATION_VERSION = "ai-summary-validator-v1"

PERSISTENCE_HISTORY_UNAVAILABLE_MESSAGE = (
    "AI araştırma özeti geçmişi şu anda yüklenemedi. Veritabanı kaydı kullanılamıyor."
)
PERSISTENCE_SAVE_FAILED_MESSAGE = (
    "AI araştırma özeti kaydedilemedi. Veritabanı kaydı kullanılamıyor."
)


@dataclass(frozen=True)
class SaveAIResearchSummaryResult:
    saved: bool
    skipped_duplicate: bool = False
    persistence_failed: bool = False
    row: Optional[Dict[str, Any]] = None
    message: str = ""


@dataclass(frozen=True)
class AIResearchSummaryHistoryResult:
    history: Tuple[Dict[str, Any], ...] = field(default_factory=tuple)
    available: bool = True
    message: str = ""


@dataclass(frozen=True)
class ExactAIResearchSummaryResult:
    view: Optional[AIResearchSummaryView] = None
    row: Optional[Dict[str, Any]] = None
    available: bool = True
    message: str = ""


def _normalize_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper()


def _tuple_field(values: Any) -> Tuple[str, ...]:
    if not values:
        return ()
    if isinstance(values, tuple):
        return tuple(str(item) for item in values)
    return tuple(str(item) for item in values)


def build_snapshot_payload(
    view: AIResearchSummaryView,
    *,
    semantic_identity: str,
    generated_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    if view.status != "AVAILABLE":
        raise ValueError("Only AVAILABLE AI research summaries may be persisted.")
    timestamp = generated_at
    if timestamp is None:
        if view.generated_at:
            try:
                timestamp = datetime.fromisoformat(
                    str(view.generated_at).replace("Z", "+00:00")
                )
            except ValueError:
                timestamp = datetime.now(timezone.utc)
        else:
            timestamp = datetime.now(timezone.utc)
    audit_persisted_summary_payload(view.to_dict())
    return {
        "symbol": _normalize_symbol(view.symbol),
        "semantic_identity": str(semantic_identity or "").strip(),
        "source_context_version": view.source_context_version or AI_RESEARCH_SUMMARY_VERSION,
        "summary_version": AI_RESEARCH_SUMMARY_VERSION,
        "status": view.status,
        "evidence_level": view.evidence_level,
        "model_provider": view.model_provider,
        "model_name": view.model_name,
        "generated_at": timestamp.isoformat(),
        "summary_payload": view.to_dict(),
        "display_version": AI_RESEARCH_SUMMARY_DISPLAY_VERSION,
        "validation_version": AI_SUMMARY_VALIDATION_VERSION,
    }


def audit_persisted_summary_payload(payload: Mapping[str, Any]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False).lower()
    forbidden = (
        *FORBIDDEN_KEY_FRAGMENTS,
        "authorization",
        "bearer ",
        "raw prompt",
        "raw_llm",
        "raw response",
        "api_key",
        "secret",
        "password",
    )
    for fragment in forbidden:
        if fragment in serialized:
            raise ValueError(f"Persisted AI summary payload contains forbidden fragment: {fragment}")


def snapshot_from_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "symbol": row.get("symbol"),
        "semantic_identity": row.get("semantic_identity"),
        "source_context_version": row.get("source_context_version"),
        "summary_version": row.get("summary_version"),
        "status": row.get("status"),
        "evidence_level": row.get("evidence_level"),
        "model_provider": row.get("model_provider"),
        "model_name": row.get("model_name"),
        "generated_at": row.get("generated_at"),
        "summary_payload": row.get("summary_payload") or {},
        "display_version": row.get("display_version"),
        "validation_version": row.get("validation_version"),
        "created_at": row.get("created_at"),
    }


def view_from_row(
    row: Mapping[str, Any],
    *,
    semantic_identity: Optional[str] = None,
) -> AIResearchSummaryView:
    payload = row.get("summary_payload") or {}
    view = AIResearchSummaryView.from_dict(payload)
    identity = semantic_identity or row.get("semantic_identity")
    metadata = view.metadata or AIResearchSummaryMetadata(
        context_semantic_identity=str(identity or ""),
        validation_outcome="persisted",
        llm_call_count=0,
    )
    return AIResearchSummaryView(
        symbol=view.symbol,
        status=view.status,
        evidence_level=view.evidence_level,
        financial_outlook=view.financial_outlook,
        valuation_summary=view.valuation_summary,
        key_strengths=view.key_strengths,
        key_weaknesses=view.key_weaknesses,
        risks_to_watch=view.risks_to_watch,
        missing_evidence=view.missing_evidence,
        monitoring_points=view.monitoring_points,
        limitations=view.limitations,
        generated_at=view.generated_at or str(row.get("generated_at") or ""),
        model_provider=view.model_provider or row.get("model_provider"),
        model_name=view.model_name or row.get("model_name"),
        source_context_version=view.source_context_version,
        user_message=view.user_message,
        metadata=AIResearchSummaryMetadata(
            context_semantic_identity=str(identity or metadata.context_semantic_identity),
            validation_outcome="persisted",
            latency_ms=metadata.latency_ms,
            llm_call_count=0,
            cache_hit=False,
            valuation_semantics=metadata.valuation_semantics,
            display_polish_version=metadata.display_polish_version,
        ),
    )


def save_ai_research_summary_snapshot(
    repo: AIResearchSummaryRepository,
    view: AIResearchSummaryView,
    *,
    semantic_identity: str,
) -> SaveAIResearchSummaryResult:
    if view.status != "AVAILABLE":
        return SaveAIResearchSummaryResult(
            saved=False,
            message="Yalnızca doğrulanmış AVAILABLE özetler kaydedilebilir.",
        )
    payload = build_snapshot_payload(view, semantic_identity=semantic_identity)
    try:
        existing = repo.get_exact(payload["symbol"], payload["semantic_identity"])
        if existing is not None:
            return SaveAIResearchSummaryResult(
                saved=False,
                skipped_duplicate=True,
                row=existing,
                message="Bu AI araştırma özeti zaten kayıtlı; tekrar eklenmedi.",
            )
        row, inserted = repo.save_if_absent(payload)
    except Exception:
        return SaveAIResearchSummaryResult(
            saved=False,
            persistence_failed=True,
            message=PERSISTENCE_SAVE_FAILED_MESSAGE,
        )
    if inserted:
        return SaveAIResearchSummaryResult(
            saved=True,
            row=row,
            message="AI araştırma özeti kaydedildi.",
        )
    return SaveAIResearchSummaryResult(
        saved=False,
        skipped_duplicate=True,
        row=row,
        message="Bu AI araştırma özeti zaten kayıtlı; tekrar eklenmedi.",
    )


def fetch_exact_ai_research_summary(
    repo: AIResearchSummaryRepository,
    symbol: str,
    semantic_identity: str,
) -> ExactAIResearchSummaryResult:
    try:
        row = repo.get_exact(symbol, semantic_identity)
    except Exception:
        return ExactAIResearchSummaryResult(
            available=False,
            message=PERSISTENCE_HISTORY_UNAVAILABLE_MESSAGE,
        )
    if row is None:
        return ExactAIResearchSummaryResult(available=True)
    if row.get("status") != "AVAILABLE":
        return ExactAIResearchSummaryResult(available=True)
    return ExactAIResearchSummaryResult(
        view=view_from_row(row, semantic_identity=semantic_identity),
        row=row,
        available=True,
    )


def fetch_ai_research_summary_history(
    repo: AIResearchSummaryRepository,
    symbol: str,
    *,
    limit: int = 10,
) -> AIResearchSummaryHistoryResult:
    try:
        rows = repo.get_recent_history(symbol, limit=limit)
    except Exception:
        return AIResearchSummaryHistoryResult(
            history=(),
            available=False,
            message=PERSISTENCE_HISTORY_UNAVAILABLE_MESSAGE,
        )
    return AIResearchSummaryHistoryResult(
        history=tuple(snapshot_from_row(row) for row in rows),
        available=True,
    )


def symbol_has_stale_persisted_summary(
    repo: AIResearchSummaryRepository,
    symbol: str,
    current_semantic_identity: str,
) -> bool:
    try:
        latest = repo.get_latest(symbol)
    except Exception:
        return False
    if latest is None:
        return False
    return str(latest.get("semantic_identity") or "") != str(current_semantic_identity or "")
