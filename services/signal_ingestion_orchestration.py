"""Bounded Signal ingestion stage for existing daily orchestration.

SEC adapter is live. KAP adapter is credential-blocked and not called.
Does not write portfolio, Participation, candidates, or SI snapshots.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Mapping, Optional, Sequence

from services.signal_ingestion_policy import (
    ADAPTER_KAP,
    ADAPTER_SEC,
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_MAX_FILINGS_PER_SYMBOL,
    DEFAULT_MAX_SYMBOLS_PER_RUN,
    DEFAULT_SLEEP_SECONDS,
    STATUS_DEFERRED,
    STATUS_FAILED,
    STATUS_NO_NEW_EVENTS,
    STATUS_SKIPPED,
    STATUS_SUCCESS,
    classify_symbol_status,
    resolve_sec_signal_ingestion_enabled,
)
from services.signal_ingestion_universe import (
    SignalIngestionUniverse,
    apply_symbol_capacity,
    build_signal_ingestion_universe,
)
from services.signal_sec_ingest_service import run_sec_signal_ingestion


@dataclass(frozen=True)
class SymbolStageResult:
    symbol: str
    status: str
    cik: Optional[str] = None
    source: str = ""
    filings: int = 0
    events_normalized: int = 0
    event_writes: int = 0
    evidence_writes: int = 0
    sec_calls: int = 0
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "status": self.status,
            "cik": self.cik,
            "source": self.source,
            "filings": self.filings,
            "events_normalized": self.events_normalized,
            "event_writes": self.event_writes,
            "evidence_writes": self.evidence_writes,
            "sec_calls": self.sec_calls,
            "error": self.error,
        }


@dataclass(frozen=True)
class SignalIngestionStageReport:
    adapter: str
    enabled: bool
    run_started_at: str
    run_finished_at: str
    symbols_requested: tuple[str, ...]
    symbols_processed: tuple[str, ...]
    symbols_deferred: tuple[str, ...]
    symbols_success: int
    symbols_no_new_events: int
    symbols_failed: int
    symbols_skipped: int
    sec_submissions_calls: int
    filings_discovered: int
    events_normalized: int
    event_writes: int
    evidence_writes: int
    replay_skips: int
    lookback_days: int
    max_filings_per_symbol: int
    max_symbols_per_run: int
    per_symbol: tuple[SymbolStageResult, ...] = field(default_factory=tuple)
    holdings: tuple[str, ...] = ()
    candidates: tuple[str, ...] = ()
    excluded: tuple[tuple[str, str], ...] = ()
    message: str = ""
    schedule_activated: bool = False
    kap_attempted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter": self.adapter,
            "enabled": self.enabled,
            "run_started_at": self.run_started_at,
            "run_finished_at": self.run_finished_at,
            "symbols_requested": list(self.symbols_requested),
            "symbols_processed": list(self.symbols_processed),
            "symbols_deferred": list(self.symbols_deferred),
            "symbols_success": self.symbols_success,
            "symbols_no_new_events": self.symbols_no_new_events,
            "symbols_failed": self.symbols_failed,
            "symbols_skipped": self.symbols_skipped,
            "sec_submissions_calls": self.sec_submissions_calls,
            "filings_discovered": self.filings_discovered,
            "events_normalized": self.events_normalized,
            "event_writes": self.event_writes,
            "evidence_writes": self.evidence_writes,
            "replay_skips": self.replay_skips,
            "lookback_days": self.lookback_days,
            "max_filings_per_symbol": self.max_filings_per_symbol,
            "max_symbols_per_run": self.max_symbols_per_run,
            "holdings": list(self.holdings),
            "candidates": list(self.candidates),
            "excluded": [{"symbol": item[0], "reason": item[1]} for item in self.excluded],
            "per_symbol": [item.to_dict() for item in self.per_symbol],
            "message": self.message,
            "schedule_activated": self.schedule_activated,
            "kap_attempted": self.kap_attempted,
        }


def _empty_report(
    *,
    adapter: str,
    enabled: bool,
    started: str,
    universe: Optional[SignalIngestionUniverse] = None,
    requested: Sequence[str] = (),
    deferred: Sequence[str] = (),
    message: str,
    lookback_days: int,
    max_filings: int,
    max_symbols: int,
) -> SignalIngestionStageReport:
    return SignalIngestionStageReport(
        adapter=adapter,
        enabled=enabled,
        run_started_at=started,
        run_finished_at=datetime.now(timezone.utc).isoformat(),
        symbols_requested=tuple(requested),
        symbols_processed=(),
        symbols_deferred=tuple(deferred),
        symbols_success=0,
        symbols_no_new_events=0,
        symbols_failed=0,
        symbols_skipped=0,
        sec_submissions_calls=0,
        filings_discovered=0,
        events_normalized=0,
        event_writes=0,
        evidence_writes=0,
        replay_skips=0,
        lookback_days=lookback_days,
        max_filings_per_symbol=max_filings,
        max_symbols_per_run=max_symbols,
        holdings=universe.holdings if universe else (),
        candidates=universe.candidates if universe else (),
        excluded=universe.excluded if universe else (),
        message=message,
    )


def run_signal_ingestion_stage(
    *,
    holdings: Sequence[Mapping[str, Any]] = (),
    candidates: Sequence[Mapping[str, Any]] = (),
    participation_by_symbol: Optional[Mapping[str, Mapping[str, Any]]] = None,
    security_master_by_symbol: Optional[Mapping[str, Mapping[str, Any]]] = None,
    adapter: str = ADAPTER_SEC,
    enable_sec_signal_ingestion: Optional[bool] = None,
    repo=None,
    submissions_by_symbol: Optional[Mapping[str, Mapping[str, Any]]] = None,
    submissions_loader=None,
    cik_by_symbol: Optional[Mapping[str, str]] = None,
    sec_ticker_lookup: Optional[Mapping[str, Mapping[str, Any]]] = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    max_filings_per_symbol: int = DEFAULT_MAX_FILINGS_PER_SYMBOL,
    max_symbols_per_run: int = DEFAULT_MAX_SYMBOLS_PER_RUN,
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
    as_of: Optional[date] = None,
) -> SignalIngestionStageReport:
    started = datetime.now(timezone.utc).isoformat()
    enabled = resolve_sec_signal_ingestion_enabled(enable_sec_signal_ingestion)
    universe = build_signal_ingestion_universe(
        holdings=holdings,
        candidates=candidates,
        participation_by_symbol=participation_by_symbol,
        security_master_by_symbol=security_master_by_symbol,
    )
    processed, deferred = apply_symbol_capacity(
        universe.ordered_symbols,
        max_symbols_per_run=max_symbols_per_run,
    )
    source_by_symbol = {item.symbol: item.source for item in universe.members}
    cik_map = dict(cik_by_symbol or {})
    for item in universe.members:
        if item.cik and item.symbol not in cik_map:
            cik_map[item.symbol] = item.cik

    if not enabled:
        return _empty_report(
            adapter=adapter,
            enabled=False,
            started=started,
            universe=universe,
            requested=universe.ordered_symbols,
            deferred=(),
            message="enable_sec_signal_ingestion is OFF; stage skipped.",
            lookback_days=lookback_days,
            max_filings=max_filings_per_symbol,
            max_symbols=max_symbols_per_run,
        )
    if adapter == ADAPTER_KAP:
        return _empty_report(
            adapter=ADAPTER_KAP,
            enabled=enabled,
            started=started,
            universe=universe,
            requested=universe.ordered_symbols,
            deferred=(),
            message="KAP adapter is credential-blocked; no requests issued.",
            lookback_days=lookback_days,
            max_filings=max_filings_per_symbol,
            max_symbols=max_symbols_per_run,
        )
    if adapter != ADAPTER_SEC:
        return _empty_report(
            adapter=adapter,
            enabled=enabled,
            started=started,
            universe=universe,
            requested=universe.ordered_symbols,
            deferred=universe.ordered_symbols,
            message=f"Unknown signal adapter: {adapter}",
            lookback_days=lookback_days,
            max_filings=max_filings_per_symbol,
            max_symbols=max_symbols_per_run,
        )
    if not processed:
        return _empty_report(
            adapter=ADAPTER_SEC,
            enabled=True,
            started=started,
            universe=universe,
            requested=universe.ordered_symbols,
            deferred=deferred,
            message="No eligible US equity symbols.",
            lookback_days=lookback_days,
            max_filings=max_filings_per_symbol,
            max_symbols=max_symbols_per_run,
        )

    ingest = run_sec_signal_ingestion(
        processed,
        repo=repo,
        submissions_by_symbol=submissions_by_symbol,
        submissions_loader=submissions_loader,
        cik_by_symbol=cik_map,
        sec_ticker_lookup=sec_ticker_lookup,
        lookback_days=lookback_days,
        max_filings_per_symbol=max_filings_per_symbol,
        sleep_seconds=sleep_seconds,
        as_of=as_of,
    )
    per_symbol: list[SymbolStageResult] = []
    replay_skips = 0
    sec_calls_by_symbol: dict[str, int] = {}
    remaining_calls = ingest.provider_calls_sec
    for item in ingest.results:
        status = classify_symbol_status(
            error=item.error,
            event_writes=item.event_writes,
            evidence_writes=item.evidence_writes,
        )
        if status == STATUS_NO_NEW_EVENTS:
            replay_skips += 1
        calls = 0
        if remaining_calls and not item.error:
            calls = 1
            remaining_calls -= 1
        sec_calls_by_symbol[item.symbol] = calls
        per_symbol.append(
            SymbolStageResult(
                symbol=item.symbol,
                status=status,
                cik=item.cik,
                source=source_by_symbol.get(item.symbol, ""),
                filings=item.filings,
                events_normalized=item.events,
                event_writes=item.event_writes,
                evidence_writes=item.evidence_writes,
                sec_calls=calls,
                error=item.error,
            )
        )
    counts = {key: 0 for key in (STATUS_SUCCESS, STATUS_NO_NEW_EVENTS, STATUS_FAILED, STATUS_SKIPPED)}
    for item in per_symbol:
        counts[item.status] = counts.get(item.status, 0) + 1
    deferred_rows = tuple(
        SymbolStageResult(symbol=symbol, status=STATUS_DEFERRED, source=source_by_symbol.get(symbol, ""))
        for symbol in deferred
    )
    return SignalIngestionStageReport(
        adapter=ADAPTER_SEC,
        enabled=True,
        run_started_at=started,
        run_finished_at=datetime.now(timezone.utc).isoformat(),
        symbols_requested=universe.ordered_symbols,
        symbols_processed=processed,
        symbols_deferred=deferred,
        symbols_success=counts[STATUS_SUCCESS],
        symbols_no_new_events=counts[STATUS_NO_NEW_EVENTS],
        symbols_failed=counts[STATUS_FAILED],
        symbols_skipped=counts[STATUS_SKIPPED],
        sec_submissions_calls=ingest.provider_calls_sec,
        filings_discovered=sum(item.filings for item in ingest.results),
        events_normalized=sum(item.events for item in ingest.results),
        event_writes=ingest.event_writes,
        evidence_writes=ingest.evidence_writes,
        replay_skips=replay_skips,
        lookback_days=lookback_days,
        max_filings_per_symbol=max_filings_per_symbol,
        max_symbols_per_run=max_symbols_per_run,
        per_symbol=tuple(per_symbol) + deferred_rows,
        holdings=universe.holdings,
        candidates=universe.candidates,
        excluded=universe.excluded,
        message="SEC signal stage completed.",
    )
