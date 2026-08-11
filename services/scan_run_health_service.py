from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

_EXCLUDED_STATUSES = frozenset({"ELENDİ", "ELENDI"})
_EXCLUDED_DECISIONS = frozenset({"ELE", "ELENDİ", "ELENDI"})
_NON_OK_ENDPOINT_STATUSES = frozenset({
    "RATE_LIMIT",
    "PLAN_RESTRICTED",
    "AUTH_ERROR",
    "TIMEOUT",
    "NETWORK_ERROR",
    "NOT_FOUND",
    "SERVER_ERROR",
    "MALFORMED",
    "EMPTY",
    "ERİŞİLEMEDİ",
    "ERISILEMEDI",
    "CIK YOK",
})


@dataclass(frozen=True)
class ScanRunHealth:
    total_symbols: int
    analyzed_symbols: int
    usable_symbols: int
    warning_symbols: int
    hard_failures: int
    excluded_symbols: int
    clean_symbols: int
    endpoint_warning_count: int
    has_warnings: bool
    has_hard_failures: bool
    fmp_rate_limited: bool
    legacy_error_count: Optional[int] = None

    @property
    def scheduled_health(self) -> str:
        if self.usable_symbols == 0 and (
            self.has_hard_failures or self.analyzed_symbols == 0
        ):
            return "failed"
        if self.has_warnings or self.has_hard_failures:
            return "partial"
        if self.usable_symbols > 0:
            return "success"
        return "failed"


def _normalize_errors(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (list, tuple)):
        messages: List[str] = []
        for item in value:
            if item is None:
                continue
            text = str(item).strip()
            if text:
                messages.append(text)
        return messages
    if isinstance(value, dict):
        text = str(value.get("message") or value.get("error") or "").strip()
        return [text] if text else []
    text = str(value).strip()
    return [text] if text else []


def _snapshot_from_row(row: Dict[str, Any]) -> Dict[str, Any]:
    snapshot = row.get("candidate_snapshot")
    if isinstance(snapshot, dict):
        return snapshot
    return {}


def is_excluded_result_row(row: Dict[str, Any]) -> bool:
    status = str(row.get("status") or "").strip().upper()
    if status in _EXCLUDED_STATUSES:
        return True

    decision = str(row.get("decision") or "").strip().upper()
    if decision in _EXCLUDED_DECISIONS:
        return True

    snapshot = _snapshot_from_row(row)
    if snapshot.get("excluded"):
        return True

    for key in ("decision", "decision_label", "investment_profile", "status"):
        value = str(snapshot.get(key) or "").strip().upper()
        if value in _EXCLUDED_DECISIONS or value in _EXCLUDED_STATUSES:
            return True

    issuer_category = str(snapshot.get("issuer_category") or "").strip().upper()
    if issuer_category in {"FUND", "SPECIAL_SECURITY"}:
        return True

    return False


def count_endpoint_warnings(endpoint_status: Any) -> int:
    if not isinstance(endpoint_status, dict):
        return 0

    warnings = 0
    for value in endpoint_status.values():
        status = str(value or "").strip().upper()
        if status and status != "OK":
            warnings += 1
    return warnings


def endpoint_status_has_rate_limit(endpoint_status: Any) -> bool:
    if not isinstance(endpoint_status, dict):
        return False
    return any(
        str(value or "").strip().upper() == "RATE_LIMIT"
        for value in endpoint_status.values()
    )


def classify_result_row(row: Dict[str, Any]) -> str:
    if is_excluded_result_row(row):
        return "excluded"
    if _normalize_errors(row.get("errors")):
        return "warning"
    return "clean"


def derive_scan_run_health(
    run: Optional[Dict[str, Any]],
    results: Sequence[Dict[str, Any]],
) -> ScanRunHealth:
    total_symbols = int((run or {}).get("total_symbols") or 0)
    if total_symbols <= 0 and results:
        total_symbols = len(results)

    analyzed_symbols = len(results)
    hard_failures = max(total_symbols - analyzed_symbols, 0)

    excluded_symbols = 0
    warning_symbols = 0
    clean_symbols = 0
    endpoint_warning_count = 0
    fmp_rate_limited = False

    for row in results:
        endpoint_warning_count += count_endpoint_warnings(row.get("endpoint_status"))
        if endpoint_status_has_rate_limit(row.get("endpoint_status")):
            fmp_rate_limited = True

        category = classify_result_row(row)
        if category == "excluded":
            excluded_symbols += 1
        elif category == "warning":
            warning_symbols += 1
        else:
            clean_symbols += 1

    usable_symbols = warning_symbols + clean_symbols
    legacy_error_count = None
    if run is not None and run.get("error_count") is not None:
        legacy_error_count = int(run.get("error_count") or 0)

    return ScanRunHealth(
        total_symbols=total_symbols,
        analyzed_symbols=analyzed_symbols,
        usable_symbols=usable_symbols,
        warning_symbols=warning_symbols,
        hard_failures=hard_failures,
        excluded_symbols=excluded_symbols,
        clean_symbols=clean_symbols,
        endpoint_warning_count=endpoint_warning_count,
        has_warnings=warning_symbols > 0,
        has_hard_failures=hard_failures > 0,
        fmp_rate_limited=fmp_rate_limited,
        legacy_error_count=legacy_error_count,
    )


def resolve_scheduled_health(
    run: Optional[Dict[str, Any]],
    health: Optional[ScanRunHealth] = None,
) -> str:
    if not run:
        return "missing"

    db_status = str(run.get("status") or "").upper()
    if db_status == "FAILED":
        return "failed"
    if db_status == "RUNNING":
        return "partial"
    if db_status != "COMPLETED":
        return "missing"

    if health is None:
        error_count = int(run.get("error_count") or 0)
        return "success" if error_count == 0 else "partial"

    if health.usable_symbols == 0:
        return "failed"
    return health.scheduled_health


def build_in_memory_scan_run_health(result) -> ScanRunHealth:
    return ScanRunHealth(
        total_symbols=result.total_symbols,
        analyzed_symbols=result.total_symbols - result.hard_failures,
        usable_symbols=result.usable_symbols,
        warning_symbols=result.warning_symbols,
        hard_failures=result.hard_failures,
        excluded_symbols=result.excluded,
        clean_symbols=result.clean_symbols,
        endpoint_warning_count=result.endpoint_warning_count,
        has_warnings=result.warning_symbols > 0,
        has_hard_failures=result.hard_failures > 0,
        fmp_rate_limited=result.fmp_rate_limited,
        legacy_error_count=result.errors,
    )
