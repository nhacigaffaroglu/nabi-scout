"""Authoritative participation state for pipeline enforcement.

Does not assess, score, or invent religious criteria. It only resolves
existing snapshot / catalog / candidate evidence into one status.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from config.participation_catalog import (
    configured_participation_for_symbol,
    is_configured_participation_symbol,
)
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)
from services.research_workflow_service import is_open_research_status

AUTHORITY_SOURCE_SNAPSHOT = "snapshot"
AUTHORITY_SOURCE_CATALOG = "catalog"
AUTHORITY_SOURCE_CANDIDATE = "candidate"
AUTHORITY_SOURCE_MISSING = "missing"

SCANNER_SKIP_REJECTED = "PARTICIPATION_REJECTED"
SCANNER_SKIP_UNRESOLVED = "PARTICIPATION_UNRESOLVED"
SCANNER_SKIP_MISSING = "PARTICIPATION_MISSING"

SUPPORTED_STATUSES = frozenset(
    {
        PARTICIPATION_STATUS_UYGUN,
        PARTICIPATION_STATUS_KONTROL_ET,
        PARTICIPATION_STATUS_UYGUN_DEGIL,
    }
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _symbol(value: Any) -> str:
    return _text(value).upper()


def snapshot_participation_status(snapshot: Optional[Mapping[str, Any]]) -> str:
    if not snapshot:
        return ""
    status = _text(snapshot.get("status") or snapshot.get("participation_status"))
    return status if status in SUPPORTED_STATUSES else ""


def candidate_participation_status(candidate: Optional[Mapping[str, Any]]) -> str:
    if not candidate:
        return ""
    status = _text(candidate.get("participation_status"))
    return status if status in SUPPORTED_STATUSES else ""


@dataclass(frozen=True)
class AuthoritativeParticipation:
    symbol: str
    status: str
    source: str
    research_allowed: bool
    scanner_allowed: bool
    skip_reason: Optional[str]

    @property
    def approved(self) -> bool:
        return self.status == PARTICIPATION_STATUS_UYGUN

    @property
    def rejected(self) -> bool:
        return self.status == PARTICIPATION_STATUS_UYGUN_DEGIL

    @property
    def unresolved(self) -> bool:
        return self.status == PARTICIPATION_STATUS_KONTROL_ET

    @property
    def missing(self) -> bool:
        return not self.status


def resolve_authoritative_participation(
    symbol: str,
    *,
    candidate: Optional[Mapping[str, Any]] = None,
    snapshot: Optional[Mapping[str, Any]] = None,
    catalog_status: Optional[str] = None,
) -> AuthoritativeParticipation:
    normalized = _symbol(symbol)
    snapshot_status = snapshot_participation_status(snapshot)
    if snapshot_status:
        return _from_status(normalized, snapshot_status, AUTHORITY_SOURCE_SNAPSHOT)

    explicit_catalog = _text(catalog_status)
    if explicit_catalog in SUPPORTED_STATUSES:
        if explicit_catalog == PARTICIPATION_STATUS_UYGUN or is_configured_participation_symbol(
            normalized
        ):
            return _from_status(normalized, explicit_catalog, AUTHORITY_SOURCE_CATALOG)

    configured = configured_participation_for_symbol(normalized)
    if configured and configured[0] in SUPPORTED_STATUSES:
        return _from_status(normalized, configured[0], AUTHORITY_SOURCE_CATALOG)

    candidate_status = candidate_participation_status(candidate)
    if candidate_status:
        return _from_status(normalized, candidate_status, AUTHORITY_SOURCE_CANDIDATE)

    return _from_status(normalized, "", AUTHORITY_SOURCE_MISSING)


def _from_status(symbol: str, status: str, source: str) -> AuthoritativeParticipation:
    if status == PARTICIPATION_STATUS_UYGUN:
        return AuthoritativeParticipation(
            symbol=symbol,
            status=status,
            source=source,
            research_allowed=True,
            scanner_allowed=True,
            skip_reason=None,
        )
    if status == PARTICIPATION_STATUS_UYGUN_DEGIL:
        return AuthoritativeParticipation(
            symbol=symbol,
            status=status,
            source=source,
            research_allowed=False,
            scanner_allowed=False,
            skip_reason=SCANNER_SKIP_REJECTED,
        )
    if status == PARTICIPATION_STATUS_KONTROL_ET:
        return AuthoritativeParticipation(
            symbol=symbol,
            status=status,
            source=source,
            research_allowed=False,
            scanner_allowed=False,
            skip_reason=SCANNER_SKIP_UNRESOLVED,
        )
    return AuthoritativeParticipation(
        symbol=symbol,
        status="",
        source=AUTHORITY_SOURCE_MISSING,
        research_allowed=False,
        scanner_allowed=False,
        skip_reason=SCANNER_SKIP_MISSING,
    )


def overlay_authoritative_participation(
    candidate: Mapping[str, Any],
    snapshot: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    row = dict(candidate)
    authority = resolve_authoritative_participation(
        _symbol(row.get("symbol")),
        candidate=row,
        snapshot=snapshot,
    )
    if authority.status:
        row["participation_status"] = authority.status
    row["research_allowed"] = authority.research_allowed
    row["participation_authority_source"] = authority.source
    return row


def overlay_candidate_rows(
    candidates: Sequence[Mapping[str, Any]],
    snapshots: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> list[dict[str, Any]]:
    by_symbol = snapshots or {}
    overlaid: list[dict[str, Any]] = []
    for row in candidates:
        symbol = _symbol(row.get("symbol"))
        overlaid.append(overlay_authoritative_participation(row, by_symbol.get(symbol)))
    return overlaid


def is_approved_open_research(candidate: Mapping[str, Any]) -> bool:
    """Research-waiting after authoritative overlay. Uygun + open workflow only."""
    status = candidate_participation_status(candidate)
    if status != PARTICIPATION_STATUS_UYGUN:
        return False
    allowed = candidate.get("research_allowed")
    if allowed is False:
        return False
    if allowed is None:
        allowed = status == PARTICIPATION_STATUS_UYGUN
    if not allowed:
        return False
    return is_open_research_status(candidate.get("research_status"))


def snapshots_by_symbol(
    rows: Optional[Sequence[Mapping[str, Any]]],
) -> dict[str, Mapping[str, Any]]:
    latest: dict[str, Mapping[str, Any]] = {}
    for row in rows or ():
        symbol = _symbol(row.get("symbol"))
        if symbol and symbol not in latest:
            latest[symbol] = row
    return latest

