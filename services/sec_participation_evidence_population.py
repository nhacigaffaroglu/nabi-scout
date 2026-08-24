from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from config.participation_catalog import is_configured_participation_symbol
from services.participation_cik_resolver import (
    is_usable_cik,
    normalize_resolved_cik,
)
from services.participation_source_evidence import participation_source_evidence_mapping
from services.sec_company_facts_evidence import pad_cik
from services.universe_expansion_contract import EXPANSION_STATUS_PENDING


ASSESSED_QUEUE_STATUSES = frozenset({"COMPLETED", "RETRYABLE"})


@dataclass(frozen=True)
class AssessedEquityIdentity:
    symbol: str
    cik: Optional[str]
    cik_source: str
    fetchable: bool
    problems: tuple[str, ...] = ()


@dataclass(frozen=True)
class AssessedEquityPopulation:
    assessed: tuple[AssessedEquityIdentity, ...]
    catalog_excluded: tuple[str, ...]
    pending_excluded: tuple[str, ...]
    missing_cik: tuple[str, ...]
    cik_conflicts: tuple[str, ...]
    duplicate_ciks: tuple[str, ...]

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(item.symbol for item in self.assessed)

    @property
    def fetchable(self) -> tuple[AssessedEquityIdentity, ...]:
        return tuple(item for item in self.assessed if item.fetchable)

    @property
    def fetchable_ciks(self) -> tuple[str, ...]:
        seen: list[str] = []
        for item in self.fetchable:
            if item.cik and item.cik not in seen:
                seen.append(item.cik)
        return tuple(seen)


def _snapshot_cik(snapshot: Optional[Mapping[str, Any]]) -> Optional[str]:
    if not snapshot:
        return None
    payload = snapshot.get("assessment_payload") or {}
    for source in (payload.get("source_evidence"), snapshot.get("source_evidence")):
        mapping = participation_source_evidence_mapping(source)
        cik = mapping.get("cik")
        if is_usable_cik(cik):
            return normalize_resolved_cik(cik)
    return None


def _candidate_cik(candidate: Optional[Mapping[str, Any]]) -> Optional[str]:
    if not candidate:
        return None
    cik = candidate.get("cik")
    if is_usable_cik(cik):
        return normalize_resolved_cik(cik)
    return None


def resolve_assessed_equity_population(
    *,
    queue_rows: Sequence[Mapping[str, Any]],
    snapshots_by_symbol: Mapping[str, Mapping[str, Any]],
    candidates_by_symbol: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> AssessedEquityPopulation:
    candidates_by_symbol = candidates_by_symbol or {}
    catalog_excluded: list[str] = []
    pending_excluded: list[str] = []
    assessed_rows: list[tuple[str, Mapping[str, Any]]] = []

    for row in queue_rows:
        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        if is_configured_participation_symbol(symbol):
            catalog_excluded.append(symbol)
            continue
        status = str(row.get("status") or "").strip().upper()
        if status == EXPANSION_STATUS_PENDING:
            pending_excluded.append(symbol)
            continue
        if status not in ASSESSED_QUEUE_STATUSES:
            continue
        snapshot = snapshots_by_symbol.get(symbol)
        if not snapshot:
            continue
        assessed_rows.append((symbol, row))

    identities: list[AssessedEquityIdentity] = []
    missing_cik: list[str] = []
    cik_conflicts: list[str] = []
    cik_to_symbols: dict[str, list[str]] = {}

    for symbol, _row in assessed_rows:
        snapshot = snapshots_by_symbol.get(symbol)
        candidate = candidates_by_symbol.get(symbol)
        snap_cik = _snapshot_cik(snapshot)
        cand_cik = _candidate_cik(candidate)
        problems: list[str] = []
        cik = None
        source = "unresolved"
        if snap_cik and cand_cik and snap_cik != cand_cik:
            problems.append("snapshot_candidate_cik_conflict")
            cik_conflicts.append(symbol)
            source = "conflict"
        elif snap_cik:
            cik = snap_cik
            source = "snapshot"
        elif cand_cik:
            cik = cand_cik
            source = "candidate_record"
        else:
            problems.append("missing_cik")
            missing_cik.append(symbol)

        padded = pad_cik(cik) if cik else None
        fetchable = padded is not None and not problems
        if padded:
            cik_to_symbols.setdefault(padded, []).append(symbol)
        identities.append(
            AssessedEquityIdentity(
                symbol=symbol,
                cik=padded,
                cik_source=source,
                fetchable=fetchable,
                problems=tuple(problems),
            )
        )

    duplicate_ciks: list[str] = []
    duplicate_symbols: set[str] = set()
    for cik, symbols in cik_to_symbols.items():
        unique_symbols = list(dict.fromkeys(symbols))
        if len(unique_symbols) > 1:
            duplicate_ciks.append(cik)
            duplicate_symbols.update(unique_symbols)

    resolved: list[AssessedEquityIdentity] = []
    for item in identities:
        if item.symbol in duplicate_symbols:
            resolved.append(
                AssessedEquityIdentity(
                    symbol=item.symbol,
                    cik=item.cik,
                    cik_source=item.cik_source,
                    fetchable=False,
                    problems=item.problems + ("duplicate_cik_identity",),
                )
            )
        else:
            resolved.append(item)

    return AssessedEquityPopulation(
        assessed=tuple(resolved),
        catalog_excluded=tuple(dict.fromkeys(catalog_excluded)),
        pending_excluded=tuple(dict.fromkeys(pending_excluded)),
        missing_cik=tuple(dict.fromkeys(missing_cik)),
        cik_conflicts=tuple(dict.fromkeys(cik_conflicts)),
        duplicate_ciks=tuple(dict.fromkeys(duplicate_ciks)),
    )
