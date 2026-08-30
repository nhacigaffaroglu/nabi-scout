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
REASON_PERSIST_PARTICIPATION_DISABLED = "PERSIST_PARTICIPATION_DISABLED"
REASON_FIXTURE_MOMENTUM = "FIXTURE_MOMENTUM_FORBIDDEN"
REASON_US_ISOLATED = "US_SYMBOL_ISOLATED"
REASON_BROAD_UNIVERSE = "BROAD_UNIVERSE_REFUSED"
REASON_PILOT_SCOPE = "PILOT_SCOPE_REFUSED"
REASON_LIVE_UNSAFE = "LIVE_PERSIST_UNSAFE"

PILOT_SYMBOLS = ("ASELS", "BIMAS", "TUPRS")
STATE_CACHE_PATH = ".cache/bist_refresh/state.json"

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
    membership_keys: Tuple[Tuple[str, str], ...] = ()
    capital_versions: Tuple[Tuple[str, str], ...] = ()

    def known_ids(self) -> set[str]:
        return set(self.known_notification_ids)

    def kafif_id(self, symbol: str) -> str:
        return dict(self.latest_kafif_ids).get(symbol, "")

    def kafif_submitted(self, symbol: str) -> str:
        return dict(self.latest_kafif_submitted).get(symbol, "")

    def participation_key(self, symbol: str) -> str:
        return dict(self.participation_keys).get(symbol, "")

    def membership_key(self, symbol: str) -> str:
        return dict(self.membership_keys).get(symbol, "")

    def capital_version(self, symbol: str) -> str:
        return dict(self.capital_versions).get(symbol, "")

    def to_dict(self) -> dict[str, Any]:
        return {
            "known_notification_ids": list(self.known_notification_ids),
            "latest_kafif_ids": [list(item) for item in self.latest_kafif_ids],
            "latest_kafif_submitted": [list(item) for item in self.latest_kafif_submitted],
            "latest_thb_date": self.latest_thb_date,
            "participation_keys": [list(item) for item in self.participation_keys],
            "membership_keys": [list(item) for item in self.membership_keys],
            "capital_versions": [list(item) for item in self.capital_versions],
        }

    @classmethod
    def from_dict(cls, payload: Optional[dict[str, Any]]) -> "BistRefreshState":
        if not payload:
            return cls()
        pairs = lambda key: tuple(
            (str(item[0]), str(item[1]))
            for item in (payload.get(key) or ())
            if item
        )
        return cls(
            known_notification_ids=tuple(str(item) for item in payload.get("known_notification_ids") or ()),
            latest_kafif_ids=pairs("latest_kafif_ids"),
            latest_kafif_submitted=pairs("latest_kafif_submitted"),
            latest_thb_date=payload.get("latest_thb_date"),
            participation_keys=pairs("participation_keys"),
            membership_keys=pairs("membership_keys"),
            capital_versions=pairs("capital_versions"),
        )


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
    participation_published: bool = False
    participation_skipped: bool = False
    previous_participation_state: str = ""
    new_participation_state: str = ""
    research_allowed: Optional[bool] = None
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
            "participation_published": self.participation_published,
            "participation_skipped": self.participation_skipped,
            "previous_participation_state": self.previous_participation_state,
            "new_participation_state": self.new_participation_state,
            "research_allowed": self.research_allowed,
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
    persist_participation: bool = False
    allow_live: bool = False
    symbols_checked: int = 0
    changes_detected: int = 0
    symbols_processed: int = 0
    snapshots_published: int = 0
    rows_skipped: int = 0
    writes: int = 0
    errors: Tuple[str, ...] = ()
    participation_changes_detected: int = 0
    participation_processed: int = 0
    participation_published: int = 0
    participation_skipped: int = 0
    participation_errors: Tuple[str, ...] = ()
    si_processed: int = 0
    si_published: int = 0
    si_skipped: int = 0
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
            "persist_participation": self.persist_participation,
            "allow_live": self.allow_live,
            "symbols_checked": self.symbols_checked,
            "changes_detected": self.changes_detected,
            "symbols_processed": self.symbols_processed,
            "snapshots_published": self.snapshots_published,
            "rows_skipped": self.rows_skipped,
            "writes": self.writes,
            "errors": list(self.errors),
            "participation_changes_detected": self.participation_changes_detected,
            "participation_processed": self.participation_processed,
            "participation_published": self.participation_published,
            "participation_skipped": self.participation_skipped,
            "participation_errors": list(self.participation_errors),
            "si_processed": self.si_processed,
            "si_published": self.si_published,
            "si_skipped": self.si_skipped,
            "latest_thb_date": self.latest_thb_date,
            "missing_thb_dates": list(self.missing_thb_dates),
            "securities": [row.to_dict() for row in self.securities],
        }
