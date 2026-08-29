"""Persist Security Intelligence snapshots.

Idempotency: UPSERT on (symbol, as_of_key, facts_version, engine_version).
Replay of the same identity updates the same row and does not create duplicates.

Does not write portfolios, transactions, Participation, candidates, or Hybrid.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional

from repositories.security_intelligence_snapshot_repository import (
    SecurityIntelligenceSnapshotRepository,
)
from services.security_intelligence_contract import (
    SecurityIntelligenceSnapshot,
    SecurityIntelligenceView,
    snapshot_from_view,
)


UNDATED_AS_OF_KEY = "UNDATED"


@dataclass(frozen=True)
class SaveSecurityIntelligenceResult:
    saved: bool
    skipped_duplicate: bool = False
    persistence_failed: bool = False
    row: Optional[Dict[str, Any]] = None
    message: str = ""
    dry_run: bool = False


def as_of_key(as_of: Optional[str]) -> str:
    text = str(as_of or "").strip()
    return text or UNDATED_AS_OF_KEY


def snapshot_row_from_view(
    view: SecurityIntelligenceView,
    *,
    as_of: Optional[str] = None,
) -> Dict[str, Any]:
    snap = snapshot_from_view(view, as_of=as_of)
    return snapshot_to_row(snap)


def snapshot_to_row(snap: SecurityIntelligenceSnapshot) -> Dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "symbol": str(snap.symbol or "").strip().upper(),
        "as_of": snap.as_of,
        "as_of_key": as_of_key(snap.as_of),
        "facts_version": snap.facts_version,
        "engine_version": snap.engine_version,
        "overall_score": snap.overall_score,
        "overall_status": snap.overall_status,
        "overall_confidence": snap.overall_confidence,
        "investment_state": snap.investment_state,
        "participation_status": snap.participation_status,
        "research_allowed": snap.research_allowed,
        "dimension_scores": dict(snap.dimension_scores),
        "dimension_statuses": dict(snap.dimension_statuses),
        "data_quality": dict(snap.data_quality),
        "strengths": list(snap.strengths),
        "weaknesses": list(snap.weaknesses),
        "risk_flags": list(snap.risk_flags),
        "reason_codes": list(snap.reason_codes),
        "change_flags": list(snap.change_flags),
        "updated_at": now,
    }


def snapshot_from_row(row: Mapping[str, Any]) -> SecurityIntelligenceSnapshot:
    return SecurityIntelligenceSnapshot(
        symbol=str(row.get("symbol") or ""),
        as_of=str(row.get("as_of") or "") or None,
        engine_version=str(row.get("engine_version") or ""),
        facts_version=str(row.get("facts_version") or ""),
        overall_score=row.get("overall_score"),
        overall_status=str(row.get("overall_status") or ""),
        investment_state=str(row.get("investment_state") or ""),
        participation_status=str(row.get("participation_status") or ""),
        research_allowed=row.get("research_allowed"),
        dimension_scores=dict(row.get("dimension_scores") or {}),
        dimension_statuses=dict(row.get("dimension_statuses") or {}),
        change_flags=tuple(row.get("change_flags") or ()),
        overall_confidence=row.get("overall_confidence"),
        strengths=tuple(row.get("strengths") or ()),
        weaknesses=tuple(row.get("weaknesses") or ()),
        risk_flags=tuple(row.get("risk_flags") or ()),
        reason_codes=tuple(row.get("reason_codes") or ()),
        data_quality=dict(row.get("data_quality") or {}),
    )


def save_security_intelligence_snapshot(
    repo: SecurityIntelligenceSnapshotRepository,
    view: SecurityIntelligenceView,
    *,
    as_of: Optional[str] = None,
    dry_run: bool = False,
) -> SaveSecurityIntelligenceResult:
    payload = snapshot_row_from_view(view, as_of=as_of)
    if dry_run:
        return SaveSecurityIntelligenceResult(
            saved=False,
            dry_run=True,
            row=payload,
            message="Dry run: snapshot not written.",
        )
    try:
        existing = repo.get_by_identity(
            payload["symbol"],
            as_of_key=payload["as_of_key"],
            facts_version=payload["facts_version"],
            engine_version=payload["engine_version"],
        )
        row = repo.upsert(payload)
    except Exception:
        return SaveSecurityIntelligenceResult(
            saved=False,
            persistence_failed=True,
            message="Security Intelligence snapshot could not be saved.",
        )
    skipped = existing is not None
    return SaveSecurityIntelligenceResult(
        saved=not skipped,
        skipped_duplicate=skipped,
        row=row,
        message=(
            "Security Intelligence snapshot already present; upserted."
            if skipped
            else "Security Intelligence snapshot saved."
        ),
    )
