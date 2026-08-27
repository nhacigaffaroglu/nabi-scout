from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, List, Mapping, Optional, Sequence

from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)
from services.universe_expansion_contract import (
    EXPANSION_STATUS_COMPLETED,
    EXPANSION_STATUS_RETRYABLE,
)
from services.universe_expansion_onboarding_service import (
    is_canonical_participation_status,
)


@dataclass(frozen=True)
class CompletedAssessmentReconcileResult:
    reconciled_symbols: tuple[str, ...] = ()
    skipped_symbols: tuple[str, ...] = ()
    queue_writes: int = 0
    candidate_writes: int = 0
    snapshot_writes: int = 0
    provider_calls: int = 0


def _normalize_status(value: Any) -> str:
    return str(value or "").strip()


def _snapshot_participation_status(snapshot: Optional[Mapping[str, Any]]) -> str:
    if not snapshot:
        return ""
    return _normalize_status(snapshot.get("status"))


def is_eligible_completed_assessment_reconcile(
    queue_row: Mapping[str, Any],
    snapshot: Optional[Mapping[str, Any]],
) -> bool:
    if _normalize_status(queue_row.get("status")) != EXPANSION_STATUS_RETRYABLE:
        return False
    snap_status = _snapshot_participation_status(snapshot)
    if not is_canonical_participation_status(snap_status):
        return False
    queue_participation = _normalize_status(queue_row.get("participation_status"))
    return snap_status == queue_participation


def reconcile_retryable_completed_assessments(
    *,
    queue_repo: Any,
    participation_repo: Any,
    now: Optional[datetime] = None,
    symbols: Optional[Sequence[str]] = None,
) -> CompletedAssessmentReconcileResult:
    """Mark RETRYABLE rows COMPLETED when a canonical snapshot already exists.

    Snapshot-only. No provider calls, candidate writes, or snapshot writes.
    Does not execute against production unless a caller supplies live repos.
    """
    timestamp = now or datetime.now(timezone.utc)
    wanted = None
    if symbols is not None:
        wanted = {str(item).strip().upper() for item in symbols if str(item).strip()}

    reconciled: List[str] = []
    skipped: List[str] = []
    writes = 0
    for row in queue_repo.list_all():
        symbol = str(row.get("symbol") or "").strip().upper()
        if wanted is not None and symbol not in wanted:
            continue
        snapshot = participation_repo.get_latest(symbol) if participation_repo is not None else None
        if not is_eligible_completed_assessment_reconcile(row, snapshot):
            if _normalize_status(row.get("status")) == EXPANSION_STATUS_RETRYABLE:
                skipped.append(symbol)
            continue
        queue_repo.finalize(
            str(row["id"]),
            {
                "status": EXPANSION_STATUS_COMPLETED,
                "participation_status": row.get("participation_status"),
                "research_allowed": row.get("research_allowed"),
                "last_error_category": None,
                "next_retry_at": None,
                "completed_at": timestamp.isoformat(),
                "claimed_at": None,
                "claim_run_id": None,
            },
        )
        writes += 1
        reconciled.append(symbol)

    return CompletedAssessmentReconcileResult(
        reconciled_symbols=tuple(reconciled),
        skipped_symbols=tuple(skipped),
        queue_writes=writes,
        candidate_writes=0,
        snapshot_writes=0,
        provider_calls=0,
    )


CONTROL_UYGUN_SYMBOLS = ("ADBE", "ADSK", "BIIB", "CRM", "JNJ", "MU")

# Re-export for tests that freeze control-group semantics.
CONTROL_UYGUN_STATUS = PARTICIPATION_STATUS_UYGUN
KONTROL_ET_STATUS = PARTICIPATION_STATUS_KONTROL_ET
UYGUN_DEGIL_STATUS = PARTICIPATION_STATUS_UYGUN_DEGIL
