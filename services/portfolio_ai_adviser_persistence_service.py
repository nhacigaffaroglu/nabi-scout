from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional

from repositories.portfolio_ai_adviser_repository import PortfolioAIAdviserRepository
from services.portfolio_ai_adviser_contract import (
    PORTFOLIO_AI_DISPLAY_VERSION,
    PORTFOLIO_AI_SUMMARY_VERSION,
    PORTFOLIO_AI_VALIDATION_VERSION,
    PortfolioAIAdviserResponse,
)
from services.wealth_adviser_prompt import FORBIDDEN_KEY_FRAGMENTS


@dataclass(frozen=True)
class SavePortfolioAIResult:
    saved: bool
    skipped_duplicate: bool = False
    persistence_failed: bool = False
    row: Optional[Dict[str, Any]] = None
    message: str = ""


def audit_persisted_portfolio_ai_payload(payload: Mapping[str, Any]) -> None:
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
            raise ValueError(f"Persisted portfolio AI payload contains forbidden fragment: {fragment}")


def build_snapshot_payload(
    response: PortfolioAIAdviserResponse,
    *,
    user_id: str,
    portfolio_id: str,
    semantic_identity: str,
    generated_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    if response.status != "AVAILABLE":
        raise ValueError("Only AVAILABLE portfolio AI responses may be persisted.")
    timestamp = generated_at or datetime.now(timezone.utc)
    audit_persisted_portfolio_ai_payload(response.to_dict())
    return {
        "user_id": user_id,
        "portfolio_id": portfolio_id,
        "semantic_identity": semantic_identity,
        "context_version": response.source_context_version,
        "summary_version": PORTFOLIO_AI_SUMMARY_VERSION,
        "status": response.status,
        "evidence_level": response.evidence_level,
        "model_provider": response.model_provider,
        "model_name": response.model_name,
        "generated_at": timestamp.isoformat(),
        "response_payload": response.to_dict(),
        "display_version": PORTFOLIO_AI_DISPLAY_VERSION,
        "validation_version": PORTFOLIO_AI_VALIDATION_VERSION,
    }


def view_from_row(row: Mapping[str, Any]) -> PortfolioAIAdviserResponse:
    payload = row.get("response_payload") or {}
    return PortfolioAIAdviserResponse.from_dict(payload)


def save_portfolio_ai_snapshot(
    repo: PortfolioAIAdviserRepository,
    response: PortfolioAIAdviserResponse,
    *,
    user_id: str,
    portfolio_id: str,
    semantic_identity: str,
) -> SavePortfolioAIResult:
    try:
        payload = build_snapshot_payload(
            response,
            user_id=user_id,
            portfolio_id=portfolio_id,
            semantic_identity=semantic_identity,
        )
        existing = repo.get_exact(user_id, portfolio_id, semantic_identity)
        if existing is not None:
            return SavePortfolioAIResult(
                saved=False,
                skipped_duplicate=True,
                row=existing,
                message="Bu AI portföy değerlendirmesi zaten kayıtlı.",
            )
        row, inserted = repo.save_if_absent(payload)
        return SavePortfolioAIResult(
            saved=inserted,
            skipped_duplicate=not inserted,
            row=row,
            message="AI portföy değerlendirmesi kaydedildi." if inserted else "Kayıt zaten mevcut.",
        )
    except Exception:
        return SavePortfolioAIResult(
            saved=False,
            persistence_failed=True,
            message="AI portföy değerlendirmesi kaydedilemedi.",
        )
