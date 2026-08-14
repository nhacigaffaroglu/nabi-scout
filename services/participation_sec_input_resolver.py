from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Mapping, Optional, Tuple

from services.participation_financial_contract import ParticipationFinancialInputs
from services.participation_financial_provenance import (
    FinancialFieldProvenance,
    SOURCE_SEC,
    combine_field_provenance,
)

PARTICIPATION_INPUT_SOURCE_SEC = "SEC"

_SEC_XBRL_FIELD_TAGS: dict[str, tuple[str, ...]] = {
    "total_debt": ("LongTermDebtCurrent", "LongTermDebtNoncurrent"),
    "total_assets": ("Assets",),
    "cash": ("CashAndCashEquivalentsAtCarryingValue",),
    "accounts_receivable": ("AccountsReceivableNetCurrent",),
    "total_revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ),
}


@dataclass(frozen=True)
class ParticipationInputResolutionResult:
    inputs: ParticipationFinancialInputs
    source: str = PARTICIPATION_INPUT_SOURCE_SEC
    warnings: Tuple[str, ...] = field(default_factory=tuple)
    missing_fields: Tuple[str, ...] = field(default_factory=tuple)


def _parse_as_of_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _sec_currency_usable(sec_financials: Mapping[str, Any]) -> bool:
    currency = sec_financials.get("financial_currency")
    return currency in (None, "USD")


def _collect_missing_fields(
    *,
    sec_financials: Mapping[str, Any],
    inputs: ParticipationFinancialInputs,
    market_capitalization: Optional[float],
) -> Tuple[str, ...]:
    missing: list[str] = []
    sec_field_map = {
        "total_debt": sec_financials.get("total_debt"),
        "cash": sec_financials.get("cash"),
        "total_assets": sec_financials.get("total_assets"),
        "total_revenue": sec_financials.get("revenue"),
        "accounts_receivable": sec_financials.get("accounts_receivable"),
    }
    input_field_map = {
        "total_debt": inputs.total_debt,
        "cash": inputs.cash,
        "total_assets": inputs.total_assets,
        "total_revenue": inputs.total_revenue,
        "accounts_receivable": inputs.accounts_receivable,
        "market_capitalization": market_capitalization,
    }
    for name, sec_value in sec_field_map.items():
        if sec_value is None and input_field_map[name] is None:
            missing.append(name)
    if market_capitalization is None and inputs.market_capitalization is None:
        missing.append("market_capitalization")
    for field_name in (
        "interest_bearing_debt",
        "cash_and_interest_bearing_securities",
        "cash_plus_interest_bearing_securities",
        "average_market_cap_24m",
        "average_market_value_of_equity_36m",
        "non_permissible_revenue",
    ):
        if getattr(inputs, field_name) is None:
            missing.append(field_name)
    return tuple(dict.fromkeys(missing))


def _build_source_evidence(
    sec_financials: Mapping[str, Any],
    *,
    cik: Optional[str] = None,
) -> Tuple[Tuple[str, str], ...]:
    evidence: list[tuple[str, str]] = [("provider", "SEC")]
    if cik:
        evidence.append(("cik", str(cik)))
    for key in (
        "financial_period_end",
        "balance_sheet_period_end",
        "financial_currency",
        "financial_taxonomy",
        "annual_periods_found",
        "interest_bearing_securities_tags",
    ):
        value = sec_financials.get(key)
        if value is not None and value != "":
            evidence.append((key, str(value)))
    for field_name in (
        "total_debt",
        "cash",
        "total_assets",
        "revenue",
        "accounts_receivable",
        "interest_bearing_securities",
    ):
        if sec_financials.get(field_name) is not None:
            evidence.append((f"sec_field:{field_name}", "extract_financials"))
    return tuple(evidence)


def _interest_bearing_source_fields(sec_financials: Mapping[str, Any]) -> Tuple[str, ...]:
    tags = sec_financials.get("interest_bearing_securities_tags")
    if not tags:
        return ("interest_bearing_securities",)
    return tuple(
        part.strip()
        for part in str(tags).split("+")
        if part.strip()
    )


def _build_field_provenance(
    *,
    sec_financials: Mapping[str, Any],
    total_debt: Optional[float],
    cash: Optional[float],
    total_assets: Optional[float],
    total_revenue: Optional[float],
    accounts_receivable: Optional[float],
    interest_bearing_securities: Optional[float],
    cash_and_interest_bearing: Optional[float],
) -> Tuple[Tuple[str, FinancialFieldProvenance], ...]:
    period = (
        sec_financials.get("balance_sheet_period_end")
        or sec_financials.get("financial_period_end")
    )
    period_text = str(period) if period else None
    provenance: dict[str, FinancialFieldProvenance] = {}

    field_values = {
        "total_debt": total_debt,
        "total_assets": total_assets,
        "cash": cash,
        "accounts_receivable": accounts_receivable,
        "total_revenue": total_revenue,
    }
    for field_name, value in field_values.items():
        if value is not None and field_name in _SEC_XBRL_FIELD_TAGS:
            provenance[field_name] = FinancialFieldProvenance(
                source=SOURCE_SEC,
                source_fields=_SEC_XBRL_FIELD_TAGS[field_name],
                period=period_text,
            )

    if interest_bearing_securities is not None:
        provenance["interest_bearing_securities"] = FinancialFieldProvenance(
            source=SOURCE_SEC,
            source_fields=_interest_bearing_source_fields(sec_financials),
            period=period_text,
        )

    if cash_and_interest_bearing is not None:
        components = [
            provenance[name]
            for name in ("cash", "interest_bearing_securities")
            if name in provenance
        ]
        combined = combine_field_provenance(*components)
        provenance["cash_and_interest_bearing_securities"] = combined
        provenance["cash_plus_interest_bearing_securities"] = combined

    if accounts_receivable is not None and cash is not None:
        provenance["accounts_receivable_plus_cash"] = combine_field_provenance(
            provenance["accounts_receivable"],
            provenance["cash"],
        )

    return tuple(provenance.items())


def build_participation_inputs_from_sec(
    symbol: str,
    sec_financials: Mapping[str, Any],
    *,
    market_capitalization: Optional[float] = None,
    as_of_date: Optional[date | str] = None,
    cik: Optional[str] = None,
) -> ParticipationInputResolutionResult:
    warnings: list[str] = []
    normalized_symbol = str(symbol or "").strip().upper()
    parsed_as_of = _parse_as_of_date(as_of_date)
    if parsed_as_of is None:
        parsed_as_of = _parse_as_of_date(sec_financials.get("financial_period_end"))

    if not sec_financials:
        warnings.append("SEC financial payload is empty.")
        inputs = ParticipationFinancialInputs(
            symbol=normalized_symbol,
            as_of_date=parsed_as_of,
            source_evidence=(("provider", "SEC"),),
        )
        return ParticipationInputResolutionResult(
            inputs=inputs,
            warnings=tuple(warnings),
            missing_fields=_collect_missing_fields(
                sec_financials=sec_financials,
                inputs=inputs,
                market_capitalization=market_capitalization,
            ),
        )

    if sec_financials.get("annual_periods_found", 0) == 0 and not any(
        sec_financials.get(key) is not None
        for key in ("total_debt", "cash", "total_assets", "revenue")
    ):
        warnings.append("SEC annual financial periods were not found.")

    monetary_values_allowed = _sec_currency_usable(sec_financials)
    if not monetary_values_allowed:
        currency = sec_financials.get("financial_currency")
        warnings.append(
            f"SEC financial currency '{currency}' is not mapped in 6B.2b; "
            "monetary fields remain unset."
        )

    total_debt = (
        _optional_float(sec_financials.get("total_debt"))
        if monetary_values_allowed
        else None
    )
    cash = (
        _optional_float(sec_financials.get("cash"))
        if monetary_values_allowed
        else None
    )
    total_assets = (
        _optional_float(sec_financials.get("total_assets"))
        if monetary_values_allowed
        else None
    )
    total_revenue = (
        _optional_float(sec_financials.get("revenue"))
        if monetary_values_allowed
        else None
    )
    accounts_receivable = (
        _optional_float(sec_financials.get("accounts_receivable"))
        if monetary_values_allowed
        else None
    )
    interest_bearing_securities = (
        _optional_float(sec_financials.get("interest_bearing_securities"))
        if monetary_values_allowed
        else None
    )
    market_cap = _optional_float(market_capitalization)

    cash_and_interest_bearing = None
    cash_plus_interest_bearing = None
    if cash is not None and interest_bearing_securities is not None:
        combined = cash + interest_bearing_securities
        cash_and_interest_bearing = combined
        cash_plus_interest_bearing = combined

    source_evidence = _build_source_evidence(sec_financials, cik=cik)
    if interest_bearing_securities is not None:
        source_evidence = source_evidence + (
            ("sec_field:interest_bearing_securities", "extract_financials"),
        )
    if cash is not None and interest_bearing_securities is not None:
        source_evidence = source_evidence + (
            ("derived:cash_and_interest_bearing_securities", "cash_plus_interest_bearing_securities"),
        )

    inputs = ParticipationFinancialInputs(
        symbol=normalized_symbol,
        as_of_date=parsed_as_of,
        total_debt=total_debt,
        cash=cash,
        cash_and_interest_bearing_securities=cash_and_interest_bearing,
        cash_plus_interest_bearing_securities=cash_plus_interest_bearing,
        total_assets=total_assets,
        total_revenue=total_revenue,
        accounts_receivable=accounts_receivable,
        market_capitalization=market_cap,
        source_evidence=source_evidence,
        field_provenance=_build_field_provenance(
            sec_financials=sec_financials,
            total_debt=total_debt,
            cash=cash,
            total_assets=total_assets,
            total_revenue=total_revenue,
            accounts_receivable=accounts_receivable,
            interest_bearing_securities=interest_bearing_securities,
            cash_and_interest_bearing=cash_and_interest_bearing,
        ),
    )

    return ParticipationInputResolutionResult(
        inputs=inputs,
        source=PARTICIPATION_INPUT_SOURCE_SEC,
        warnings=tuple(warnings),
        missing_fields=_collect_missing_fields(
            sec_financials=sec_financials,
            inputs=inputs,
            market_capitalization=market_capitalization,
        ),
    )
