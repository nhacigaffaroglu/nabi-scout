"""Weighted look-through analytics from official holdings.

Sector and country stay UNKNOWN unless official classification is supplied.
Does not infer issuer, country, or currency from names or ticker suffixes.
"""

from __future__ import annotations

from typing import Iterable, Optional, Sequence

from services.fund_product_contract import (
    CASH_TICKERS,
    FundHoldingsIntelligenceEvidence,
    FundLookthroughSummary,
    LookthroughHolding,
)
from services.official_fund_holdings_client import (
    MATERIAL_WEIGHT_MAX_PCT,
    MATERIAL_WEIGHT_MIN_PCT,
    OfficialHolding,
    OfficialHoldingsFile,
    SOURCE_SP_FUNDS_OFFICIAL,
)

UNKNOWN_WEIGHT_MISSING_PCT = 10.0
# Diversification uses effective holdings, not raw count, when count is large
# but HHI shows concentration. Thresholds are documented, not inferred.
DIVERSIFICATION_EFFECTIVE_N_BAD = 8.0
DIVERSIFICATION_EFFECTIVE_N_GOOD = 80.0
CONCENTRATED_EFFECTIVE_N = 20.0
LARGE_COUNT_FOR_HHI_OVERRIDE = 80
OFFICIAL_ISSUER_COLUMNS = frozenset(
    {"issuer", "issuername", "issuershortname", "obligor", "officialissuer"}
)


def _is_cash(row: OfficialHolding) -> bool:
    ident = str(row.holding_identifier or "").strip().upper()
    name = str(row.security_name or "").strip().upper()
    return ident in CASH_TICKERS or name in {"CASH & OTHER", "CASH AND OTHER", "CASH"}


def build_fund_lookthrough_summary(
    file: OfficialHoldingsFile,
    *,
    known_nabi_symbols: Optional[Iterable[str]] = None,
    official_sectors: Optional[dict[str, str]] = None,
    official_countries: Optional[dict[str, str]] = None,
) -> FundLookthroughSummary:
    known = {str(item).strip().upper() for item in (known_nabi_symbols or ())}
    sectors = official_sectors or {}
    countries = official_countries or {}
    rows = sorted(file.holdings, key=lambda item: float(item.weight_pct), reverse=True)
    holdings: list[LookthroughHolding] = []
    cash_w = 0.0
    unknown_w = 0.0
    overlap: list[str] = []
    for row in rows:
        ident = str(row.holding_identifier or "").strip().upper()
        cash = _is_cash(row)
        resolved = bool(ident) and not cash
        if cash:
            cash_w += float(row.weight_pct)
        if not ident:
            unknown_w += float(row.weight_pct)
            resolved = False
        if ident in known:
            overlap.append(ident)
        holdings.append(
            LookthroughHolding(
                holding_identifier=ident or "UNKNOWN",
                security_name=row.security_name,
                weight_pct=float(row.weight_pct),
                resolved=resolved,
                cash_or_other=cash,
            )
        )
    top = holdings[0] if holdings else None
    top5 = sum(item.weight_pct for item in holdings[:5])
    top10 = sum(item.weight_pct for item in holdings[:10])
    raw_sum = round(sum(float(item.weight_pct) for item in rows), 4)
    known_w = round(sum(item.weight_pct for item in holdings if item.resolved), 4)
    hhi = _hhi(tuple(item.weight_pct for item in holdings))
    effective = None if hhi is None or hhi <= 0 else round(1.0 / hhi, 4)
    sector_alloc: list[tuple[str, float]] = []
    country_alloc: list[tuple[str, float]] = []
    if sectors:
        buckets: dict[str, float] = {}
        for row in rows:
            label = sectors.get(str(row.holding_identifier or "").upper()) or "UNKNOWN"
            buckets[label] = buckets.get(label, 0.0) + float(row.weight_pct)
        sector_alloc = sorted(buckets.items(), key=lambda item: item[1], reverse=True)
    if countries:
        buckets = {}
        for row in rows:
            label = countries.get(str(row.holding_identifier or "").upper()) or "UNKNOWN"
            buckets[label] = buckets.get(label, 0.0) + float(row.weight_pct)
        country_alloc = sorted(buckets.items(), key=lambda item: item[1], reverse=True)
    limitation = ""
    if not sectors:
        limitation = "SECTOR_UNKNOWN"
    if not countries:
        limitation = f"{limitation}+COUNTRY_UNKNOWN" if limitation else "COUNTRY_UNKNOWN"
    return FundLookthroughSummary(
        fund_symbol=file.fund_symbol,
        as_of=file.as_of.isoformat(),
        holdings_count=len(holdings),
        top_holding=top,
        top_holding_weight_pct=top.weight_pct if top else None,
        top10_weight_pct=round(top10, 4),
        single_name_concentration_pct=top.weight_pct if top else None,
        cash_other_weight_pct=round(cash_w, 4),
        unknown_weight_pct=round(unknown_w, 4),
        sector_allocation=tuple(sector_alloc),
        country_allocation=tuple(country_alloc),
        known_nabi_overlap=tuple(sorted(set(overlap))),
        limitation=limitation,
        known_weight_pct=known_w,
        top5_weight_pct=round(top5, 4),
        raw_weight_sum_pct=raw_sum,
        rounding_difference_pct=round(raw_sum - 100.0, 4),
        weight_reconciled=MATERIAL_WEIGHT_MIN_PCT <= raw_sum <= MATERIAL_WEIGHT_MAX_PCT,
        hhi=hhi,
        effective_holdings=effective,
    )


def weight_sum(rows: Sequence[OfficialHolding]) -> float:
    return round(sum(float(item.weight_pct) for item in rows), 4)


def _hhi(weights: Sequence[float]) -> Optional[float]:
    if not weights:
        return None
    return round(sum((float(weight) / 100.0) ** 2 for weight in weights), 8)


def official_issuer_value(row: OfficialHolding) -> Optional[str]:
    """Use only an explicit official issuer column. Never parse the security name."""
    columns = (row.metadata or {}).get("issuer_columns") or {}
    for key, value in columns.items():
        token = str(key or "").strip().lower().replace(" ", "").replace("_", "")
        if token not in OFFICIAL_ISSUER_COLUMNS:
            continue
        text = str(value or "").strip()
        if text:
            return text
    return None


def official_issuer_field_present(file: OfficialHoldingsFile) -> bool:
    return any(official_issuer_value(row) for row in file.holdings)


def holdings_reliable(summary: FundLookthroughSummary) -> bool:
    if summary.holdings_count <= 0:
        return False
    return summary.unknown_weight_pct <= UNKNOWN_WEIGHT_MISSING_PCT


def build_holdings_intelligence_evidence(
    file: OfficialHoldingsFile,
    *,
    known_nabi_symbols: Optional[Iterable[str]] = None,
) -> FundHoldingsIntelligenceEvidence:
    summary = build_fund_lookthrough_summary(file, known_nabi_symbols=known_nabi_symbols)
    return FundHoldingsIntelligenceEvidence(
        fund_symbol=summary.fund_symbol,
        as_of=summary.as_of,
        holding_count=summary.holdings_count,
        known_weight=summary.known_weight_pct,
        unknown_weight=summary.unknown_weight_pct,
        largest_holding_weight=summary.top_holding_weight_pct,
        top_5_weight=summary.top5_weight_pct,
        top_10_weight=summary.top10_weight_pct,
        effective_number_of_holdings=summary.effective_holdings,
        hhi=summary.hhi,
        cash_other_weight=summary.cash_other_weight_pct,
        raw_weight_sum=summary.raw_weight_sum_pct,
        rounding_difference=summary.rounding_difference_pct,
        weight_reconciled=summary.weight_reconciled,
        source=file.source or SOURCE_SP_FUNDS_OFFICIAL,
        provenance=(file.source or SOURCE_SP_FUNDS_OFFICIAL, "official_holdings_weights"),
        official_issuer_field_present=official_issuer_field_present(file),
    )
