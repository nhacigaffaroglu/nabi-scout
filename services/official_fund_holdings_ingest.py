"""Persist official issuer holdings into the canonical fund holdings store."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from repositories.fund_holdings_repository import FundHoldingsRepository
from services.fund_intelligence_contract import FundHoldingRow
from services.official_fund_holdings_client import (
    MATERIAL_WEIGHT_MAX_PCT,
    MATERIAL_WEIGHT_MIN_PCT,
    OfficialHoldingsError,
    OfficialHoldingsFile,
    SOURCE_SP_FUNDS_OFFICIAL,
)
from services.security_master_contract import (
    RESOLUTION_RESOLVED,
    SOURCE_PROVIDER_EXPLICIT,
    SOURCE_US_LISTING,
)
from services.security_master_service import (
    EXPLICIT_HOLDING_TO_INSTRUMENT,
    SecurityMasterService,
    summarize_holding_coverage,
)


WRITE_TABLES = frozenset({"fund_holdings", "fund_holdings_snapshots"})
READ_TABLES = frozenset(
    WRITE_TABLES
    | {
        "security_master",
        "universe_expansion_queue",
        "investment_candidates",
        "participation_assessment_snapshots",
        "wealth_portfolios",
        "wealth_adviser_goals",
        "wealth_transactions",
    }
)
_WRITE_METHODS = frozenset({"insert", "update", "upsert", "delete"})


class OfficialHoldingsWriteGuardError(RuntimeError):
    pass


class OfficialHoldingsWriteGuard:
    def __init__(self, client: Any) -> None:
        self._client = client

    def table(self, name: str):
        table_name = str(name or "").strip()
        if table_name not in READ_TABLES:
            raise OfficialHoldingsWriteGuardError(f"blocked table access: {table_name}")
        return _GuardedTable(self._client.table(table_name), table_name)

    def __getattr__(self, name: str):
        return getattr(self._client, name)


class _GuardedTable:
    def __init__(self, inner: Any, table_name: str) -> None:
        self._inner = inner
        self._table_name = table_name

    def __getattr__(self, name: str):
        if name in _WRITE_METHODS and self._table_name not in WRITE_TABLES:
            def _blocked(*args: Any, **kwargs: Any) -> Any:
                raise OfficialHoldingsWriteGuardError(
                    f"blocked write on {self._table_name}.{name}"
                )

            return _blocked
        return getattr(self._inner, name)


def holdings_fingerprint(rows: Sequence[dict[str, Any] | OfficialHoldingPersist]) -> tuple:
    items = []
    for row in rows:
        if isinstance(row, OfficialHoldingPersist):
            items.append((row.underlying_symbol, row.underlying_name, round(row.weight_pct, 4)))
        else:
            items.append(
                (
                    str(row.get("underlying_symbol") or ""),
                    str(row.get("underlying_name") or ""),
                    round(float(row.get("weight_pct") or 0.0), 4),
                )
            )
    return tuple(sorted(items))


@dataclass(frozen=True)
class OfficialHoldingPersist:
    underlying_symbol: str
    underlying_name: str
    weight_pct: float
    asset_type: Optional[str] = None


@dataclass
class OfficialIngestReport:
    fund_symbol: str
    http_status: int
    as_of: str
    source: str
    source_reference: str
    rows: int
    weight_sum: float
    identifier_coverage: float
    missing_identifiers: int
    duplicates: int
    parse_failures: int
    weight_valid: bool
    blocked_reason: str = ""
    snapshot_inserted: int = 0
    snapshot_unchanged: int = 0
    holdings_inserted: int = 0
    holdings_unchanged: int = 0
    content_changed: bool = False
    persisted: bool = False
    classification: dict[str, Any] = field(default_factory=dict)
    resolution: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fund_symbol": self.fund_symbol,
            "http_status": self.http_status,
            "as_of": self.as_of,
            "source": self.source,
            "source_reference": self.source_reference,
            "rows": self.rows,
            "weight_sum": self.weight_sum,
            "identifier_coverage": self.identifier_coverage,
            "missing_identifiers": self.missing_identifiers,
            "duplicates": self.duplicates,
            "parse_failures": self.parse_failures,
            "weight_valid": self.weight_valid,
            "blocked_reason": self.blocked_reason,
            "snapshot_inserted": self.snapshot_inserted,
            "snapshot_unchanged": self.snapshot_unchanged,
            "holdings_inserted": self.holdings_inserted,
            "holdings_unchanged": self.holdings_unchanged,
            "content_changed": self.content_changed,
            "persisted": self.persisted,
            "classification": self.classification,
            "resolution": self.resolution,
        }


def official_rows_to_persist(file: OfficialHoldingsFile) -> list[OfficialHoldingPersist]:
    rows = []
    for item in file.holdings:
        identifier = item.holding_identifier
        rows.append(
            OfficialHoldingPersist(
                underlying_symbol=identifier,
                underlying_name=item.security_name,
                weight_pct=float(item.weight_pct),
                asset_type=item.asset_type,
            )
        )
    return rows


def official_rows_to_holding_views(
    rows: Sequence[OfficialHoldingPersist],
) -> list[FundHoldingRow]:
    return [
        FundHoldingRow(
            underlying_symbol=row.underlying_symbol,
            underlying_name=row.underlying_name,
            weight_pct=row.weight_pct,
            asset_type=row.asset_type,
            participation_status=None,
            research_status=None,
        )
        for row in rows
    ]


def classify_official_holdings(
    rows: Sequence[OfficialHoldingPersist],
    *,
    security_master: Optional[SecurityMasterService] = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    master = security_master or SecurityMasterService()
    views = official_rows_to_holding_views(rows)
    summary = summarize_holding_coverage(views, security_master=master)
    explicit_w = sm_w = unknown_w = 0.0
    explicit_n = sm_n = unknown_n = 0
    sources: set[str] = set()
    for row in views:
        weight = float(row.weight_pct or 0.0)
        explicit = EXPLICIT_HOLDING_TO_INSTRUMENT.get(str(row.asset_type or "").strip().lower())
        if explicit is not None:
            explicit_n += 1
            explicit_w += weight
            sources.add(SOURCE_PROVIDER_EXPLICIT)
            continue
        resolution = master.resolve_security(row.underlying_symbol)
        if resolution.status == RESOLUTION_RESOLVED:
            sm_n += 1
            sm_w += weight
            if resolution.source:
                sources.add(resolution.source)
        else:
            unknown_n += 1
            unknown_w += weight
    classified = (
        summary["classified_EQUITY"]
        + summary["classified_REIT"]
        + summary["classified_SUKUK"]
        + summary["classified_FIXED_INCOME"]
        + summary["classified_CASH"]
        + summary["classified_OTHER"]
    )
    return summary, {
        "explicit_holding_fact_rows": explicit_n,
        "explicit_holding_fact_weight": round(explicit_w, 4),
        "security_master_rows": sm_n,
        "security_master_weight": round(sm_w, 4),
        "unresolved_rows": unknown_n,
        "unresolved_weight": round(unknown_w, 4),
        "classified_weight": round(classified, 4),
        "evidence_sources": tuple(sorted(sources)),
        "us_listing_used": SOURCE_US_LISTING in sources,
    }


def audit_official_file(
    file: OfficialHoldingsFile,
    *,
    security_master: Optional[SecurityMasterService] = None,
) -> OfficialIngestReport:
    rows = official_rows_to_persist(file)
    identifiers = [row.underlying_symbol for row in rows]
    missing = sum(1 for item in identifiers if not item)
    duplicates = len(identifiers) - len(set(identifiers))
    weight_sum = round(sum(row.weight_pct for row in rows), 4)
    weight_valid = MATERIAL_WEIGHT_MIN_PCT <= weight_sum <= MATERIAL_WEIGHT_MAX_PCT
    classification, resolution = classify_official_holdings(rows, security_master=security_master)
    blocked = ""
    if not weight_valid:
        blocked = f"raw weight sum {weight_sum} outside {MATERIAL_WEIGHT_MIN_PCT}-{MATERIAL_WEIGHT_MAX_PCT}"
    return OfficialIngestReport(
        fund_symbol=file.fund_symbol,
        http_status=file.http_status,
        as_of=file.as_of.isoformat(),
        source=file.source,
        source_reference=file.source_reference,
        rows=len(rows),
        weight_sum=weight_sum,
        identifier_coverage=round((len(rows) - missing) / len(rows) * 100.0, 4) if rows else 0.0,
        missing_identifiers=missing,
        duplicates=duplicates,
        parse_failures=file.parse_failures,
        weight_valid=weight_valid,
        blocked_reason=blocked,
        classification=classification,
        resolution=resolution,
    )


class OfficialFundHoldingsIngestService:
    SOURCE = SOURCE_SP_FUNDS_OFFICIAL

    def __init__(self, repo: FundHoldingsRepository) -> None:
        self.repo = repo

    def persist(
        self,
        file: OfficialHoldingsFile,
        *,
        security_master: Optional[SecurityMasterService] = None,
        allow_content_change: bool = False,
    ) -> OfficialIngestReport:
        report = audit_official_file(file, security_master=security_master)
        if report.blocked_reason:
            raise OfficialHoldingsError(report.blocked_reason)
        rows = official_rows_to_persist(file)
        existing = self.repo.get_snapshot_for_date(
            fund_symbol=file.fund_symbol,
            as_of=file.as_of,
            source=self.SOURCE,
        )
        payload = [
            {
                "underlying_symbol": row.underlying_symbol,
                "underlying_name": row.underlying_name,
                "weight_pct": row.weight_pct,
                "asset_type": row.asset_type,
                "participation_status": None,
                "research_status": None,
            }
            for row in rows
        ]
        if existing is not None:
            current = self.repo.list_holdings(str(existing["id"]))
            if holdings_fingerprint(current) == holdings_fingerprint(payload):
                report.snapshot_unchanged = 1
                report.holdings_unchanged = len(payload)
                report.persisted = True
                return report
            if not allow_content_change:
                report.content_changed = True
                report.blocked_reason = "same as_of content changed; not overwritten"
                return report
            report.content_changed = True
            snap = self.repo.upsert_snapshot(
                fund_symbol=file.fund_symbol,
                fund_type="etf",
                as_of=file.as_of,
                source=self.SOURCE,
                coverage_pct=min(report.weight_sum, 100.0),
                underlying_count=len(payload),
            )
            for row in payload:
                row["snapshot_id"] = snap["id"]
            inserted = self.repo.replace_holdings(str(snap["id"]), payload)
            report.holdings_inserted = inserted
            report.persisted = True
            return report
        snap = self.repo.upsert_snapshot(
            fund_symbol=file.fund_symbol,
            fund_type="etf",
            as_of=file.as_of,
            source=self.SOURCE,
            coverage_pct=min(report.weight_sum, 100.0),
            underlying_count=len(payload),
        )
        for row in payload:
            row["snapshot_id"] = snap["id"]
        inserted = self.repo.replace_holdings(str(snap["id"]), payload)
        report.snapshot_inserted = 1
        report.holdings_inserted = inserted
        report.persisted = True
        return report
