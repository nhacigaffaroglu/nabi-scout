from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from services.change_detection_engine import detect_changes, rank_changes
from services.scan_snapshot import build_scan_snapshot
from services.scanner_v8_engine import ScannerV8Engine

ProgressCallback = Callable[[int, int], None]

DEFAULT_PARTICIPATION = ("Kontrol Et", 60)
WRITE_BLOCKED_DECISIONS = {
    "ŞİMDİLİK UZAK DUR",
    "VERİ EKSİK — ÖN ELEME",
}


@dataclass
class ScanRunResult:
    run_id: str
    source: str
    universe_name: str
    total_symbols: int
    scanned: int
    updated: int
    strong: int
    errors: int
    excluded: int
    symbols_without_previous: int
    meaningful_changes: List[Dict[str, Any]] = field(default_factory=list)
    candidates: List[Dict[str, Any]] = field(default_factory=list)
    status: str = "COMPLETED"
    skipped: bool = False
    skip_reason: Optional[str] = None


def run_scan(
    *,
    symbols: List[Dict[str, Any]],
    universe_name: str,
    source: str = "manual",
    scan_repo,
    candidate_repo,
    fmp_client,
    sec_client,
    engine: Optional[ScannerV8Engine] = None,
    minimum_completeness: int = 65,
    minimum_conviction: int = 60,
    portfolio_fit: int = 55,
    participation_defaults: Optional[Dict[str, tuple[str, int]]] = None,
    progress_callback: Optional[ProgressCallback] = None,
) -> ScanRunResult:
    if not symbols:
        raise ValueError("At least one symbol is required to run a scan.")

    participation_defaults = participation_defaults or {}
    fmp_client.reset_scan_state()
    scanner = engine or ScannerV8Engine(fmp_client, sec_client)

    run_id = scan_repo.create_run(universe_name, len(symbols))
    full_candidates: List[Dict[str, Any]] = []
    scan_changes: List[Dict[str, Any]] = []
    symbols_without_previous = 0
    updated = strong = errors = excluded = 0
    successful_symbols = 0

    try:
        for index, row in enumerate(symbols, 1):
            symbol = row["symbol"]
            participation_status, participation_score = participation_defaults.get(
                symbol,
                DEFAULT_PARTICIPATION,
            )

            try:
                result = scanner.analyze(
                    symbol=symbol,
                    cik=row.get("cik"),
                    company_name=row.get("company_name"),
                    exchange=row.get("exchange"),
                    is_etf=row.get("is_etf", False),
                    participation_status=participation_status,
                    participation_score=participation_score,
                    portfolio_fit=portfolio_fit,
                )
            except Exception:
                errors += 1
                if progress_callback is not None:
                    progress_callback(index, len(symbols))
                continue

            successful_symbols += 1
            candidate = result["candidate"]

            should_write = (
                not result["excluded"]
                and candidate.get("data_completeness", 0) >= minimum_completeness
                and candidate.get("conviction_score", 0) >= minimum_conviction
                and candidate.get("decision_label") not in WRITE_BLOCKED_DECISIONS
            )

            if should_write:
                candidate_repo.upsert_by_symbol(candidate)
                updated += 1

            if result["excluded"]:
                excluded += 1
            if candidate.get("decision_label") == "YÜKSEK ÖNCELİKLİ ARAŞTIRMA ADAYI":
                strong += 1
            if result.get("errors"):
                errors += 1

            previous_snapshot = scan_repo.get_previous_snapshot(
                symbol,
                run_id,
                universe_name,
            )
            current_snapshot = build_scan_snapshot(result)
            change_result = detect_changes(previous_snapshot, current_snapshot)
            if previous_snapshot is None:
                symbols_without_previous += 1
            else:
                scan_changes.append({
                    "symbol": symbol,
                    "company_name": candidate.get("company_name") or symbol,
                    "change": change_result,
                })

            scan_repo.add_result(run_id, result)
            full_candidates.append(candidate)

            if progress_callback is not None:
                progress_callback(index, len(symbols))

        meaningful_changes = rank_changes([
            item
            for item in scan_changes
            if item["change"].get("has_meaningful_change")
        ])

        if successful_symbols == 0:
            scan_repo.fail_run(run_id, error_count=max(errors, len(symbols)))
            status = "FAILED"
        else:
            scan_repo.complete_run(
                run_id,
                len(symbols),
                updated,
                strong,
                errors,
            )
            status = "COMPLETED"

        return ScanRunResult(
            run_id=run_id,
            source=source,
            universe_name=universe_name,
            total_symbols=len(symbols),
            scanned=len(symbols),
            updated=updated,
            strong=strong,
            errors=errors,
            excluded=excluded,
            symbols_without_previous=symbols_without_previous,
            meaningful_changes=meaningful_changes,
            candidates=full_candidates,
            status=status,
        )
    except Exception:
        scan_repo.fail_run(run_id, error_count=max(errors, 1))
        raise
