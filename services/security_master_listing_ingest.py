"""Controlled Security Master listing-fact ingest.

Writes instrument facts only. Never enqueues universe symbols, never runs
Participation, and never calls discovery ingest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from repositories.security_master_repository import PersistFactsResult
from services.security_master_contract import INSTRUMENT_EQUITY, INSTRUMENT_ETF
from services.security_master_service import (
    SecurityMasterService,
    listing_row_to_fact,
)
from services.universe_discovery_listings import merge_exchange_and_sec_listings

WRITE_TABLE = "security_master"
READ_TABLES = frozenset(
    {
        WRITE_TABLE,
        "universe_expansion_queue",
        "investment_candidates",
        "participation_assessment_snapshots",
        "fund_holdings",
        "fund_holdings_snapshots",
        "wealth_portfolios",
        "wealth_adviser_goals",
        "wealth_transactions",
        "universe_expansion_runs",
    }
)
_WRITE_METHODS = frozenset({"insert", "update", "upsert", "delete"})


class SecurityMasterWriteGuardError(RuntimeError):
    pass


class SecurityMasterWriteGuard:
    """Fail closed: production writes may only target security_master."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def table(self, name: str):
        table_name = str(name or "").strip()
        if table_name not in READ_TABLES:
            raise SecurityMasterWriteGuardError(f"blocked table access: {table_name}")
        return _GuardedTable(self._client.table(table_name), table_name)

    def __getattr__(self, name: str):
        return getattr(self._client, name)


class _GuardedTable:
    def __init__(self, inner: Any, table_name: str) -> None:
        self._inner = inner
        self._table_name = table_name

    def __getattr__(self, name: str):
        if name in _WRITE_METHODS and self._table_name != WRITE_TABLE:
            def _blocked(*args: Any, **kwargs: Any) -> Any:
                raise SecurityMasterWriteGuardError(
                    f"blocked write on {self._table_name}.{name}"
                )

            return _blocked
        return getattr(self._inner, name)


@dataclass(frozen=True)
class ListingFactIngestReport:
    nasdaq_rows: int
    other_rows: int
    sec_rows: int
    merged_rows: int
    eligible: int
    equity_facts: int
    etf_facts: int
    skipped_unproven: int
    inserted: int
    updated: int
    unchanged: int
    fmp_calls: int = 0
    llm_calls: int = 0
    universe_queue_writes: int = 0
    unexpected_instrument_types: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nasdaq_rows": self.nasdaq_rows,
            "other_rows": self.other_rows,
            "sec_rows": self.sec_rows,
            "merged_rows": self.merged_rows,
            "eligible": self.eligible,
            "equity_facts": self.equity_facts,
            "etf_facts": self.etf_facts,
            "skipped_unproven": self.skipped_unproven,
            "inserted": self.inserted,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "fmp_calls": self.fmp_calls,
            "llm_calls": self.llm_calls,
            "universe_queue_writes": self.universe_queue_writes,
            "unexpected_instrument_types": list(self.unexpected_instrument_types),
        }


def ingest_merged_us_listing_facts(
    service: SecurityMasterService,
    nasdaq_rows: Sequence[Mapping[str, Any]] | None = None,
    other_rows: Sequence[Mapping[str, Any]] | None = None,
    sec_rows: Sequence[Mapping[str, Any]] | None = None,
) -> ListingFactIngestReport:
    """Persist EQUITY/ETF facts from canonical listing feeds. No queue writes."""
    nasdaq = list(nasdaq_rows or ())
    other = list(other_rows or ())
    sec = list(sec_rows or ())
    merged = merge_exchange_and_sec_listings(nasdaq, other, sec)
    facts = []
    equity = etf = skipped = 0
    unexpected: list[str] = []
    for row in merged:
        fact = listing_row_to_fact(row)
        if fact is None:
            skipped += 1
            continue
        if fact.instrument_type == INSTRUMENT_EQUITY:
            equity += 1
        elif fact.instrument_type == INSTRUMENT_ETF:
            etf += 1
        else:
            unexpected.append(fact.instrument_type)
            skipped += 1
            continue
        facts.append(fact)
    result: PersistFactsResult = service.repo.persist_facts(facts)
    service.register_listing_index(merged)
    return ListingFactIngestReport(
        nasdaq_rows=len(nasdaq),
        other_rows=len(other),
        sec_rows=len(sec),
        merged_rows=len(merged),
        eligible=len(facts),
        equity_facts=equity,
        etf_facts=etf,
        skipped_unproven=skipped,
        inserted=result.inserted,
        updated=result.updated,
        unchanged=result.unchanged,
        unexpected_instrument_types=tuple(sorted(set(unexpected))),
    )


def planned_listing_source_path() -> dict[str, Any]:
    return {
        "planned_Nasdaq_calls": [
            "nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt",
            "nasdaqtrader.com/dynamic/symdir/otherlisted.txt",
        ],
        "planned_SEC_calls": [
            "sec.gov/files/company_tickers_exchange.json",
        ],
        "planned_FMP_calls": 0,
        "planned_LLM_calls": 0,
        "expected_security_master_writes": "positive EQUITY and ETF listing facts only",
        "expected_universe_queue_writes": 0,
        "not_called": [
            "universe discovery queue ingest",
            "Participation",
            "FMP",
        ],
    }
