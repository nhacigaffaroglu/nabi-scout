"""Bounded SEC 8-K Signal Intelligence ingestion.

Lookback strategy: each run re-reads a bounded recent filing window
(default 90 days). Persistence is idempotent, so no last-run cursor is
used and filings cannot be silently skipped.

Uses existing SECFinancialClient submissions + User-Agent. No FMP, news,
KAP, or social calls. Does not download filing HTML.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Mapping, Optional, Sequence

from repositories.signal_intelligence_repository import InMemorySignalIntelligenceRepository
from services.participation_cik_resolver import resolve_participation_cik
from services.sec_eight_k_discovery import SecEightKFiling, discover_recent_8k_filings
from services.signal_disclosure_adapters import raw_inputs_from_8k_filing
from services.signal_intelligence_service import IngestSignalResult, SignalIntelligenceService


SubmissionsLoader = Callable[[str], Mapping[str, Any]]


@dataclass(frozen=True)
class SymbolIngestResult:
    symbol: str
    cik: Optional[str]
    filings: int = 0
    events: int = 0
    evidence: int = 0
    event_writes: int = 0
    evidence_writes: int = 0
    error: Optional[str] = None
    ingest_results: tuple[IngestSignalResult, ...] = ()
    discovered: tuple[SecEightKFiling, ...] = ()


@dataclass(frozen=True)
class SecSignalIngestReport:
    lookback_days: int
    max_filings_per_symbol: int
    symbols: tuple[str, ...]
    event_writes: int
    evidence_writes: int
    failed_symbols: tuple[str, ...]
    results: tuple[SymbolIngestResult, ...] = field(default_factory=tuple)
    provider_calls_sec: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "lookback_days": self.lookback_days,
            "max_filings_per_symbol": self.max_filings_per_symbol,
            "symbols": list(self.symbols),
            "event_writes": self.event_writes,
            "evidence_writes": self.evidence_writes,
            "failed_symbols": list(self.failed_symbols),
            "provider_calls_sec": self.provider_calls_sec,
            "results": [
                {
                    "symbol": item.symbol,
                    "cik": item.cik,
                    "filings": item.filings,
                    "events": item.events,
                    "evidence": item.evidence,
                    "event_writes": item.event_writes,
                    "evidence_writes": item.evidence_writes,
                    "error": item.error,
                }
                for item in self.results
            ],
        }


class WriteCountRepo:
    def __init__(self, inner) -> None:
        self._inner = inner
        self.event_writes = 0
        self.evidence_writes = 0

    def upsert_event(self, payload):
        self.event_writes += 1
        return self._inner.upsert_event(payload)

    def upsert_evidence(self, payload):
        self.evidence_writes += 1
        return self._inner.upsert_evidence(payload)

    def __getattr__(self, name: str):
        return getattr(self._inner, name)


def resolve_signal_cik(
    symbol: str,
    *,
    cik_by_symbol: Optional[Mapping[str, str]] = None,
    candidate: Optional[Mapping[str, Any]] = None,
    sec_ticker_lookup: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> Optional[str]:
    mapped = (cik_by_symbol or {}).get(str(symbol or "").strip().upper())
    if mapped:
        return str(mapped).strip().lstrip("0") or None
    resolution = resolve_participation_cik(
        symbol,
        candidate_cik=(candidate or {}).get("cik"),
        sec_ticker_lookup=sec_ticker_lookup,
    )
    return resolution.cik


def run_sec_signal_ingestion(
    symbols: Sequence[str],
    *,
    repo=None,
    submissions_by_symbol: Optional[Mapping[str, Mapping[str, Any]]] = None,
    submissions_loader: Optional[SubmissionsLoader] = None,
    cik_by_symbol: Optional[Mapping[str, str]] = None,
    candidates_by_symbol: Optional[Mapping[str, Mapping[str, Any]]] = None,
    sec_ticker_lookup: Optional[Mapping[str, Mapping[str, Any]]] = None,
    lookback_days: int = 90,
    max_filings_per_symbol: int = 20,
    as_of: Optional[date] = None,
    sleep_seconds: float = 0.0,
) -> SecSignalIngestReport:
    """Ingest recent 8-K filings for a bounded symbol list.

    Future orchestration hook: scripts/run_sec_signal_ingestion.py
    called by an existing daily job. Schedule is not activated here.
    """
    inner = repo if repo is not None else InMemorySignalIntelligenceRepository()
    counted = WriteCountRepo(inner)
    service = SignalIntelligenceService(counted)
    results: list[SymbolIngestResult] = []
    sec_calls = 0
    for index, raw_symbol in enumerate(symbols):
        symbol = str(raw_symbol or "").strip().upper()
        if not symbol:
            continue
        before_events = counted.event_writes
        before_evidence = counted.evidence_writes
        try:
            cik = resolve_signal_cik(
                symbol,
                cik_by_symbol=cik_by_symbol,
                candidate=(candidates_by_symbol or {}).get(symbol),
                sec_ticker_lookup=sec_ticker_lookup,
            )
            if not cik:
                raise ValueError("missing CIK")
            payload = (submissions_by_symbol or {}).get(symbol)
            if payload is None and submissions_loader is not None:
                payload = submissions_loader(cik)
                sec_calls += 1
            if payload is None:
                raise ValueError("missing SEC submissions")
            filings = discover_recent_8k_filings(
                payload,
                symbol=symbol,
                cik=cik,
                lookback_days=lookback_days,
                max_filings=max_filings_per_symbol,
                as_of=as_of,
            )
            ingested: list[IngestSignalResult] = []
            for filing in filings:
                for raw in raw_inputs_from_8k_filing(filing):
                    ingested.append(service.ingest(raw))
            results.append(
                SymbolIngestResult(
                    symbol=symbol,
                    cik=cik,
                    filings=len(filings),
                    events=len({item.event.event_id for item in ingested}),
                    evidence=len({item.evidence.evidence_id for item in ingested}),
                    event_writes=counted.event_writes - before_events,
                    evidence_writes=counted.evidence_writes - before_evidence,
                    ingest_results=tuple(ingested),
                    discovered=filings,
                )
            )
        except Exception as exc:
            results.append(
                SymbolIngestResult(
                    symbol=symbol,
                    cik=resolve_signal_cik(
                        symbol,
                        cik_by_symbol=cik_by_symbol,
                        candidate=(candidates_by_symbol or {}).get(symbol),
                        sec_ticker_lookup=sec_ticker_lookup,
                    ),
                    error=str(exc)[:240],
                    event_writes=counted.event_writes - before_events,
                    evidence_writes=counted.evidence_writes - before_evidence,
                )
            )
        if sleep_seconds and index + 1 < len(symbols):
            time.sleep(sleep_seconds)
    failed = tuple(item.symbol for item in results if item.error)
    return SecSignalIngestReport(
        lookback_days=lookback_days,
        max_filings_per_symbol=max_filings_per_symbol,
        symbols=tuple(str(item).strip().upper() for item in symbols if str(item).strip()),
        event_writes=counted.event_writes,
        evidence_writes=counted.evidence_writes,
        failed_symbols=failed,
        results=tuple(results),
        provider_calls_sec=sec_calls,
    )


def live_sec_submissions_loader(*, contact_email: str) -> SubmissionsLoader:
    """SEC submissions only. No FMP, news, or filing-HTML download."""
    from services.sec_financial_client import SECFinancialClient

    client = SECFinancialClient(contact_email=contact_email)

    def _load(cik: str) -> Mapping[str, Any]:
        return client.company_submissions(cik)

    return _load
