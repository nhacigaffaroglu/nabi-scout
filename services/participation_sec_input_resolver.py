from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Mapping, Optional, Tuple

from services.participation_financial_contract import ParticipationFinancialInputs

PARTICIPATION_INPUT_SOURCE_SEC = "SEC"


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
        "financial_currency",
        "financial_taxonomy",
        "annual_periods_found",
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
    ):
        if sec_financials.get(field_name) is not None:
            evidence.append((f"sec_field:{field_name}", "extract_financials"))
    return tuple(evidence)


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
    market_cap = _optional_float(market_capitalization)

    inputs = ParticipationFinancialInputs(
        symbol=normalized_symbol,
        as_of_date=parsed_as_of,
        total_debt=total_debt,
        cash=cash,
        total_assets=total_assets,
        total_revenue=total_revenue,
        accounts_receivable=accounts_receivable,
        market_capitalization=market_cap,
        source_evidence=_build_source_evidence(sec_financials, cik=cik),
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
