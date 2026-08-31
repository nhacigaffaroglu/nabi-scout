"""Persist Turkish fund Participation and Fund Intelligence snapshots.

Reuses existing tables and repositories. Does not rescore, persist 8E,
or call New Money. A successful compute does not imply a write.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from services.fund_product_contract import LAYER_CASH_LIKE
from services.security_intelligence_snapshot_service import payloads_semantically_equal
from services.turkiye_fund_refresh_contract import (
    LAYER_FUND_INTELLIGENCE,
    LAYER_PARTICIPATION,
    REASON_INVALID_PAYLOAD,
    TABLE_PARTICIPATION_SNAPSHOTS,
    TABLE_SI_SNAPSHOTS,
)
from services.turkiye_fund_snapshot import TurkiyeFundLayerSnapshot, assert_ais_not_portfolio_cash

FORBIDDEN_AIS_EXPOSURE = frozenset({"cash", "CASH", "ASSET_CLASS_CASH"})
MIGRATION_PARTICIPATION = Path("database/migration_participation_assessment_history.sql")
MIGRATION_PARTICIPATION_ELIGIBILITY = Path("database/migration_participation_research_allowed.sql")
MIGRATION_SI = Path("database/migration_security_intelligence_snapshots.sql")

PARTICIPATION_REQUIRED = frozenset(
    {"symbol", "status", "assessment_payload", "semantic_identity"}
)
PARTICIPATION_COLUMNS = frozenset(
    {
        "symbol",
        "assessed_at",
        "methodology_id",
        "methodology_version",
        "status",
        "source",
        "confidence",
        "methodology_completeness",
        "data_completeness_pct",
        "holdings_coverage_pct",
        "freshness_label",
        "financial_overall_outcome",
        "business_overall_outcome",
        "provider_status",
        "sec_available",
        "warnings",
        "errors",
        "missing_capabilities",
        "source_evidence",
        "assessment_payload",
        "semantic_identity",
        "research_allowed",
    }
)
SI_REQUIRED = frozenset(
    {
        "symbol",
        "as_of_key",
        "facts_version",
        "engine_version",
        "overall_status",
        "investment_state",
    }
)
SI_COLUMNS = frozenset(
    {
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
    }
)


@dataclass(frozen=True)
class PersistLayerResult:
    saved: bool
    skipped_duplicate: bool = False
    persistence_failed: bool = False
    invalid: bool = False
    row: Optional[Dict[str, Any]] = None
    message: str = ""


@dataclass
class MemoryParticipationAssessmentRepository:
    TABLE = TABLE_PARTICIPATION_SNAPSHOTS
    rows: List[Dict[str, Any]] = field(default_factory=list)
    fail_symbols: set[str] = field(default_factory=set)
    unavailable: bool = False

    def append_snapshot(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if self.unavailable:
            raise RuntimeError("database_unavailable")
        symbol = str(payload.get("symbol") or "").upper()
        if symbol in self.fail_symbols:
            raise RuntimeError("participation_insert_failed")
        stored = dict(payload)
        self.rows.append(stored)
        return dict(stored)

    def get_latest(self, symbol: str) -> Optional[Dict[str, Any]]:
        history = self.get_recent_history(symbol, limit=1)
        return history[0] if history else None

    def get_recent_history(self, symbol: str, *, limit: int = 10) -> List[Dict[str, Any]]:
        if self.unavailable:
            raise RuntimeError("database_unavailable")
        code = str(symbol or "").strip().upper()
        matches = [dict(row) for row in self.rows if str(row.get("symbol") or "").upper() == code]
        matches.reverse()
        return matches[: max(1, int(limit))]


@dataclass
class MemorySecurityIntelligenceSnapshotRepository:
    TABLE = TABLE_SI_SNAPSHOTS
    rows: List[Dict[str, Any]] = field(default_factory=list)
    fail_symbols: set[str] = field(default_factory=set)
    unavailable: bool = False

    def upsert(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if self.unavailable:
            raise RuntimeError("database_unavailable")
        symbol = str(payload.get("symbol") or "").upper()
        if symbol in self.fail_symbols:
            raise RuntimeError("fi_insert_failed")
        identity = (
            symbol,
            str(payload.get("as_of_key") or ""),
            str(payload.get("facts_version") or ""),
            str(payload.get("engine_version") or ""),
        )
        for index, row in enumerate(self.rows):
            current = (
                str(row.get("symbol") or "").upper(),
                str(row.get("as_of_key") or ""),
                str(row.get("facts_version") or ""),
                str(row.get("engine_version") or ""),
            )
            if current == identity:
                self.rows[index] = dict(payload)
                return dict(payload)
        self.rows.append(dict(payload))
        return dict(payload)

    def get_latest(self, symbol: str) -> Optional[Dict[str, Any]]:
        history = self.get_recent_history(symbol, limit=1)
        return history[0] if history else None

    def get_recent_history(self, symbol: str, *, limit: int = 10) -> List[Dict[str, Any]]:
        if self.unavailable:
            raise RuntimeError("database_unavailable")
        code = str(symbol or "").strip().upper()
        matches = [dict(row) for row in self.rows if str(row.get("symbol") or "").upper() == code]

        def _as_of(row: Dict[str, Any]) -> str:
            return str(row.get("as_of") or row.get("as_of_key") or "")

        matches.sort(key=_as_of, reverse=True)
        return matches[: max(1, min(int(limit), 25))]

    def get_by_identity(
        self,
        symbol: str,
        *,
        as_of_key: str,
        facts_version: str,
        engine_version: str,
    ) -> Optional[Dict[str, Any]]:
        if self.unavailable:
            raise RuntimeError("database_unavailable")
        code = str(symbol or "").strip().upper()
        for row in self.rows:
            if (
                str(row.get("symbol") or "").upper() == code
                and str(row.get("as_of_key") or "") == as_of_key
                and str(row.get("facts_version") or "") == facts_version
                and str(row.get("engine_version") or "") == engine_version
            ):
                return dict(row)
        return None


def participation_row_from_snapshot(snapshot: TurkiyeFundLayerSnapshot) -> Dict[str, Any]:
    raw = dict(snapshot.payload)
    assessment = dict(raw.get("assessment_payload") or {})
    assessment.setdefault("instrument", snapshot.instrument)
    assessment.setdefault("market", snapshot.market)
    assessment.setdefault("fund_code", snapshot.fund_code)
    row = {
        "symbol": str(raw.get("symbol") or snapshot.fund_code).strip().upper(),
        "assessed_at": raw.get("assessed_at") or snapshot.calculated_at,
        "methodology_id": raw.get("methodology_id"),
        "methodology_version": raw.get("methodology_version") or snapshot.methodology_version,
        "status": raw.get("status"),
        "source": raw.get("source"),
        "confidence": raw.get("confidence"),
        "methodology_completeness": raw.get("methodology_completeness"),
        "data_completeness_pct": raw.get("data_completeness_pct"),
        "holdings_coverage_pct": raw.get("holdings_coverage_pct"),
        "freshness_label": raw.get("freshness_label"),
        "financial_overall_outcome": raw.get("financial_overall_outcome"),
        "business_overall_outcome": raw.get("business_overall_outcome"),
        "provider_status": dict(raw.get("provider_status") or {}),
        "sec_available": bool(raw.get("sec_available", False)),
        "warnings": list(raw.get("warnings") or []),
        "errors": list(raw.get("errors") or []),
        "missing_capabilities": list(raw.get("missing_capabilities") or []),
        "source_evidence": dict(raw.get("source_evidence") or {}),
        "assessment_payload": assessment,
        "semantic_identity": raw.get("semantic_identity") or snapshot.idempotency_key,
        "research_allowed": bool(raw.get("research_allowed")),
    }
    return row


def fund_intelligence_row_from_snapshot(snapshot: TurkiyeFundLayerSnapshot) -> Dict[str, Any]:
    raw = dict(snapshot.payload)
    quality = dict(raw.get("data_quality") or {})
    quality.setdefault("instrument", snapshot.instrument)
    quality.setdefault("market", snapshot.market)
    if raw.get("source_as_of") and "source_as_of" not in quality:
        quality["source_as_of"] = dict(raw.get("source_as_of") or {})
    row = {
        "symbol": str(raw.get("symbol") or snapshot.fund_code).strip().upper(),
        "as_of": raw.get("as_of"),
        "as_of_key": raw.get("as_of_key"),
        "facts_version": raw.get("facts_version"),
        "engine_version": raw.get("engine_version") or snapshot.methodology_version,
        "overall_score": raw.get("overall_score"),
        "overall_status": raw.get("overall_status") or raw.get("investment_state"),
        "overall_confidence": raw.get("overall_confidence"),
        "investment_state": raw.get("investment_state") or raw.get("overall_status"),
        "participation_status": raw.get("participation_status"),
        "research_allowed": raw.get("research_allowed"),
        "dimension_scores": dict(raw.get("dimension_scores") or {}),
        "dimension_statuses": dict(raw.get("dimension_statuses") or {}),
        "data_quality": quality,
        "strengths": list(raw.get("strengths") or []),
        "weaknesses": list(raw.get("weaknesses") or []),
        "risk_flags": list(raw.get("risk_flags") or []),
        "reason_codes": list(raw.get("reason_codes") or []),
        "change_flags": list(raw.get("change_flags") or []),
    }
    if snapshot.fund_code == "AIS":
        assert_ais_not_portfolio_cash(snapshot)
        exposure = (quality.get("economic_exposure") or {}).get("primary_exposure")
        if exposure in FORBIDDEN_AIS_EXPOSURE or exposure != LAYER_CASH_LIKE:
            raise ValueError("ais_cash_firewall")
    return row


def audit_production_schema_compatibility() -> Dict[str, Any]:
    """Confirm Turkish FUND rows fit existing tables. Does not migrate."""
    participation_sql = MIGRATION_PARTICIPATION.read_text(encoding="utf-8")
    eligibility_sql = MIGRATION_PARTICIPATION_ELIGIBILITY.read_text(encoding="utf-8")
    si_sql = MIGRATION_SI.read_text(encoding="utf-8")
    missing_participation = [
        column
        for column in PARTICIPATION_REQUIRED
        if column not in participation_sql and column not in eligibility_sql
    ]
    missing_si = [column for column in SI_REQUIRED if column not in si_sql]
    extra_not_columns = ("instrument", "market", "source_as_of", "calculated_at")
    compatible = not missing_participation and not missing_si
    return {
        "migration_required": False if compatible else True,
        "compatible": compatible,
        "result": "COMPATIBLE" if compatible else "BLOCKED",
        "missing_participation_columns": missing_participation,
        "missing_si_columns": missing_si,
        "instrument_market_columns": False,
        "extra_compute_fields_nested_or_stripped": list(extra_not_columns),
        "participation_table": TABLE_PARTICIPATION_SNAPSHOTS,
        "fund_intelligence_table": TABLE_SI_SNAPSHOTS,
        "unique_si_identity": "(symbol, as_of_key, facts_version, engine_version)",
        "participation_idempotency": "semantic_identity",
    }


def schema_compatible(snapshot: TurkiyeFundLayerSnapshot) -> bool:
    if snapshot.layer == LAYER_PARTICIPATION:
        row = participation_row_from_snapshot(snapshot)
        return PARTICIPATION_REQUIRED.issubset(row) and set(row) <= PARTICIPATION_COLUMNS
    if snapshot.layer == LAYER_FUND_INTELLIGENCE:
        row = fund_intelligence_row_from_snapshot(snapshot)
        return SI_REQUIRED.issubset(row) and set(row) <= SI_COLUMNS
    return False


def persist_participation_snapshot(
    repo: Any,
    snapshot: TurkiyeFundLayerSnapshot,
    *,
    dry_run: bool = True,
) -> PersistLayerResult:
    if snapshot.layer != LAYER_PARTICIPATION:
        return PersistLayerResult(saved=False, invalid=True, message=REASON_INVALID_PAYLOAD)
    try:
        row = participation_row_from_snapshot(snapshot)
    except Exception as exc:
        return PersistLayerResult(saved=False, invalid=True, message=str(exc))
    if not PARTICIPATION_REQUIRED.issubset(row) or not row.get("status"):
        return PersistLayerResult(saved=False, invalid=True, message=REASON_INVALID_PAYLOAD)
    if dry_run or repo is None:
        return PersistLayerResult(saved=False, row=row, message="DRY_RUN_NO_WRITE")
    try:
        latest = repo.get_latest(row["symbol"])
        if latest is not None and latest.get("semantic_identity") == row["semantic_identity"]:
            return PersistLayerResult(
                saved=False,
                skipped_duplicate=True,
                row=dict(latest),
                message="NO_CHANGE",
            )
        saved = repo.append_snapshot(row)
    except Exception as exc:
        return PersistLayerResult(saved=False, persistence_failed=True, message=str(exc))
    return PersistLayerResult(saved=True, row=dict(saved), message="PUBLISHED")


def persist_fund_intelligence_snapshot(
    repo: Any,
    snapshot: TurkiyeFundLayerSnapshot,
    *,
    dry_run: bool = True,
) -> PersistLayerResult:
    if snapshot.layer != LAYER_FUND_INTELLIGENCE:
        return PersistLayerResult(saved=False, invalid=True, message=REASON_INVALID_PAYLOAD)
    try:
        row = fund_intelligence_row_from_snapshot(snapshot)
    except Exception as exc:
        return PersistLayerResult(saved=False, invalid=True, message=str(exc))
    if not SI_REQUIRED.issubset(row):
        return PersistLayerResult(saved=False, invalid=True, message=REASON_INVALID_PAYLOAD)
    if dry_run or repo is None:
        return PersistLayerResult(saved=False, row=row, message="DRY_RUN_NO_WRITE")
    try:
        existing = repo.get_by_identity(
            row["symbol"],
            as_of_key=row["as_of_key"],
            facts_version=row["facts_version"],
            engine_version=row["engine_version"],
        )
        if existing is not None and payloads_semantically_equal(existing, row):
            return PersistLayerResult(
                saved=False,
                skipped_duplicate=True,
                row=dict(existing),
                message="NO_CHANGE",
            )
        saved = repo.upsert(row)
    except Exception as exc:
        return PersistLayerResult(saved=False, persistence_failed=True, message=str(exc))
    return PersistLayerResult(saved=True, row=dict(saved), message="PUBLISHED")
