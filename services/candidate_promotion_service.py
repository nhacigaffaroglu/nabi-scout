"""Apply YENI candidate promotion through the existing candidate repository.

Default is evaluate-only. Writes require an explicit persist flag.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from services.candidate_promotion_policy import (
    CandidatePromotionDecision,
    build_promotion_payload,
    evaluate_candidate_promotion,
)
from services.wealth_contract import normalize_symbol


@dataclass(frozen=True)
class CandidatePromotionResult:
    decision: CandidatePromotionDecision
    written: bool
    payload: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.decision.to_dict(),
            "written": self.written,
            "payload": self.payload,
        }


def evaluate_symbol_promotion(
    symbol: str,
    *,
    snapshot: Optional[Mapping[str, Any]] = None,
    resolution: Any = None,
    queue_row: Optional[Mapping[str, Any]] = None,
    existing_candidates: Sequence[Mapping[str, Any]] = (),
) -> CandidatePromotionDecision:
    return evaluate_candidate_promotion(
        symbol,
        snapshot=snapshot,
        resolution=resolution,
        queue_row=queue_row,
        existing_candidates=existing_candidates,
    )


def promote_if_eligible(
    symbol: str,
    *,
    snapshot: Optional[Mapping[str, Any]] = None,
    resolution: Any = None,
    queue_row: Optional[Mapping[str, Any]] = None,
    existing_candidates: Sequence[Mapping[str, Any]] = (),
    candidate_repo: Any = None,
    persist: bool = False,
) -> CandidatePromotionResult:
    """Create a YENI candidate once. Replay and blocked symbols write nothing."""
    normalized = normalize_symbol(symbol)
    existing = list(existing_candidates)
    if candidate_repo is not None and not existing:
        lister = getattr(candidate_repo, "list_by_symbol", None)
        if callable(lister):
            existing = list(lister(normalized) or [])
        else:
            getter = getattr(candidate_repo, "get_by_symbol", None)
            if callable(getter):
                row = getter(normalized)
                existing = [row] if row else []
    decision = evaluate_candidate_promotion(
        normalized,
        snapshot=snapshot,
        resolution=resolution,
        queue_row=queue_row,
        existing_candidates=existing,
    )
    if not persist or not decision.eligible or candidate_repo is None:
        return CandidatePromotionResult(decision=decision, written=False)
    payload = build_promotion_payload(decision)
    created = candidate_repo.create(payload)
    return CandidatePromotionResult(
        decision=decision,
        written=created is not None,
        payload=dict(created) if isinstance(created, dict) else payload,
    )
