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
from decimal import Decimal
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
PERSISTENCE_METADATA_FIELDS = frozenset({"id", "created_at", "updated_at"})
SEMANTIC_FIELDS = (
    "symbol",
    "as_of",
    "as_of_key",
    "facts_version",
    "engine_version",
    "overall_score",
    "overall_status",
    "overall_confidence",
    "investment_state",
    "participation_status",
    "research_allowed",
    "dimension_scores",
    "dimension_statuses",
    "data_quality",
    "strengths",
    "weaknesses",
    "risk_flags",
    "reason_codes",
    "change_flags",
)


@dataclass(frozen=True)
class SaveSecurityIntelligenceResult:
    saved: bool
    skipped_duplicate: bool = False
    persistence_failed: bool = False
    insufficient: bool = False
    row: Optional[Dict[str, Any]] = None
    message: str = ""
    dry_run: bool = False


def canonicalize_as_of(value: Any) -> Optional[str]:
    """Normalize date / midnight timestamptz to YYYY-MM-DD.

    Postgres timestamptz stores a date-only as_of as 00:00:00+00. That is
    storage representation, not a new financial period. A non-midnight
    timestamp is kept because it can represent evidence freshness.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if (
            value.hour == 0
            and value.minute == 0
            and value.second == 0
            and value.microsecond == 0
        ):
            return value.date().isoformat()
        return value.isoformat()
    if hasattr(value, "isoformat") and not isinstance(value, (str, bytes)):
        try:
            return value.isoformat()
        except Exception:
            pass
    text = str(value).strip()
    if not text:
        return None
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        date_part = text[:10]
        remainder = text[10:]
        if not remainder:
            return date_part
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return text
        if (
            parsed.hour == 0
            and parsed.minute == 0
            and parsed.second == 0
            and parsed.microsecond == 0
        ):
            return date_part
        return parsed.isoformat()
    return text


def as_of_key(as_of: Optional[str]) -> str:
    canonical = canonicalize_as_of(as_of)
    if canonical and len(canonical) >= 10 and canonical[4] == "-" and canonical[7] == "-":
        return canonical[:10]
    return canonical or UNDATED_AS_OF_KEY


def _canonicalize_number(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        return round(value, 6)
    if isinstance(value, int):
        return value
    return value


def canonicalize_semantic_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): canonicalize_semantic_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [canonicalize_semantic_value(item) for item in value]
    if isinstance(value, (Decimal, float, int)) and not isinstance(value, bool):
        return _canonicalize_number(value)
    return value


def semantic_payload(row: Mapping[str, Any]) -> Dict[str, Any]:
    rebuilt = snapshot_to_row(snapshot_from_row(row))
    payload: Dict[str, Any] = {}
    for field in SEMANTIC_FIELDS:
        raw = rebuilt.get(field)
        if field == "as_of":
            raw = canonicalize_as_of(raw)
        if field == "as_of_key":
            raw = as_of_key(rebuilt.get("as_of") or raw)
        payload[field] = canonicalize_semantic_value(raw)
    return payload


def canonical_semantic_json(row: Mapping[str, Any]) -> str:
    return json.dumps(semantic_payload(row), sort_keys=True, separators=(",", ":"), default=str)


def payloads_semantically_equal(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return canonical_semantic_json(left) == canonical_semantic_json(right)


def semantic_payload_diffs(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
) -> tuple[tuple[str, Any, Any], ...]:
    first = semantic_payload(left)
    second = semantic_payload(right)
    diffs: list[tuple[str, Any, Any]] = []
    for field in SEMANTIC_FIELDS:
        if first.get(field) != second.get(field):
            diffs.append((field, first.get(field), second.get(field)))
    return tuple(diffs)


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
        "as_of": canonicalize_as_of(snap.as_of),
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
        as_of=canonicalize_as_of(row.get("as_of")),
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
