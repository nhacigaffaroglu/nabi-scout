from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Sequence

from repositories.sec_company_facts_cache import SecCompanyFactsCache
from services.sec_participation_evidence_population import (
    AssessedEquityIdentity,
    AssessedEquityPopulation,
    resolve_assessed_equity_population,
)


CompanyFactsFetcher = Callable[[str], dict[str, Any]]


@dataclass(frozen=True)
class SecEvidenceRefreshPlan:
    population: AssessedEquityPopulation
    cache_hits: tuple[str, ...]
    cache_misses: tuple[str, ...]
    refresh_candidates: tuple[AssessedEquityIdentity, ...]
    expected_sec_calls: int
    identity_blocked: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "assessed_equities": len(self.population.assessed),
            "symbols": list(self.population.symbols),
            "cik_mapped": [
                {"symbol": item.symbol, "cik": item.cik, "source": item.cik_source}
                for item in self.population.assessed
                if item.cik
            ],
            "cik_problems": {
                "missing_cik": list(self.population.missing_cik),
                "cik_conflicts": list(self.population.cik_conflicts),
                "duplicate_ciks": list(self.population.duplicate_ciks),
            },
            "catalog_etfs_excluded": list(self.population.catalog_excluded),
            "pending_excluded": list(self.population.pending_excluded),
            "cache_hits": list(self.cache_hits),
            "cache_misses": list(self.cache_misses),
            "refresh_candidates": [item.symbol for item in self.refresh_candidates],
            "expected_sec_calls": self.expected_sec_calls,
            "identity_blocked": list(self.identity_blocked),
            "sec_provider_calls_executed": 0,
        }


@dataclass(frozen=True)
class SecEvidenceFetchResult:
    stored: tuple[str, ...]
    reused: tuple[str, ...]
    failed: tuple[tuple[str, str], ...]
    sec_calls: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "stored": list(self.stored),
            "reused": list(self.reused),
            "failed": [{"symbol": symbol, "error": error} for symbol, error in self.failed],
            "sec_calls": self.sec_calls,
        }


def plan_sec_evidence_refresh(
    *,
    queue_rows: Sequence[Mapping[str, Any]],
    snapshots_by_symbol: Mapping[str, Mapping[str, Any]],
    candidates_by_symbol: Optional[Mapping[str, Mapping[str, Any]]] = None,
    cache: Optional[SecCompanyFactsCache] = None,
) -> SecEvidenceRefreshPlan:
    population = resolve_assessed_equity_population(
        queue_rows=queue_rows,
        snapshots_by_symbol=snapshots_by_symbol,
        candidates_by_symbol=candidates_by_symbol,
    )
    cache = cache or SecCompanyFactsCache()
    hits: list[str] = []
    misses: list[str] = []
    refresh: list[AssessedEquityIdentity] = []
    identity_blocked: list[str] = []
    miss_ciks: list[str] = []

    for item in population.assessed:
        if not item.fetchable:
            identity_blocked.append(item.symbol)
            continue
        cached = cache.get_latest(symbol=item.symbol, cik=item.cik)
        if cached is not None and cached.cik == item.cik:
            hits.append(item.symbol)
            continue
        misses.append(item.symbol)
        refresh.append(item)
        if item.cik and item.cik not in miss_ciks:
            miss_ciks.append(item.cik)

    return SecEvidenceRefreshPlan(
        population=population,
        cache_hits=tuple(hits),
        cache_misses=tuple(misses),
        refresh_candidates=tuple(refresh),
        expected_sec_calls=len(miss_ciks),
        identity_blocked=tuple(identity_blocked),
    )


def fetch_sec_evidence(
    plan: SecEvidenceRefreshPlan,
    *,
    fetcher: CompanyFactsFetcher,
    cache: SecCompanyFactsCache,
) -> SecEvidenceFetchResult:
    """Retrieve Company Facts and persist cache only. Does not assess participation."""
    stored: list[str] = []
    reused: list[str] = []
    failed: list[tuple[str, str]] = []
    fetched_by_cik: dict[str, dict[str, Any]] = {}
    sec_calls = 0

    for item in plan.refresh_candidates:
        if not item.cik:
            failed.append((item.symbol, "missing_cik"))
            continue
        payload = fetched_by_cik.get(item.cik)
        if payload is None:
            try:
                payload = fetcher(item.cik)
            except Exception as exc:
                failed.append((item.symbol, str(exc)))
                continue
            fetched_by_cik[item.cik] = payload
            sec_calls += 1
        try:
            _evidence, created = cache.store_if_new(
                symbol=item.symbol,
                cik=item.cik,
                raw_payload=payload,
                http_status=200,
            )
        except Exception as exc:
            failed.append((item.symbol, str(exc)))
            continue
        if created:
            stored.append(item.symbol)
        else:
            reused.append(item.symbol)

    return SecEvidenceFetchResult(
        stored=tuple(stored),
        reused=tuple(reused),
        failed=tuple(failed),
        sec_calls=sec_calls,
    )
