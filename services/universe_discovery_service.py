"""Enqueue discovered identities without running Participation.

Discovery capacity (how many symbols may be known/queued) is independent of
Participation processing capacity (how many may start per scheduled run).
Ingest never marks Uygun, never calls Scanner, and never creates ADAY.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, List, Mapping, Optional, Sequence

from config.universe_expansion_config import UniverseExpansionBudgetConfig
from repositories.universe_expansion_repository import UniverseExpansionRepository
from services.universe_discovery_listings import (
    DiscoveryCandidate,
    merge_exchange_and_sec_listings,
    select_us_equity_discovery_candidates,
)
from services.universe_listing_identity import (
    EXTERNAL_SIGNAL_PRIORITY,
    EXTERNAL_SIGNAL_SOURCE,
    US_EQUITY_DISCOVERY_SOURCE,
    excluded_instrument_reason,
    listing_identity,
)


@dataclass(frozen=True)
class DiscoveryIngestReport:
    considered: int
    eligible: int
    inserted: int
    skipped_existing: int
    skipped_excluded: int
    skipped_duplicate_input: int
    skipped_capacity: int
    skipped_missing_cik: int = 0
    skipped_ingest_limit: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "considered": self.considered,
            "eligible": self.eligible,
            "inserted": self.inserted,
            "skipped_existing": self.skipped_existing,
            "skipped_excluded": self.skipped_excluded,
            "skipped_duplicate_input": self.skipped_duplicate_input,
            "skipped_capacity": self.skipped_capacity,
            "skipped_missing_cik": self.skipped_missing_cik,
            "skipped_ingest_limit": self.skipped_ingest_limit,
        }


def _known_size(repo: UniverseExpansionRepository) -> int:
    return len(repo.list_all())


def _existing_identity(
    repo: UniverseExpansionRepository,
    symbol: str,
) -> Optional[Mapping[str, Any]]:
    identity = listing_identity(symbol)
    if not identity:
        return None
    return repo.get_by_symbol(identity)


def _resolve_non_negative(value: Optional[int], default: int) -> int:
    if value is None:
        return max(0, int(default))
    return max(0, int(value))


def enqueue_discovery_candidates(
    repo: UniverseExpansionRepository,
    candidates: Sequence[DiscoveryCandidate],
    *,
    discovery_capacity: Optional[int] = None,
    max_new_symbols_per_ingest: Optional[int] = None,
) -> DiscoveryIngestReport:
    """Insert PENDING rows for new identities only. Existing rows are untouched."""
    defaults = UniverseExpansionBudgetConfig()
    capacity = _resolve_non_negative(discovery_capacity, defaults.discovery_capacity)
    ingest_limit = _resolve_non_negative(
        max_new_symbols_per_ingest,
        defaults.max_new_symbols_per_ingest,
    )
    inserted = 0
    skipped_existing = 0
    skipped_capacity = 0
    skipped_ingest_limit = 0
    seen: set[str] = set()
    skipped_duplicate_input = 0
    known = _known_size(repo)

    for candidate in candidates:
        identity = listing_identity(candidate.symbol)
        if not identity:
            continue
        if identity in seen:
            skipped_duplicate_input += 1
            continue
        seen.add(identity)
        if _existing_identity(repo, identity) is not None:
            skipped_existing += 1
            continue
        if known + inserted >= capacity:
            skipped_capacity += 1
            continue
        if inserted >= ingest_limit:
            skipped_ingest_limit += 1
            continue
        repo.upsert_pending(
            identity,
            source_universe=candidate.source_universe,
            priority=int(candidate.priority),
        )
        inserted += 1

    return DiscoveryIngestReport(
        considered=len(candidates),
        eligible=len(seen),
        inserted=inserted,
        skipped_existing=skipped_existing,
        skipped_excluded=0,
        skipped_duplicate_input=skipped_duplicate_input,
        skipped_capacity=skipped_capacity,
        skipped_ingest_limit=skipped_ingest_limit,
    )


def ingest_us_equity_listings(
    repo: UniverseExpansionRepository,
    listings: Iterable[Mapping[str, Any]],
    *,
    discovery_capacity: Optional[int] = None,
    max_new_symbols_per_ingest: Optional[int] = None,
    source_universe: str = US_EQUITY_DISCOVERY_SOURCE,
) -> DiscoveryIngestReport:
    """Scale the known universe from injected listings. Zero provider calls."""
    listing_rows = list(listings)
    considered = len(listing_rows)
    skipped_excluded = 0
    skipped_missing_cik = 0
    seen_input: set[str] = set()
    skipped_duplicate_input = 0
    for row in listing_rows:
        identity = listing_identity(row.get("symbol") or row.get("ticker"))
        if identity and identity in seen_input:
            skipped_duplicate_input += 1
            continue
        if identity:
            seen_input.add(identity)
        reason = excluded_instrument_reason(
            symbol=identity,
            company_name=row.get("company_name") or row.get("name") or "",
            exchange_security_name=row.get("exchange_security_name") or "",
            is_etf=row.get("is_etf"),
        )
        if reason or not identity:
            skipped_excluded += 1
            continue
        if not str(row.get("cik") or "").strip():
            skipped_missing_cik += 1

    candidates = select_us_equity_discovery_candidates(
        listing_rows,
        source_universe=source_universe,
    )
    report = enqueue_discovery_candidates(
        repo,
        candidates,
        discovery_capacity=discovery_capacity,
        max_new_symbols_per_ingest=max_new_symbols_per_ingest,
    )
    return DiscoveryIngestReport(
        considered=considered,
        eligible=len(candidates),
        inserted=report.inserted,
        skipped_existing=report.skipped_existing,
        skipped_excluded=skipped_excluded,
        skipped_duplicate_input=skipped_duplicate_input + report.skipped_duplicate_input,
        skipped_capacity=report.skipped_capacity,
        skipped_missing_cik=skipped_missing_cik,
        skipped_ingest_limit=report.skipped_ingest_limit,
    )


def ingest_merged_exchange_listings(
    repo: UniverseExpansionRepository,
    *,
    nasdaq_rows: Sequence[Mapping[str, Any]] | None = None,
    other_rows: Sequence[Mapping[str, Any]] | None = None,
    sec_rows: Sequence[Mapping[str, Any]] | None = None,
    discovery_capacity: Optional[int] = None,
    max_new_symbols_per_ingest: Optional[int] = None,
) -> DiscoveryIngestReport:
    merged = merge_exchange_and_sec_listings(nasdaq_rows, other_rows, sec_rows)
    return ingest_us_equity_listings(
        repo,
        merged,
        discovery_capacity=discovery_capacity,
        max_new_symbols_per_ingest=max_new_symbols_per_ingest,
    )


def propose_external_discovery_symbols(
    symbols: Sequence[Any],
    *,
    repo: UniverseExpansionRepository,
    discovery_capacity: Optional[int] = None,
    max_new_symbols_per_ingest: Optional[int] = None,
    source: str = EXTERNAL_SIGNAL_SOURCE,
    names: Optional[Mapping[str, str]] = None,
) -> DiscoveryIngestReport:
    """Hook: external signal → proposed symbol → dedupe → discovery queue.

    Never sets participation status, never starts Scanner, never creates ADAY.
    """
    names = names or {}
    considered = 0
    skipped_excluded = 0
    skipped_duplicate_input = 0
    seen: set[str] = set()
    candidates: List[DiscoveryCandidate] = []
    for raw in symbols:
        considered += 1
        identity = listing_identity(raw)
        company_name = names.get(identity) or names.get(str(raw or "").strip().upper()) or ""
        reason = excluded_instrument_reason(
            symbol=identity,
            company_name=company_name,
            is_etf=False,
        )
        if reason or not identity:
            skipped_excluded += 1
            continue
        if identity in seen:
            skipped_duplicate_input += 1
            continue
        seen.add(identity)
        candidates.append(
            DiscoveryCandidate(
                symbol=identity,
                source_universe=source,
                priority=EXTERNAL_SIGNAL_PRIORITY,
                exchange="",
                company_name=company_name or identity,
            )
        )
    report = enqueue_discovery_candidates(
        repo,
        candidates,
        discovery_capacity=discovery_capacity,
        max_new_symbols_per_ingest=max_new_symbols_per_ingest,
    )
    return DiscoveryIngestReport(
        considered=considered,
        eligible=len(candidates),
        inserted=report.inserted,
        skipped_existing=report.skipped_existing,
        skipped_excluded=skipped_excluded,
        skipped_duplicate_input=skipped_duplicate_input,
        skipped_capacity=report.skipped_capacity,
        skipped_ingest_limit=report.skipped_ingest_limit,
    )
