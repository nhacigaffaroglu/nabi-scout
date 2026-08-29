"""Canonical Security Master v1: store and resolve instrument facts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional, Sequence

from repositories.security_master_repository import SecurityMasterRepository
from services.security_identity_contract import IDENTITY_FACT_SOURCES
from services.security_master_contract import (
    IDENTIFIER_TYPE_CUSIP,
    IDENTIFIER_TYPE_ISIN,
    IDENTIFIER_TYPE_SEDOL,
    IDENTIFIER_TYPE_TICKER,
    INSTRUMENT_CASH,
    INSTRUMENT_COMMODITY,
    INSTRUMENT_EQUITY,
    INSTRUMENT_ETF,
    INSTRUMENT_FIXED_INCOME,
    INSTRUMENT_OTHER,
    INSTRUMENT_REIT,
    INSTRUMENT_SUKUK,
    INSTRUMENT_UNKNOWN,
    RESOLUTION_CONFLICT,
    RESOLUTION_RESOLVED,
    RESOLUTION_UNKNOWN,
    SOURCE_CANONICAL_STATIC,
    SOURCE_PRECEDENCE,
    SOURCE_PROVIDER_EXPLICIT,
    SOURCE_US_LISTING,
    SecurityFact,
    SecurityResolution,
)
from services.security_master_listing_evidence import (
    listing_exchange,
    listing_index_key,
    listing_instrument_type,
)
from services.universe_listing_identity import listing_identity
from services.wealth_asset_classification import (
    KNOWN_EQUITY_TR,
    KNOWN_EQUITY_US,
)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def infer_identifier_type(raw: Any) -> str:
    text = str(raw or "").strip().upper().replace(" ", "")
    if not text:
        return IDENTIFIER_TYPE_TICKER
    if len(text) == 12 and text[:2].isalpha() and text[2:].isalnum():
        return IDENTIFIER_TYPE_ISIN
    if len(text) == 9 and text.isalnum() and any(ch.isdigit() for ch in text) and not text.isalpha():
        return IDENTIFIER_TYPE_CUSIP
    if len(text) == 7 and text.isalnum() and any(ch.isdigit() for ch in text):
        return IDENTIFIER_TYPE_SEDOL
    return IDENTIFIER_TYPE_TICKER


def normalize_identifier(raw: Any, *, identifier_type: Optional[str] = None) -> tuple[str, str]:
    inferred = str(identifier_type or infer_identifier_type(raw)).strip().upper()
    if inferred == IDENTIFIER_TYPE_TICKER:
        return listing_identity(raw), inferred
    return str(raw or "").strip().upper().replace(" ", ""), inferred


def _row_to_fact(row: Mapping[str, Any]) -> SecurityFact:
    return SecurityFact(
        identifier=str(row.get("identifier") or ""),
        identifier_type=str(row.get("identifier_type") or ""),
        instrument_type=str(row.get("instrument_type") or INSTRUMENT_UNKNOWN),
        source=str(row.get("source") or ""),
        observed_at=str(row.get("observed_at") or ""),
        symbol=row.get("symbol"),
        exchange=row.get("exchange"),
        issuer_name=row.get("issuer_name"),
        source_reference=row.get("source_reference"),
        metadata=dict(row.get("metadata") or {}),
    )


def _canonical_static_fact(identifier: str, identifier_type: str) -> Optional[SecurityFact]:
    if identifier_type != IDENTIFIER_TYPE_TICKER:
        return None
    if identifier in KNOWN_EQUITY_US or identifier in KNOWN_EQUITY_TR:
        return SecurityFact(
            identifier=identifier,
            identifier_type=IDENTIFIER_TYPE_TICKER,
            instrument_type=INSTRUMENT_EQUITY,
            source=SOURCE_CANONICAL_STATIC,
            observed_at=_utcnow_iso(),
            symbol=identifier,
            source_reference="wealth_asset_classification.KNOWN_EQUITY",
        )
    return None


def listing_row_to_fact(row: Mapping[str, Any]) -> Optional[SecurityFact]:
    identity = listing_index_key(row)
    instrument = listing_instrument_type(row)
    if not identity or not instrument:
        return None
    return SecurityFact(
        identifier=identity,
        identifier_type=IDENTIFIER_TYPE_TICKER,
        instrument_type=instrument,
        source=SOURCE_US_LISTING,
        observed_at=_utcnow_iso(),
        symbol=identity,
        exchange=listing_exchange(row) or None,
        issuer_name=str(row.get("company_name") or row.get("name") or "") or None,
        source_reference="nasdaq_trader+sec_cik",
        metadata={"cik": str(row.get("cik") or "").strip()},
    )


class SecurityMasterUnavailableError(RuntimeError):
    """Production Security Master facts are required but no client was provided."""


def memory_security_master(
    rows: Sequence[Mapping[str, Any]],
    *,
    include_canonical_static: bool = True,
) -> "SecurityMasterService":
    """Build an in-memory service from already-loaded fact rows."""
    repo = SecurityMasterRepository()
    for row in rows:
        key = (
            str(row.get("identifier") or "").strip().upper(),
            str(row.get("identifier_type") or "").strip().upper(),
            str(row.get("source") or "").strip(),
        )
        if not key[0] or not key[1] or not key[2]:
            continue
        repo._memory[key] = dict(row)
    return SecurityMasterService(repo=repo, include_canonical_static=include_canonical_static)


def production_security_master(
    client: Any,
    *,
    include_canonical_static: bool = True,
) -> "SecurityMasterService":
    """Load production facts once, then resolve in-memory. Fail closed without a client."""
    if client is None:
        raise SecurityMasterUnavailableError(
            "Production Security Master requires a database client."
        )
    return memory_security_master(
        SecurityMasterRepository(client).list_all(),
        include_canonical_static=include_canonical_static,
    )


def security_master_from_wealth(wealth: Any) -> "SecurityMasterService":
    client = getattr(wealth, "client", None) if wealth is not None else None
    return production_security_master(client)


def try_security_master_from_wealth(wealth: Any) -> Optional["SecurityMasterService"]:
    """Inject when a client exists. Tests/stubs without a client stay explicit None."""
    client = getattr(wealth, "client", None) if wealth is not None else None
    if client is None:
        return None
    return production_security_master(client)


class SecurityMasterService:
    def __init__(
        self,
        *,
        repo: Optional[SecurityMasterRepository] = None,
        listing_index: Optional[Mapping[str, Mapping[str, Any]]] = None,
        include_canonical_static: bool = True,
    ) -> None:
        self.repo = repo or SecurityMasterRepository()
        self.listing_index = dict(listing_index or {})
        self.include_canonical_static = include_canonical_static

    def register_listing_index(self, rows: Iterable[Mapping[str, Any]]) -> int:
        added = 0
        for row in rows:
            key = listing_index_key(row)
            if not key or key in self.listing_index:
                continue
            self.listing_index[key] = dict(row)
            added += 1
        return added

    def upsert_security_fact(self, fact: SecurityFact) -> Dict[str, Any]:
        identifier, identifier_type = normalize_identifier(
            fact.identifier, identifier_type=fact.identifier_type
        )
        normalized = SecurityFact(
            identifier=identifier,
            identifier_type=identifier_type,
            instrument_type=str(fact.instrument_type or INSTRUMENT_UNKNOWN).strip().upper(),
            source=str(fact.source or "").strip(),
            observed_at=fact.observed_at or _utcnow_iso(),
            symbol=fact.symbol or identifier,
            exchange=fact.exchange,
            issuer_name=fact.issuer_name,
            source_reference=fact.source_reference,
            metadata=dict(fact.metadata or {}),
        )
        return self.repo.upsert_fact(normalized)

    def ingest_listing_facts(self, rows: Sequence[Mapping[str, Any]]) -> int:
        facts = []
        for row in rows:
            fact = listing_row_to_fact(row)
            if fact is None:
                continue
            facts.append(fact)
        self.repo.persist_facts(facts)
        self.register_listing_index(rows)
        return len(facts)

    def ingest_provider_explicit_fact(
        self,
        identifier: Any,
        instrument_type: str,
        *,
        identifier_type: Optional[str] = None,
        issuer_name: Optional[str] = None,
        observed_at: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        ident, itype = normalize_identifier(identifier, identifier_type=identifier_type)
        if not ident:
            return None
        fact = SecurityFact(
            identifier=ident,
            identifier_type=itype,
            instrument_type=str(instrument_type).strip().upper(),
            source=SOURCE_PROVIDER_EXPLICIT,
            observed_at=observed_at or _utcnow_iso(),
            symbol=ident if itype == IDENTIFIER_TYPE_TICKER else None,
            issuer_name=issuer_name,
            source_reference="holding.asset_type",
        )
        return self.upsert_security_fact(fact)

    def get_security_facts(
        self,
        identifier: Any,
        *,
        identifier_type: Optional[str] = None,
    ) -> list[SecurityFact]:
        ident, itype = normalize_identifier(identifier, identifier_type=identifier_type)
        if not ident:
            return []
        rows = self.repo.list_facts(ident, identifier_type=itype)
        return [_row_to_fact(row) for row in rows]

    def resolve_security(
        self,
        identifier: Any,
        identifier_type: Optional[str] = None,
    ) -> SecurityResolution:
        ident, itype = normalize_identifier(identifier, identifier_type=identifier_type)
        if not ident:
            return SecurityResolution(
                identifier="",
                identifier_type=itype,
                instrument_type=INSTRUMENT_UNKNOWN,
                status=RESOLUTION_UNKNOWN,
                source=None,
                observed_at=None,
                limitation="EMPTY_IDENTIFIER",
            )
        candidates = [
            row
            for row in self.get_security_facts(ident, identifier_type=itype)
            if row.source not in IDENTITY_FACT_SOURCES
        ]
        sources = {row.source for row in candidates}
        listing_row = self.listing_index.get(ident) if itype == IDENTIFIER_TYPE_TICKER else None
        listing_fact = listing_row_to_fact(listing_row) if listing_row else None
        if listing_fact is not None and SOURCE_US_LISTING not in sources:
            candidates.append(listing_fact)
        if self.include_canonical_static and SOURCE_CANONICAL_STATIC not in sources:
            static = _canonical_static_fact(ident, itype)
            if static is not None:
                candidates.append(static)
        if not candidates:
            return SecurityResolution(
                identifier=ident,
                identifier_type=itype,
                instrument_type=INSTRUMENT_UNKNOWN,
                status=RESOLUTION_UNKNOWN,
                source=None,
                observed_at=None,
                limitation="NO_EVIDENCE",
            )
        ranked = sorted(
            candidates,
            key=lambda item: (
                SOURCE_PRECEDENCE.get(item.source, 1000),
                item.source,
                item.observed_at,
            ),
        )
        best_rank = SOURCE_PRECEDENCE.get(ranked[0].source, 1000)
        top = [item for item in ranked if SOURCE_PRECEDENCE.get(item.source, 1000) == best_rank]
        types = {item.instrument_type for item in top}
        if len(types) > 1:
            return SecurityResolution(
                identifier=ident,
                identifier_type=itype,
                instrument_type=INSTRUMENT_UNKNOWN,
                status=RESOLUTION_CONFLICT,
                source=None,
                observed_at=None,
                facts=tuple(ranked),
                limitation="SOURCE_CONFLICT",
            )
        chosen = top[0]
        return SecurityResolution(
            identifier=ident,
            identifier_type=itype,
            instrument_type=chosen.instrument_type,
            status=RESOLUTION_RESOLVED,
            source=chosen.source,
            observed_at=chosen.observed_at,
            facts=tuple(ranked),
        )


EXPLICIT_HOLDING_TO_INSTRUMENT = {
    "equity": INSTRUMENT_EQUITY,
    "stock": INSTRUMENT_EQUITY,
    "common stock": INSTRUMENT_EQUITY,
    "sukuk": INSTRUMENT_SUKUK,
    "fixed_income": INSTRUMENT_FIXED_INCOME,
    "fixed income": INSTRUMENT_FIXED_INCOME,
    "bond": INSTRUMENT_FIXED_INCOME,
    "reit": INSTRUMENT_REIT,
    "real_estate": INSTRUMENT_REIT,
    "real estate": INSTRUMENT_REIT,
    "cash": INSTRUMENT_CASH,
    "cash_equivalent": INSTRUMENT_CASH,
    "commodity": INSTRUMENT_COMMODITY,
    "gold": INSTRUMENT_COMMODITY,
}


def summarize_holding_coverage(
    holdings: Sequence[Mapping[str, Any] | Any],
    *,
    security_master: Optional["SecurityMasterService"] = None,
) -> dict[str, Any]:
    """Read-only coverage tally for lookthrough identifiers. No provider calls."""
    master = security_master or SecurityMasterService()
    buckets = {
        INSTRUMENT_EQUITY: 0.0,
        INSTRUMENT_REIT: 0.0,
        INSTRUMENT_SUKUK: 0.0,
        INSTRUMENT_FIXED_INCOME: 0.0,
        INSTRUMENT_CASH: 0.0,
        INSTRUMENT_ETF: 0.0,
        INSTRUMENT_COMMODITY: 0.0,
        INSTRUMENT_OTHER: 0.0,
        INSTRUMENT_UNKNOWN: 0.0,
    }
    sources: set[str] = set()
    count = 0
    weight_total = 0.0
    for raw in holdings:
        if hasattr(raw, "underlying_symbol"):
            identifier = raw.underlying_symbol
            asset_type = raw.asset_type
            weight = float(raw.weight_pct or 0.0)
        else:
            identifier = raw.get("underlying_symbol") or raw.get("identifier")
            asset_type = raw.get("asset_type")
            weight = float(raw.get("weight_pct") or 0.0)
        count += 1
        weight_total += weight
        explicit = EXPLICIT_HOLDING_TO_INSTRUMENT.get(str(asset_type or "").strip().lower())
        if explicit is not None:
            instrument = explicit
            sources.add(SOURCE_PROVIDER_EXPLICIT)
        else:
            resolution = master.resolve_security(identifier)
            if resolution.status == RESOLUTION_RESOLVED:
                instrument = resolution.instrument_type
                if resolution.source:
                    sources.add(resolution.source)
            else:
                instrument = INSTRUMENT_UNKNOWN
        buckets[instrument] = buckets.get(instrument, 0.0) + weight
    return {
        "holding_count": count,
        "weight_total": round(weight_total, 4),
        "classified_EQUITY": round(buckets[INSTRUMENT_EQUITY], 4),
        "classified_REIT": round(buckets[INSTRUMENT_REIT], 4),
        "classified_SUKUK": round(buckets[INSTRUMENT_SUKUK], 4),
        "classified_FIXED_INCOME": round(buckets[INSTRUMENT_FIXED_INCOME], 4),
        "classified_CASH": round(buckets[INSTRUMENT_CASH], 4),
        "classified_ETF": round(buckets[INSTRUMENT_ETF], 4),
        "classified_OTHER": round(
            buckets[INSTRUMENT_ETF] + buckets[INSTRUMENT_OTHER] + buckets[INSTRUMENT_COMMODITY],
            4,
        ),
        "UNKNOWN": round(buckets[INSTRUMENT_UNKNOWN], 4),
        "evidence_sources_used": tuple(sorted(sources)),
    }
