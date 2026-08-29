"""Persist Security Intelligence snapshots.

Idempotency:
  same (symbol, as_of_key, facts_version, engine_version)
  + identical semantic payload → skip write (0 timestamp churn)
  same identity + changed payload → UPSERT (intentional update)

A new facts_version or engine_version creates a new row and does not
overwrite older history.

Does not write portfolios, transactions, Participation, candidates, or Hybrid.
"""

from __future__ import annotations

import json
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
MIN_PERSIST_COMPLETENESS_PCT = 50.0
_TRANSIENT_KEYS = frozenset({"id", "created_at", "updated_at"})


@dataclass(frozen=True)
class SaveSecurityIntelligenceResult:
    saved: bool
    skipped_duplicate: bool = False
    persistence_failed: bool = False
    insufficient: bool = False
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


def semantic_payload(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {key: row.get(key) for key in snapshot_to_row(snapshot_from_row(row)) if key not in _TRANSIENT_KEYS}


def payloads_semantically_equal(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return json.dumps(semantic_payload(left), sort_keys=True, default=str) == json.dumps(
        semantic_payload(right), sort_keys=True, default=str
    )


def may_persist_view(
    view: SecurityIntelligenceView,
    *,
    completeness_pct: Optional[float] = None,
) -> bool:
    if view.overall_score is not None:
        return True
    if completeness_pct is not None and completeness_pct >= MIN_PERSIST_COMPLETENESS_PCT:
        return True
    return False


def latest_snapshot(
    repo: SecurityIntelligenceSnapshotRepository,
    symbol: str,
) -> Optional[SecurityIntelligenceSnapshot]:
    row = repo.get_latest(symbol)
    return snapshot_from_row(row) if row else None


def load_previous_for_evaluation(
    repo: SecurityIntelligenceSnapshotRepository,
    symbol: str,
    *,
    as_of: Optional[str],
    facts_version: str,
    engine_version: str,
) -> Optional[SecurityIntelligenceSnapshot]:
    latest = repo.get_latest(symbol)
    if latest is None:
        return None
    same_identity = (
        as_of_key(latest.get("as_of")) == as_of_key(as_of)
        and str(latest.get("facts_version") or "") == facts_version
        and str(latest.get("engine_version") or "") == engine_version
    )
    if same_identity:
        return previous_snapshot(repo, symbol, before_as_of=latest.get("as_of"))
    return snapshot_from_row(latest)


def previous_snapshot(
    repo: SecurityIntelligenceSnapshotRepository,
    symbol: str,
    *,
    before_as_of: Optional[str] = None,
    facts_version: Optional[str] = None,
    engine_version: Optional[str] = None,
) -> Optional[SecurityIntelligenceSnapshot]:
    row = repo.get_previous(
        symbol,
        before_as_of=before_as_of,
        facts_version=facts_version,
        engine_version=engine_version,
    )
    if row is None and (facts_version or engine_version):
        row = repo.get_previous(symbol, before_as_of=before_as_of)
    return snapshot_from_row(row) if row else None


def save_security_intelligence_snapshot(
    repo: SecurityIntelligenceSnapshotRepository,
    view: SecurityIntelligenceView,
    *,
    as_of: Optional[str] = None,
    dry_run: bool = False,
    completeness_pct: Optional[float] = None,
    require_sufficient: bool = False,
) -> SaveSecurityIntelligenceResult:
    if require_sufficient and not may_persist_view(view, completeness_pct=completeness_pct):
        return SaveSecurityIntelligenceResult(
            saved=False,
            insufficient=True,
            message="SecurityFacts too sparse to persist a snapshot.",
        )
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
        if existing is not None and payloads_semantically_equal(existing, payload):
            return SaveSecurityIntelligenceResult(
                saved=False,
                skipped_duplicate=True,
                row=dict(existing),
                message="Identical snapshot already present; write skipped.",
            )
        if existing is None:
            payload["created_at"] = datetime.now(timezone.utc).isoformat()
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        row = repo.upsert(payload)
    except Exception:
        return SaveSecurityIntelligenceResult(
            saved=False,
            persistence_failed=True,
            message="Security Intelligence snapshot could not be saved.",
        )
    return SaveSecurityIntelligenceResult(
        saved=True,
        skipped_duplicate=False,
        row=row,
        message=(
            "Security Intelligence snapshot updated."
            if existing is not None
            else "Security Intelligence snapshot saved."
        ),
    )
