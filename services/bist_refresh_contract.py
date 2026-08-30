"""Change-driven BIST refresh vocabulary. No scoring. No writes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Tuple


JOB_NAME = "bist_canonical_refresh"
MAX_SYMBOLS_DEFAULT = 8

CHANGE_FINANCIAL_FACTS = "FINANCIAL_FACTS_CHANGED"
CHANGE_PARTICIPATION = "PARTICIPATION_CHANGED"
CHANGE_CAPITAL = "CAPITAL_STRUCTURE_CHANGED"
CHANGE_PRICE_HISTORY = "PRICE_HISTORY_CHANGED"
CHANGE_CORPORATE_ACTION = "CORPORATE_ACTION_CHANGED"

STATUS_NO_CHANGE = "NO_CHANGE"
STATUS_NEW_PERIOD = "NEW_PERIOD"
STATUS_RESTATEMENT = "RESTATEMENT"
STATUS_CORRECTION = "CORRECTION"
STATUS_SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
STATUS_SOURCE_FAILURE = "SOURCE_FAILURE"
STATUS_CHECKED = "CHECKED"
STATUS_SKIPPED = "SKIPPED"
STATUS_UNRESOLVED_CA = "UNRESOLVED_CA"
STATUS_WOULD_PUBLISH = "WOULD_PUBLISH"
STATUS_BLOCKED = "BLOCKED"
STATUS_US_ISOLATED = "US_ISOLATED"

REASON_NO_CHANGE = "NO_CHANGE"
REASON_DRY_RUN = "DRY_RUN_NO_WRITE"
REASON_SOURCE_FAILURE_PRESERVE = "SOURCE_FAILURE_PRESERVE_PREVIOUS_SI"
REASON_UNRESOLVED_CA = "UNRESOLVED_CORPORATE_ACTION_FAIL_CLOSED"
REASON_QUALITY_GATE = "PRODUCTION_QUALITY_GATE"
REASON_PERSIST_DISABLED = "PERSIST_SI_DISABLED"
REASON_FIXTURE_MOMENTUM = "FIXTURE_MOMENTUM_FORBIDDEN"
REASON_US_ISOLATED = "US_SYMBOL_ISOLATED"
REASON_BROAD_UNIVERSE = "BROAD_UNIVERSE_REFUSED"

PAID_PROVIDER_TOKENS = (
    "FMPClient",
    "fmp_client",
    "Musaffa",
    "Zoya",
    "KAP Veri Yayın",
    "paid KAP",
)


@dataclass(frozen=True)
class BistRefreshState:
    """Incremental cursor. Notification IDs, not symbol+year+period alone."""

    known_notification_ids: Tuple[str, ...] = ()
    latest_kafif_ids: Tuple[Tuple[str, str], ...] = ()
    latest_kafif_submitted: Tuple[Tuple[str, str], ...] = ()
    latest_thb_date: Optional[str] = None
    participation_keys: Tuple[Tuple[str, str], ...] = ()
    capital_versions: Tuple[Tuple[str, str], ...] = ()

    def known_ids(self) -> set[str]:
        return set(self.known_notification_ids)

    def kafif_id(self, symbol: str) -> str:
        return dict(self.latest_kafif_ids).get(symbol, "")

    def kafif_submitted(self, symbol: str) -> str:
        return dict(self.latest_kafif_submitted).get(symbol, "")

    def participation_key(self, symbol: str) -> str:
        return dict(self.participation_keys).get(symbol, "")

    def capital_version(self, symbol: str) -> str:
        return dict(self.capital_versions).get(symbol, "")


@dataclass(frozen=True)
class BistSymbolRefresh:
    symbol: str
    changes: Tuple[str, ...] = ()
    kap_status: str = STATUS_CHECKED
    kafif_status: str = STATUS_CHECKED
    capital_status: str = STATUS_CHECKED
    thb_status: str = STATUS_CHECKED
    ca_status: str = STATUS_CHECKED
    facts_status: str = STATUS_SKIPPED
    si_status: str = STATUS_SKIPPED
    latest_notification_ids: Tuple[str, ...] = ()
    latest_kafif_id: str = ""
    latest_thb_date: Optional[str] = None
    si_score: Optional[float] = None
    si_state: Optional[str] = None
    would_publish: bool = False
    published: bool = False
    reason: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "changes": list(self.changes),
            "kap_status": self.kap_status,
            "kafif_status": self.kafif_status,
            "capital_status": self.capital_status,
            "thb_status": self.thb_status,
            "ca_status": self.ca_status,
            "facts_status": self.facts_status,
            "si_status": self.si_status,
            "latest_notification_ids": list(self.latest_notification_ids),
            "latest_kafif_id": self.latest_kafif_id,
            "latest_thb_date": self.latest_thb_date,
            "si_score": self.si_score,
            "si_state": self.si_state,
            "would_publish": self.would_publish,
            "published": self.published,
            "reason": self.reason,
            "error": self.error,
        }


@dataclass(frozen=True)
class BistRefreshRun:
    run_id: str
    job_name: str = JOB_NAME
    started_at: str = ""
    finished_at: str = ""
    status: str = ""
    dry_run: bool = True
    persist_si: bool = False
    allow_live: bool = False
    symbols_checked: int = 0
    changes_detected: int = 0
    symbols_processed: int = 0
    snapshots_published: int = 0
    rows_skipped: int = 0
    writes: int = 0
    errors: Tuple[str, ...] = ()
    latest_thb_date: Optional[str] = None
    missing_thb_dates: Tuple[str, ...] = ()
    securities: Tuple[BistSymbolRefresh, ...] = ()
    next_state: BistRefreshState = field(default_factory=BistRefreshState)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "job_name": self.job_name,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "dry_run": self.dry_run,
            "persist_si": self.persist_si,
            "allow_live": self.allow_live,
            "symbols_checked": self.symbols_checked,
            "changes_detected": self.changes_detected,
            "symbols_processed": self.symbols_processed,
            "snapshots_published": self.snapshots_published,
            "rows_skipped": self.rows_skipped,
            "writes": self.writes,
            "errors": list(self.errors),
            "latest_thb_date": self.latest_thb_date,
            "missing_thb_dates": list(self.missing_thb_dates),
            "securities": [row.to_dict() for row in self.securities],
        }
