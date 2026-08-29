"""Plan strategic-layer discovery through the existing queue.

Never marks Uygun. Never infers sukuk/REIT from names or fund mandates.
Default path is dry-run. Production enqueue reuses propose_external_discovery_symbols.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from repositories.universe_expansion_repository import UniverseExpansionRepository
from services.reit_evidence_contract import classify_from_name_or_fund as reit_from_name
from services.participation_cik_resolver import is_usable_cik, normalize_resolved_cik
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.security_master_contract import INSTRUMENT_EQUITY, SOURCE_US_LISTING
from services.strategic_layer_discovery_contract import (
    ACTIONABILITY_FAIL,
    ACTIONABILITY_NOT_RUN,
    ACTIONABILITY_PASS,
    CLASSIFICATION_FAIL,
    CLASSIFICATION_PASS,
    CLASSIFICATION_UNKNOWN,
    GATE_ELIGIBLE,
    REASON_ROBUST_UW_REAL_ESTATE,
    SUPPORT_FULL,
    SUPPORT_PARTIAL,
    SUPPORT_UNSUPPORTED,
    StrategicDiscoveryRecord,
    three_gate_eligibility,
)
from services.sukuk_evidence_contract import classify_from_name_or_fund as sukuk_from_name
from services.universe_discovery_service import DiscoveryIngestReport, propose_external_discovery_symbols
from services.universe_listing_identity import (
    STRATEGIC_LAYER_DISCOVERY_SOURCE,
    excluded_instrument_reason,
    listing_identity,
)

# 7J.6/7J.7 already audited. Do not rediscover.
CLOSED_STRATEGIC_REIT_SYMBOLS = frozenset(
    {"WELL", "PLD", "EQIX", "O", "AMT", "SPG", "DLR", "PSA"}
)


@dataclass(frozen=True)
class StrategicEnqueuePlan:
    dry_run: bool
    considered: int
    proposed_insert: int
    skipped_existing: int
    skipped_excluded: int
    skipped_etf: int
    inserted: int
    write_tables: tuple[str, ...]
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "considered": self.considered,
            "proposed_insert": self.proposed_insert,
            "skipped_existing": self.skipped_existing,
            "skipped_excluded": self.skipped_excluded,
            "skipped_etf": self.skipped_etf,
            "inserted": self.inserted,
            "write_tables": list(self.write_tables),
            "reasons": list(self.reasons),
        }


def classification_from_evidence(
    *,
    target_layer: str,
    explicit_layer: Optional[str] = None,
    security_name: str = "",
    fund_symbol: str = "",
) -> str:
    """Name and fund mandate never pass. Explicit economic layer must match."""
    sukuk_from_name(security_name, fund_symbol)
    reit_from_name(security_name, fund_symbol)
    if explicit_layer and str(explicit_layer).strip().lower() == str(target_layer).strip().lower():
        return CLASSIFICATION_PASS
    if explicit_layer:
        return CLASSIFICATION_FAIL
    return CLASSIFICATION_UNKNOWN


def evaluate_discovery_record(row: StrategicDiscoveryRecord) -> str:
    return three_gate_eligibility(
        classification_status=row.classification_status,
        participation_status=row.participation_status,
        actionability=row.actionability,
        discovery_reason=row.discovery_reason,
    )


def actionability_from_candidate(raw: Optional[Mapping[str, Any]]) -> str:
    if raw is None:
        return ACTIONABILITY_NOT_RUN
    from services.candidate_pipeline_presentation import is_actionable_opportunity

    if is_actionable_opportunity(dict(raw)):
        return ACTIONABILITY_PASS
    return ACTIONABILITY_FAIL


def plan_strategic_enqueue(
    symbols: Sequence[Any],
    *,
    repo: UniverseExpansionRepository,
    names: Optional[Mapping[str, str]] = None,
    dry_run: bool = True,
    discovery_capacity: Optional[int] = None,
    max_new_symbols_per_ingest: Optional[int] = None,
) -> StrategicEnqueuePlan:
    """Reuse the canonical discovery hook. Dry-run by default."""
    names = names or {}
    considered = 0
    skipped_existing = 0
    skipped_excluded = 0
    skipped_etf = 0
    proposed = 0
    eligible: list[str] = []
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
            if reason in {"etf", "catalog_etf"}:
                skipped_etf += 1
            continue
        if repo.get_by_symbol(identity) is not None:
            skipped_existing += 1
            continue
        proposed += 1
        eligible.append(identity)
    inserted = 0
    write_tables: tuple[str, ...] = ()
    if not dry_run and eligible:
        report: DiscoveryIngestReport = propose_external_discovery_symbols(
            eligible,
            repo=repo,
            discovery_capacity=discovery_capacity,
            max_new_symbols_per_ingest=max_new_symbols_per_ingest,
            source=STRATEGIC_LAYER_DISCOVERY_SOURCE,
            names=names,
        )
        inserted = report.inserted
        write_tables = ("universe_expansion_queue",)
    return StrategicEnqueuePlan(
        dry_run=dry_run,
        considered=considered,
        proposed_insert=proposed,
        skipped_existing=skipped_existing,
        skipped_excluded=skipped_excluded,
        skipped_etf=skipped_etf,
        inserted=inserted,
        write_tables=write_tables,
        reasons=("DRY_RUN" if dry_run else "ENQUEUED_PENDING_ONLY",),
    )


def eligible_filler_count(rows: Sequence[StrategicDiscoveryRecord]) -> int:
    return sum(1 for row in rows if evaluate_discovery_record(row) == GATE_ELIGIBLE)


def discovery_hint_is_not_classification(hint: Any = None) -> str:
    """SPRE membership, sector labels, and peer lists never classify."""
    del hint
    return CLASSIFICATION_UNKNOWN


def tickers_from_sec_sic_lookup(
    sic_ciks: Sequence[Any],
    sec_lookup: Mapping[str, Mapping[str, Any]],
) -> tuple[str, ...]:
    """Join official SIC CIKs to listed tickers. SIC is a discovery hint only."""
    wanted = {normalize_resolved_cik(cik) for cik in sic_ciks}
    wanted.discard(None)
    out: list[str] = []
    seen: set[str] = set()
    for raw_ticker, row in sec_lookup.items():
        identity = listing_identity(raw_ticker)
        cik = normalize_resolved_cik((row or {}).get("cik"))
        if not identity or cik not in wanted or identity in seen:
            continue
        seen.add(identity)
        out.append(identity)
    return tuple(out)


def may_run_reit_economic_classification(*, participation_status: str) -> bool:
    """OpenFIGI REIT persist is Participation-first. Uygun only."""
    return str(participation_status or "").strip() == PARTICIPATION_STATUS_UYGUN


def may_run_actionability(*, participation_status: str, classification_status: str) -> bool:
    """Scanner/actionability only after Uygun and explicit REIT PASS."""
    if not may_run_reit_economic_classification(participation_status=participation_status):
        return False
    return str(classification_status or "").strip().upper() == CLASSIFICATION_PASS


def select_us_listing_discovery_candidates(
    hint_symbols: Sequence[Any],
    *,
    listing_rows: Mapping[str, Mapping[str, Any]],
    queued_symbols: Sequence[Any] = (),
    closed_symbols: Sequence[Any] = (),
    names: Optional[Mapping[str, str]] = None,
    limit: int = 30,
) -> tuple[dict[str, Any], ...]:
    """Keep US-listed commons with a pricing/SEC path. Hint is not evidence."""
    names = names or {}
    queued = {listing_identity(item) for item in queued_symbols if listing_identity(item)}
    closed = {
        listing_identity(item)
        for item in (*(closed_symbols or ()), *CLOSED_STRATEGIC_REIT_SYMBOLS)
        if listing_identity(item)
    }
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    cap = max(0, int(limit))
    for raw in hint_symbols:
        identity = listing_identity(raw)
        if not identity or identity in seen:
            continue
        seen.add(identity)
        if identity in closed or identity in queued:
            continue
        company_name = names.get(identity) or ""
        if excluded_instrument_reason(symbol=identity, company_name=company_name):
            continue
        listing = dict(listing_rows.get(identity) or {})
        instrument = str(listing.get("instrument_type") or "").strip().upper()
        source = str(listing.get("source") or "").strip()
        cik = listing.get("cik")
        us_equity = instrument == INSTRUMENT_EQUITY and source == SOURCE_US_LISTING
        has_cik = is_usable_cik(cik)
        if us_equity and has_cik:
            support = SUPPORT_FULL
        elif us_equity:
            support = SUPPORT_PARTIAL
        else:
            support = SUPPORT_UNSUPPORTED
        if support != SUPPORT_FULL:
            continue
        selected.append(
            {
                "symbol": identity,
                "exchange": listing.get("exchange") or "",
                "cik": str(cik).strip(),
                "provider_support": support,
                "classification_status": discovery_hint_is_not_classification(
                    listing.get("hint")
                ),
                "economic_layer": None,
                "discovery_source": STRATEGIC_LAYER_DISCOVERY_SOURCE,
                "discovery_reason": REASON_ROBUST_UW_REAL_ESTATE,
            }
        )
        if len(selected) >= cap:
            break
    return tuple(selected)
