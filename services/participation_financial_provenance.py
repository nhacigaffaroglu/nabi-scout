from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Sequence, Tuple

SOURCE_SEC = "SEC"
SOURCE_FMP = "FMP"
SOURCE_KAP = "KAP"
SOURCE_MIXED = "SEC + FMP"

NUMERATOR_TO_INPUT_FIELD: dict[str, str] = {
    "total_debt": "total_debt",
    "interest_bearing_debt": "interest_bearing_debt",
    "cash_and_interest_bearing_securities": "cash_and_interest_bearing_securities",
    "cash_plus_interest_bearing_securities": "cash_plus_interest_bearing_securities",
    "cash_and_interest_bearing_items": "cash_and_interest_bearing_items",
    "interest_taking_deposits": "interest_taking_deposits",
    "accounts_receivable": "accounts_receivable",
    "accounts_receivable_plus_cash": "accounts_receivable_plus_cash",
    "non_permissible_revenue": "non_permissible_revenue",
    "non_permissible_income_excluding_interest": "non_permissible_income_excluding_interest",
    "non_compliant_activities_income": "non_compliant_activities_income",
    "prohibited_component_income": "prohibited_component_income",
}

DENOMINATOR_TO_INPUT_FIELD: dict[str, str] = {
    "total_assets": "total_assets",
    "market_capitalization": "market_capitalization",
    "trailing_24_month_average_market_capitalization": "average_market_cap_24m",
    "trailing_36_month_average_market_value_of_equity": "average_market_value_of_equity_36m",
    "total_revenue": "total_revenue",
    "total_income": "total_income",
}


@dataclass(frozen=True)
class FinancialFieldProvenance:
    source: str
    source_fields: Tuple[str, ...] = ()
    period: Optional[str] = None


def _normalize_source_label(source: str) -> str:
    normalized = str(source or "").strip().upper()
    if normalized == SOURCE_SEC:
        return SOURCE_SEC
    if normalized == SOURCE_FMP:
        return SOURCE_FMP
    if normalized == SOURCE_KAP:
        return SOURCE_KAP
    return str(source or "").strip() or "—"


def combine_field_provenance(
    *items: FinancialFieldProvenance,
) -> FinancialFieldProvenance:
    present = [item for item in items if item.source]
    if not present:
        return FinancialFieldProvenance(source="—")

    sources = {_normalize_source_label(item.source) for item in present}
    if sources == {SOURCE_SEC}:
        combined_source = SOURCE_SEC
    elif sources == {SOURCE_FMP}:
        combined_source = SOURCE_FMP
    elif len(sources) == 1:
        combined_source = next(iter(sources))
    else:
        ordered = []
        for candidate in (SOURCE_SEC, SOURCE_FMP, SOURCE_KAP):
            if candidate in sources:
                ordered.append(candidate)
        combined_source = " + ".join(ordered) if ordered else SOURCE_MIXED

    fields: list[str] = []
    for item in present:
        for field_name in item.source_fields:
            if field_name and field_name not in fields:
                fields.append(field_name)

    period = next((item.period for item in present if item.period), None)
    return FinancialFieldProvenance(
        source=combined_source,
        source_fields=tuple(fields),
        period=period,
    )


def field_provenance_map(
    field_provenance: Sequence[Tuple[str, FinancialFieldProvenance]],
) -> dict[str, FinancialFieldProvenance]:
    return dict(field_provenance)


def resolve_input_field_provenance(
    field_name: Optional[str],
    provenance_by_field: Mapping[str, FinancialFieldProvenance],
) -> Optional[FinancialFieldProvenance]:
    if not field_name:
        return None
    return provenance_by_field.get(field_name)


def resolve_rule_metric_provenance(
    *,
    numerator_key: str,
    denominator_key: str,
    provenance_by_field: Mapping[str, FinancialFieldProvenance],
) -> FinancialFieldProvenance:
    numerator_field = NUMERATOR_TO_INPUT_FIELD.get(numerator_key)
    denominator_field = DENOMINATOR_TO_INPUT_FIELD.get(denominator_key)
    numerator_prov = resolve_input_field_provenance(
        numerator_field,
        provenance_by_field,
    )
    denominator_prov = resolve_input_field_provenance(
        denominator_field,
        provenance_by_field,
    )
    if numerator_prov is None and denominator_prov is None:
        return FinancialFieldProvenance(source="—")
    if numerator_prov is None:
        return denominator_prov or FinancialFieldProvenance(source="—")
    if denominator_prov is None:
        return numerator_prov
    return combine_field_provenance(numerator_prov, denominator_prov)
