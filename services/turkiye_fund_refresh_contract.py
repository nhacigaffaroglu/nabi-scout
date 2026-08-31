"""Turkish fund snapshot refresh vocabulary.

Reuses BIST refresh status/reason constants. Does not write.
COMPUTE, PUBLISH DECISION, and PERSIST stay separate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from services.bist_refresh_contract import (
    REASON_DRY_RUN,
    REASON_LIVE_UNSAFE,
    REASON_NO_CHANGE,
    REASON_PERSIST_DISABLED,
    REASON_PILOT_SCOPE,
    STATUS_BLOCKED,
    STATUS_NO_CHANGE,
    STATUS_SKIPPED,
    STATUS_SOURCE_FAILURE,
    STATUS_WOULD_PUBLISH,
)
from services.fund_product_contract import PILOT_TEFAS_FUND_CODES

JOB_NAME = "turkiye_fund_canonical_refresh"
LAYER_IDENTITY = "identity"
LAYER_PARTICIPATION = "participation"
LAYER_FUND_INTELLIGENCE = "fund_intelligence"
LAYER_ECONOMIC_EXPOSURE = "economic_exposure"
LAYER_EIGHT_E = "eight_e"
SNAPSHOT_LAYERS = (
    LAYER_IDENTITY,
    LAYER_PARTICIPATION,
    LAYER_FUND_INTELLIGENCE,
    LAYER_ECONOMIC_EXPOSURE,
    LAYER_EIGHT_E,
)

CHANGE_TEFAS_PRICE = "TEFAS_PRICE_CHANGED"
CHANGE_PDR = "PDR_CHANGED"
CHANGE_PARTICIPATION = "PARTICIPATION_CHANGED"
CHANGE_FUND_INTELLIGENCE = "FUND_INTELLIGENCE_CHANGED"
CHANGE_ECONOMIC_EXPOSURE = "ECONOMIC_EXPOSURE_CHANGED"
CHANGE_EIGHT_E = "EIGHT_E_CHANGED"

TABLE_SI_SNAPSHOTS = "security_intelligence_snapshots"
TABLE_PARTICIPATION_SNAPSHOTS = "participation_assessment_snapshots"
STATE_CACHE_PATH = ".cache/turkiye_fund_refresh/state.json"

OUTCOME_PUBLISHED = "PUBLISHED"
OUTCOME_NO_CHANGE = STATUS_NO_CHANGE
OUTCOME_SKIPPED = STATUS_SKIPPED
OUTCOME_BLOCKED = STATUS_BLOCKED
OUTCOME_ERROR = "ERROR"
OUTCOME_WOULD_PUBLISH = STATUS_WOULD_PUBLISH
STATUS_PUBLISHED = OUTCOME_PUBLISHED
REASON_PARTICIPATION_WRITE_FAILED = "PARTICIPATION_WRITE_FAILED"
REASON_FORBIDDEN_LAYER = "FORBIDDEN_LAYER_PERSIST"
REASON_INVALID_PAYLOAD = "INVALID_SNAPSHOT_PAYLOAD"


@dataclass(frozen=True)
class TurkiyeFundLayerCounts:
    processed: int = 0
    published: int = 0
    would_publish: int = 0
    no_change: int = 0
    blocked: int = 0
    errors: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "processed": self.processed,
            "published": self.published,
            "would_publish": self.would_publish,
            "no_change": self.no_change,
            "blocked": self.blocked,
            "errors": self.errors,
        }


@dataclass(frozen=True)
class TurkiyeFundRefreshState:
    """Idempotency cursors. Keys, not timestamps."""

    layer_keys: tuple[tuple[str, str, str], ...] = ()
    tefas_price_dates: tuple[tuple[str, str], ...] = ()
    pdr_periods: tuple[tuple[str, str], ...] = ()

    def layer_key(self, fund_code: str, layer: str) -> str:
        return dict(((row[0], row[1]), row[2]) for row in self.layer_keys).get((fund_code, layer), "")

    def tefas_price_date(self, fund_code: str) -> str:
        return dict(self.tefas_price_dates).get(fund_code, "")

    def pdr_period(self, fund_code: str) -> str:
        return dict(self.pdr_periods).get(fund_code, "")

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer_keys": [list(item) for item in self.layer_keys],
            "tefas_price_dates": [list(item) for item in self.tefas_price_dates],
            "pdr_periods": [list(item) for item in self.pdr_periods],
        }

    @classmethod
    def from_dict(cls, payload: Optional[dict[str, Any]]) -> "TurkiyeFundRefreshState":
        if not payload:
            return cls()
        triples = tuple(
            (str(item[0]), str(item[1]), str(item[2]))
            for item in (payload.get("layer_keys") or ())
            if item
        )
        pairs = lambda key: tuple(
            (str(item[0]), str(item[1])) for item in (payload.get(key) or ()) if item
        )
        return cls(
            layer_keys=triples,
            tefas_price_dates=pairs("tefas_price_dates"),
            pdr_periods=pairs("pdr_periods"),
        )


@dataclass(frozen=True)
class TurkiyeFundLayerResult:
    fund_code: str
    layer: str
    status: str
    would_publish: bool = False
    published: bool = False
    publishable: bool = False
    idempotency_key: str = ""
    reason: str = ""
    error: str = ""
    changes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "fund_code": self.fund_code,
            "layer": self.layer,
            "status": self.status,
            "would_publish": self.would_publish,
            "published": self.published,
            "publishable": self.publishable,
            "idempotency_key": self.idempotency_key,
            "reason": self.reason,
            "error": self.error,
            "changes": list(self.changes),
        }


@dataclass(frozen=True)
class TurkiyeFundSymbolRefresh:
    fund_code: str
    changes: tuple[str, ...] = ()
    layers: tuple[TurkiyeFundLayerResult, ...] = ()
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "fund_code": self.fund_code,
            "changes": list(self.changes),
            "layers": [row.to_dict() for row in self.layers],
            "error": self.error,
        }


@dataclass(frozen=True)
class TurkiyeFundRefreshRun:
    run_id: str
    job_name: str = JOB_NAME
    started_at: str = ""
    finished_at: str = ""
    status: str = ""
    dry_run: bool = True
    persist_fund_intelligence: bool = False
    persist_participation: bool = False
    persist_economic_exposure: bool = False
    persist_decisions: bool = False
    allow_live: bool = False
    cli_live: bool = False
    symbols: tuple[str, ...] = PILOT_TEFAS_FUND_CODES
    changes_detected: int = 0
    processed: int = 0
    published: int = 0
    would_publish: int = 0
    no_change: int = 0
    blocked: int = 0
    errors: tuple[str, ...] = ()
    writes: int = 0
    participation: TurkiyeFundLayerCounts = field(default_factory=TurkiyeFundLayerCounts)
    fund_intelligence: TurkiyeFundLayerCounts = field(default_factory=TurkiyeFundLayerCounts)
    funds: tuple[TurkiyeFundSymbolRefresh, ...] = ()
    next_state: TurkiyeFundRefreshState = field(default_factory=TurkiyeFundRefreshState)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "job_name": self.job_name,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "dry_run": self.dry_run,
            "persist_fund_intelligence": self.persist_fund_intelligence,
            "persist_participation": self.persist_participation,
            "persist_economic_exposure": self.persist_economic_exposure,
            "persist_decisions": self.persist_decisions,
            "allow_live": self.allow_live,
            "cli_live": self.cli_live,
            "symbols": list(self.symbols),
            "fund_codes": list(self.symbols),
            "changes_detected": self.changes_detected,
            "processed": self.processed,
            "published": self.published,
            "would_publish": self.would_publish,
            "no_change": self.no_change,
            "blocked": self.blocked,
            "errors": list(self.errors),
            "writes": self.writes,
            "participation": self.participation.to_dict(),
            "fund_intelligence": self.fund_intelligence.to_dict(),
            "funds": [row.to_dict() for row in self.funds],
        }
