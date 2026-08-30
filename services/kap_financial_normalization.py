"""Normalize official KAP raw lines into canonical monetary facts.

Does not fetch KAP, invent zeros, treat YTD as TTM, or annualize.
Account mapping is by explicit code only.
"""

from __future__ import annotations

from typing import Iterable, Optional, Sequence

from services.kap_financial_contract import (
    ACCOUNT_ACCOUNTS_RECEIVABLE,
    ACCOUNT_CASH,
    ACCOUNT_CURRENT_ASSETS,
    ACCOUNT_CURRENT_LIABILITIES,
    ACCOUNT_NET_INCOME,
    ACCOUNT_OPERATING_INCOME,
    ACCOUNT_REVENUE,
    ACCOUNT_TOTAL_ASSETS,
    ACCOUNT_TOTAL_DEBT,
    ACCOUNT_TOTAL_EQUITY,
    EXPLICIT_UNIT_SCALES,
    IFRS_CASH,
    IFRS_CURRENT_ASSETS,
    IFRS_CURRENT_LIABILITIES,
    IFRS_CURRENT_TRADE_RECEIVABLES,
    IFRS_EQUITY,
    IFRS_NET_INCOME,
    IFRS_OPERATING_INCOME,
    IFRS_REVENUE,
    IFRS_TOTAL_ASSETS,
    KapDerivedFact,
    KapNormalizedBundle,
    KapNormalizedFinancialFact,
    KapRawFinancialLine,
    NATURE_FLOW,
    NATURE_POINT_IN_TIME,
    PERIOD_FY,
    PERIOD_Q,
    PERIOD_UNKNOWN,
    PERIOD_YTD,
)
from services.security_intelligence_contract import (
    PERIOD_INCOMPATIBLE,
    PERIOD_MIXED,
    PERIOD_TTM,
)


# Official-code → (canonical field, required nature). No label guessing.
KAP_ACCOUNT_CODE_MAP = {
    ACCOUNT_REVENUE: ("revenue", NATURE_FLOW),
    ACCOUNT_OPERATING_INCOME: ("operating_income", NATURE_FLOW),
    ACCOUNT_NET_INCOME: ("net_income", NATURE_FLOW),
    ACCOUNT_TOTAL_ASSETS: ("total_assets", NATURE_POINT_IN_TIME),
    ACCOUNT_TOTAL_EQUITY: ("equity", NATURE_POINT_IN_TIME),
    ACCOUNT_CASH: ("cash", NATURE_POINT_IN_TIME),
    ACCOUNT_TOTAL_DEBT: ("total_debt", NATURE_POINT_IN_TIME),
    ACCOUNT_CURRENT_ASSETS: ("current_assets", NATURE_POINT_IN_TIME),
    ACCOUNT_CURRENT_LIABILITIES: ("current_liabilities", NATURE_POINT_IN_TIME),
    ACCOUNT_ACCOUNTS_RECEIVABLE: ("accounts_receivable", NATURE_POINT_IN_TIME),
    IFRS_REVENUE: ("revenue", NATURE_FLOW),
    IFRS_OPERATING_INCOME: ("operating_income", NATURE_FLOW),
    IFRS_NET_INCOME: ("net_income", NATURE_FLOW),
    IFRS_TOTAL_ASSETS: ("total_assets", NATURE_POINT_IN_TIME),
    IFRS_EQUITY: ("equity", NATURE_POINT_IN_TIME),
    IFRS_CASH: ("cash", NATURE_POINT_IN_TIME),
    IFRS_CURRENT_ASSETS: ("current_assets", NATURE_POINT_IN_TIME),
    IFRS_CURRENT_LIABILITIES: ("current_liabilities", NATURE_POINT_IN_TIME),
    IFRS_CURRENT_TRADE_RECEIVABLES: ("accounts_receivable", NATURE_POINT_IN_TIME),
}

_INCOMPATIBLE_PERIOD_PAIRS = (
    frozenset({PERIOD_FY, PERIOD_YTD}),
    frozenset({PERIOD_FY, PERIOD_Q}),
    frozenset({PERIOD_YTD, PERIOD_Q}),
    frozenset({PERIOD_YTD, PERIOD_TTM}),
    frozenset({PERIOD_Q, PERIOD_TTM}),
)


def _text(raw: object) -> str:
    return str(raw or "").strip()


def normalize_reporting_period(raw: object) -> str:
    text = _text(raw).upper()
    if text in {PERIOD_FY, PERIOD_YTD, PERIOD_Q}:
        return text
    if text in {"ANNUAL", "YEAR", "YILLIK"}:
        return PERIOD_FY
    if text in {"INTERIM", "QUARTER", "CEYREK", "Q1", "Q2", "Q3", "Q4"}:
        return PERIOD_Q
    return PERIOD_UNKNOWN


def resolve_unit_scale(line: KapRawFinancialLine) -> Optional[int]:
    if line.unit_scale in {1, 1_000, 1_000_000}:
        return int(line.unit_scale)
    label = _text(line.unit_label).upper()
    if not label:
        return None
    return EXPLICIT_UNIT_SCALES.get(label)


def map_account_code(account_code: object) -> Optional[tuple[str, str]]:
    code = _text(account_code).upper()
    if not code:
        return None
    return KAP_ACCOUNT_CODE_MAP.get(code)


def period_compatibility(*period_kinds: str) -> str:
    kinds = {normalize_reporting_period(item) for item in period_kinds if _text(item)}
    kinds.discard("")
    if not kinds:
        return PERIOD_UNKNOWN
    if PERIOD_UNKNOWN in kinds:
        return PERIOD_INCOMPATIBLE if len(kinds) > 1 else PERIOD_UNKNOWN
    if any(pair <= kinds for pair in _INCOMPATIBLE_PERIOD_PAIRS):
        return PERIOD_INCOMPATIBLE
    if len(kinds) == 1:
        return next(iter(kinds))
    return PERIOD_MIXED


def _finite(raw: object) -> Optional[float]:
    if raw is None or raw == "":
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value != value or value in {float("inf"), float("-inf")}:
        return None
    return value


def normalize_raw_line(line: KapRawFinancialLine) -> Optional[KapNormalizedFinancialFact]:
    mapped = map_account_code(line.account_code)
    if mapped is None:
        return None
    field, required_nature = mapped
    raw_value = _finite(line.raw_value)
    if raw_value is None:
        return None
    scale = resolve_unit_scale(line)
    if scale is None:
        return None
    currency = _text(line.currency).upper()
    if not currency:
        return None
    period_kind = normalize_reporting_period(line.reporting_period)
    if period_kind == PERIOD_UNKNOWN:
        return None
    nature = _text(line.fact_nature).upper()
    if nature != required_nature:
        return None
    return KapNormalizedFinancialFact(
        field=field,
        symbol=_text(line.symbol).upper(),
        raw_value=raw_value,
        raw_unit_scale=scale,
        raw_unit_label=_text(line.unit_label),
        normalized_value=raw_value * scale,
        currency=currency,
        normalization_rule=f"RAW_TIMES_SCALE_{scale}",
        period_kind=period_kind,
        fact_nature=nature,
        statement_type=_text(line.statement_type).upper(),
        period_start=line.period_start,
        period_end=line.period_end,
        account_code=_text(line.account_code).upper() or None,
        account_label=line.account_label,
        source=line.source,
        source_document_id=line.source_document_id,
        as_of=line.as_of or line.period_end,
    )


def _compatible_pair(
    left: KapNormalizedFinancialFact,
    right: KapNormalizedFinancialFact,
) -> str:
    if left.currency != right.currency:
        return PERIOD_INCOMPATIBLE
    return period_compatibility(left.period_kind, right.period_kind)


def _ratio(
    field: str,
    numerator: Optional[KapNormalizedFinancialFact],
    denominator: Optional[KapNormalizedFinancialFact],
    *,
    as_percent: bool,
    rule: str,
) -> KapDerivedFact:
    if numerator is None or denominator is None:
        return KapDerivedFact(
            field=field,
            value=None,
            numerator_field=numerator.field if numerator else "",
            denominator_field=denominator.field if denominator else "",
            period_compatibility=PERIOD_UNKNOWN,
            currency="",
            normalization_rule=rule,
            limitation="MISSING_INPUT",
        )
    compatibility = _compatible_pair(numerator, denominator)
    if compatibility == PERIOD_INCOMPATIBLE:
        return KapDerivedFact(
            field=field,
            value=None,
            numerator_field=numerator.field,
            denominator_field=denominator.field,
            period_compatibility=compatibility,
            currency=numerator.currency,
            normalization_rule=rule,
            limitation="PERIOD_INCOMPATIBLE",
        )
    if denominator.normalized_value == 0:
        return KapDerivedFact(
            field=field,
            value=None,
            numerator_field=numerator.field,
            denominator_field=denominator.field,
            period_compatibility=compatibility,
            currency=numerator.currency,
            normalization_rule=rule,
            limitation="ZERO_DENOMINATOR",
        )
    value = numerator.normalized_value / denominator.normalized_value
    if as_percent:
        value *= 100.0
    return KapDerivedFact(
        field=field,
        value=value,
        numerator_field=numerator.field,
        denominator_field=denominator.field,
        period_compatibility=compatibility,
        currency=numerator.currency,
        normalization_rule=rule,
    )


def derive_compatible_ratios(
    facts: Sequence[KapNormalizedFinancialFact],
) -> tuple[KapDerivedFact, ...]:
    derived: list[KapDerivedFact] = []
    for period in (PERIOD_FY, PERIOD_YTD, PERIOD_Q):
        by_field = {item.field: item for item in facts if item.period_kind == period}
        if not by_field:
            continue
        derived.extend(
            (
                _ratio(
                    "roa",
                    by_field.get("net_income"),
                    by_field.get("total_assets"),
                    as_percent=True,
                    rule="NET_INCOME_OVER_ASSETS",
                ),
                _ratio(
                    "roe",
                    by_field.get("net_income"),
                    by_field.get("equity"),
                    as_percent=True,
                    rule="NET_INCOME_OVER_EQUITY",
                ),
                _ratio(
                    "debt_to_equity",
                    by_field.get("total_debt"),
                    by_field.get("equity"),
                    as_percent=False,
                    rule="DEBT_OVER_EQUITY",
                ),
                _ratio(
                    "current_ratio",
                    by_field.get("current_assets"),
                    by_field.get("current_liabilities"),
                    as_percent=False,
                    rule="CURRENT_ASSETS_OVER_CURRENT_LIABILITIES",
                ),
            )
        )
    return tuple(derived)


def fy_facts_only(
    facts: Sequence[KapNormalizedFinancialFact],
) -> tuple[KapNormalizedFinancialFact, ...]:
    return tuple(item for item in facts if item.period_kind == PERIOD_FY)


def facts_for_period(
    facts: Sequence[KapNormalizedFinancialFact],
    period_kind: str,
) -> tuple[KapNormalizedFinancialFact, ...]:
    wanted = normalize_reporting_period(period_kind)
    return tuple(item for item in facts if item.period_kind == wanted)


def normalize_kap_lines(
    lines: Iterable[KapRawFinancialLine],
    *,
    symbol: str,
    identity_source: str,
) -> KapNormalizedBundle:
    mapped: list[KapNormalizedFinancialFact] = []
    unmapped: list[str] = []
    for line in lines:
        code = _text(line.account_code).upper()
        fact = normalize_raw_line(line)
        if fact is None:
            if code and map_account_code(code) is None:
                unmapped.append(code)
            continue
        mapped.append(fact)
    derived = derive_compatible_ratios(mapped)
    periods = [item.period_kind for item in mapped]
    return KapNormalizedBundle(
        symbol=symbol,
        identity_source=identity_source,
        mapped=tuple(mapped),
        unmapped_account_codes=tuple(unmapped),
        derived=derived,
        period_compatibility=period_compatibility(*periods) if periods else PERIOD_UNKNOWN,
    )
