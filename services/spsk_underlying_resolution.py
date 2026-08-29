"""SPSK underlying identifier resolution. Evidence only. No fund inference.

Does not classify SPSK itself. Does not write. Dry-run rows stay UNKNOWN
unless Security Master already has a compatible explicit fact.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from services.official_fund_holdings_client import OfficialHolding
from services.security_identifier_match import (
    IdentifierMatch,
    first_exact_match,
    match_official_holding,
)
from services.security_identifier_validation import (
    IdentifierAssessment,
    assess_identifier,
)
from services.security_master_contract import (
    INSTRUMENT_TO_POLICY_ASSET_TYPE,
    INSTRUMENT_UNKNOWN,
    RESOLUTION_RESOLVED,
)
from services.security_master_service import SecurityMasterService
from services.sukuk_evidence_contract import (
    classify_from_name_or_fund,
    explicit_instrument_from_structured_type,
)

WRITE_NONE = "NONE"
WRITE_INSERT = "INSERT"
WRITE_SKIP_NO_EVIDENCE = "SKIP_NO_EXPLICIT_EVIDENCE"
WRITE_SKIP_CONFLICT = "SKIP_CONFLICT"


@dataclass(frozen=True)
class SpskHoldingResolution:
    date: str
    stock_ticker: str
    cusip_raw: str
    security_name: str
    weight_pct: float
    ticker_assessment: IdentifierAssessment
    cusip_assessment: IdentifierAssessment
    ticker_match: IdentifierMatch
    cusip_match: IdentifierMatch
    resolved_identifier: Optional[str]
    identifier_type: Optional[str]
    evidence_source: Optional[str]
    instrument_type: str
    economic_layer: Optional[str]
    write_action: str
    limitation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "stock_ticker": self.stock_ticker,
            "cusip_raw": self.cusip_raw,
            "security_name": self.security_name,
            "weight_pct": self.weight_pct,
            "ticker_assessment": self.ticker_assessment.to_dict(),
            "cusip_assessment": self.cusip_assessment.to_dict(),
            "resolved_identifier": self.resolved_identifier,
            "identifier_type": self.identifier_type,
            "evidence_source": self.evidence_source,
            "instrument_type": self.instrument_type,
            "economic_layer": self.economic_layer,
            "write_action": self.write_action,
            "limitation": self.limitation,
        }


@dataclass
class SpskDryRunReport:
    rows: list[SpskHoldingResolution] = field(default_factory=list)
    identifier_usability: dict[str, int] = field(default_factory=dict)
    identifier_weight: dict[str, float] = field(default_factory=dict)
    match_status: dict[str, int] = field(default_factory=dict)
    instrument_weight: dict[str, float] = field(default_factory=dict)
    matched_weight: float = 0.0
    unmatched_weight: float = 0.0
    conflict_weight: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_count": len(self.rows),
            "identifier_usability": dict(self.identifier_usability),
            "identifier_weight": {key: round(val, 4) for key, val in self.identifier_weight.items()},
            "match_status": dict(self.match_status),
            "instrument_weight": {key: round(val, 4) for key, val in self.instrument_weight.items()},
            "matched_weight": round(self.matched_weight, 4),
            "unmatched_weight": round(self.unmatched_weight, 4),
            "conflict_weight": round(self.conflict_weight, 4),
            "rows": [row.to_dict() for row in self.rows],
        }


def _best_usability(ticker: IdentifierAssessment, cusip: IdentifierAssessment) -> IdentifierAssessment:
    rank = {
        "VALID_ISIN": 0,
        "VALID_CUSIP": 1,
        "VALID_SEDOL": 2,
        "LISTING_TICKER": 3,
        "UNVERIFIED_IDENTIFIER": 4,
        "MISSING": 5,
    }
    if rank.get(cusip.usability, 9) <= rank.get(ticker.usability, 9):
        return cusip
    return ticker


def resolve_official_holding(
    holding: OfficialHolding,
    *,
    security_master: SecurityMasterService,
) -> SpskHoldingResolution:
    # Name and SPSK membership are never classification inputs.
    _ = classify_from_name_or_fund(holding.security_name, holding.fund_symbol)
    structured = explicit_instrument_from_structured_type(holding.asset_type)
    ticker_match, cusip_match = match_official_holding(
        ticker=holding.ticker,
        cusip_raw=holding.cusip_raw,
        security_master=security_master,
    )
    ticker_assessment = assess_identifier(holding.ticker)
    cusip_assessment = assess_identifier(holding.cusip_raw)
    exact = first_exact_match((ticker_match, cusip_match))
    conflicts = [row for row in (ticker_match, cusip_match) if row.status == "CONFLICT"]
    exacts = [row for row in (ticker_match, cusip_match) if row.status == "EXACT"]
    exact_types = {
        row.resolution.instrument_type
        for row in exacts
        if row.resolution is not None
    }

    instrument = INSTRUMENT_UNKNOWN
    source = None
    ident = None
    itype = None
    layer = None
    write = WRITE_SKIP_NO_EVIDENCE
    limitation = "NO_EXPLICIT_INSTRUMENT_EVIDENCE"

    if len(exact_types) > 1 or (conflicts and exact is None):
        write = WRITE_SKIP_CONFLICT
        limitation = "SOURCE_CONFLICT"
    elif structured:
        instrument = structured
        source = "provider_explicit"
        best = _best_usability(ticker_assessment, cusip_assessment)
        ident = best.identifier
        itype = best.identifier_type
        layer = INSTRUMENT_TO_POLICY_ASSET_TYPE.get(instrument)
        write = WRITE_INSERT if ident else WRITE_SKIP_NO_EVIDENCE
        limitation = "" if ident else "IDENTIFIER_UNVERIFIED"
    elif exact is not None and exact.resolution is not None:
        resolution = exact.resolution
        instrument = resolution.instrument_type
        source = resolution.source
        ident = exact.assessment.identifier
        itype = exact.assessment.identifier_type
        layer = resolution.policy_asset_type
        write = WRITE_NONE
        limitation = "EXISTING_SECURITY_MASTER_FACT"
    else:
        best = _best_usability(ticker_assessment, cusip_assessment)
        ident = best.identifier
        itype = best.identifier_type
        if ident is None:
            limitation = "IDENTIFIER_UNVERIFIED"

    return SpskHoldingResolution(
        date=holding.as_of.isoformat(),
        stock_ticker=holding.ticker,
        cusip_raw=holding.cusip_raw,
        security_name=holding.security_name,
        weight_pct=float(holding.weight_pct),
        ticker_assessment=ticker_assessment,
        cusip_assessment=cusip_assessment,
        ticker_match=ticker_match,
        cusip_match=cusip_match,
        resolved_identifier=ident,
        identifier_type=itype,
        evidence_source=source,
        instrument_type=instrument,
        economic_layer=layer,
        write_action=write,
        limitation=limitation,
    )


def dry_run_spsk_holdings(
    holdings: Sequence[OfficialHolding],
    *,
    security_master: SecurityMasterService,
) -> SpskDryRunReport:
    report = SpskDryRunReport()
    usability = Counter()
    usability_weight: dict[str, float] = {}
    match_status = Counter()
    instruments: dict[str, float] = {}
    for holding in holdings:
        row = resolve_official_holding(holding, security_master=security_master)
        report.rows.append(row)
        best = _best_usability(row.ticker_assessment, row.cusip_assessment)
        usability[best.usability] += 1
        usability_weight[best.usability] = usability_weight.get(best.usability, 0.0) + row.weight_pct
        statuses = {row.ticker_match.status, row.cusip_match.status}
        if "CONFLICT" in statuses:
            key = "CONFLICT"
            report.conflict_weight += row.weight_pct
        elif "EXACT" in statuses:
            key = "EXACT"
            report.matched_weight += row.weight_pct
        else:
            key = "UNMATCHED"
            report.unmatched_weight += row.weight_pct
        match_status[key] += 1
        instruments[row.instrument_type] = instruments.get(row.instrument_type, 0.0) + row.weight_pct
    report.identifier_usability = dict(usability)
    report.identifier_weight = usability_weight
    report.match_status = dict(match_status)
    report.instrument_weight = instruments
    return report
