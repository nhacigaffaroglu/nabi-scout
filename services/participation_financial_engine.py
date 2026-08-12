from __future__ import annotations

from decimal import Decimal, InvalidOperation
from math import isfinite
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from services.participation_financial_contract import (
    FINANCIAL_SCREEN_OUTCOME_FAIL,
    FINANCIAL_SCREEN_OUTCOME_INSUFFICIENT_DATA,
    FINANCIAL_SCREEN_OUTCOME_PASS,
    FINANCIAL_SCREEN_OUTCOME_REVIEW_REQUIRED,
    ParticipationFinancialInputs,
    ParticipationFinancialScreenResult,
)
from services.participation_intelligence_contract import (
    RULE_OUTCOME_FAIL,
    RULE_OUTCOME_INSUFFICIENT_DATA,
    RULE_OUTCOME_PASS,
    RULE_OUTCOME_REVIEW_REQUIRED,
    ParticipationRuleResult,
)
from services.participation_methodology_registry import (
    MethodologyDefinition,
    MethodologyRuleDefinition,
    get_methodology,
)

NumeratorResolver = Callable[[ParticipationFinancialInputs], Optional[Decimal]]

DENOMINATOR_REGISTRY_TO_FIELD: Dict[str, str] = {
    "total_assets": "total_assets",
    "market_capitalization": "market_capitalization",
    "trailing_24_month_average_market_capitalization": "average_market_cap_24m",
    "trailing_36_month_average_market_value_of_equity": "average_market_value_of_equity_36m",
    "total_revenue": "total_revenue",
    "total_income": "total_income",
}

SUPPORTED_COMPARATORS = frozenset({"<", "<=", ">", ">="})


def _resolve_accounts_receivable_plus_cash(
    inputs: ParticipationFinancialInputs,
) -> Optional[Decimal]:
    receivable = normalize_financial_value(inputs.accounts_receivable)
    cash = normalize_financial_value(inputs.cash)
    if receivable is None or cash is None:
        return None
    return receivable + cash


def _field_numerator(field_name: str) -> NumeratorResolver:
    def _resolver(inputs: ParticipationFinancialInputs) -> Optional[Decimal]:
        return normalize_financial_value(getattr(inputs, field_name))

    return _resolver


NUMERATOR_RESOLVERS: Dict[str, NumeratorResolver] = {
    "total_debt": _field_numerator("total_debt"),
    "interest_bearing_debt": _field_numerator("interest_bearing_debt"),
    "cash_and_interest_bearing_securities": _field_numerator(
        "cash_and_interest_bearing_securities"
    ),
    "cash_plus_interest_bearing_securities": _field_numerator(
        "cash_plus_interest_bearing_securities"
    ),
    "cash_and_interest_bearing_items": _field_numerator("cash_and_interest_bearing_items"),
    "interest_taking_deposits": _field_numerator("interest_taking_deposits"),
    "accounts_receivable": _field_numerator("accounts_receivable"),
    "accounts_receivable_plus_cash": _resolve_accounts_receivable_plus_cash,
    "non_permissible_revenue": _field_numerator("non_permissible_revenue"),
    "non_permissible_income_excluding_interest": _field_numerator(
        "non_permissible_income_excluding_interest"
    ),
    "non_compliant_activities_income": _field_numerator("non_compliant_activities_income"),
    "prohibited_component_income": _field_numerator("prohibited_component_income"),
}


def normalize_financial_value(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        candidate = value
    elif isinstance(value, int):
        candidate = Decimal(value)
    elif isinstance(value, float):
        if not isfinite(value):
            return None
        candidate = Decimal(repr(value))
    elif isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            candidate = Decimal(stripped)
        except InvalidOperation:
            return None
    else:
        return None

    if not candidate.is_finite():
        return None
    if candidate < 0:
        return None
    return candidate


def resolve_denominator_value(
    denominator_key: str,
    inputs: ParticipationFinancialInputs,
) -> Tuple[Optional[Decimal], Optional[str]]:
    field_name = DENOMINATOR_REGISTRY_TO_FIELD.get(denominator_key)
    if field_name is None:
        return None, None
    return normalize_financial_value(getattr(inputs, field_name)), field_name


def compare_ratio_to_threshold(
    ratio_pct: Decimal,
    threshold_pct: Decimal,
    comparator: str,
) -> str:
    if comparator == "<":
        return RULE_OUTCOME_PASS if ratio_pct < threshold_pct else RULE_OUTCOME_FAIL
    if comparator == "<=":
        return RULE_OUTCOME_PASS if ratio_pct <= threshold_pct else RULE_OUTCOME_FAIL
    if comparator == ">":
        return RULE_OUTCOME_PASS if ratio_pct > threshold_pct else RULE_OUTCOME_FAIL
    if comparator == ">=":
        return RULE_OUTCOME_PASS if ratio_pct >= threshold_pct else RULE_OUTCOME_FAIL
    return RULE_OUTCOME_REVIEW_REQUIRED


def evaluate_ratio_rule(
    *,
    rule: MethodologyRuleDefinition,
    methodology: MethodologyDefinition,
    inputs: ParticipationFinancialInputs,
) -> ParticipationRuleResult:
    warnings: List[str] = []
    if rule.notes:
        warnings.append(rule.notes)

    numerator_resolver = NUMERATOR_RESOLVERS.get(rule.numerator)
    if numerator_resolver is None:
        return ParticipationRuleResult(
            rule_id=rule.rule_id,
            outcome=RULE_OUTCOME_REVIEW_REQUIRED,
            methodology_id=methodology.methodology_id,
            methodology_version=methodology.version,
            numerator_definition=rule.numerator,
            denominator_definition=rule.denominator,
            threshold_pct=rule.threshold_pct,
            comparator=rule.comparator,
            measurement_period=rule.measurement_period,
            warnings=tuple(
                warnings
                + [f"Numerator '{rule.numerator}' is not executable in 6B.2a."]
            ),
        )

    comparator = rule.comparator
    if comparator not in SUPPORTED_COMPARATORS:
        return ParticipationRuleResult(
            rule_id=rule.rule_id,
            outcome=RULE_OUTCOME_REVIEW_REQUIRED,
            methodology_id=methodology.methodology_id,
            methodology_version=methodology.version,
            numerator_definition=rule.numerator,
            denominator_definition=rule.denominator,
            threshold_pct=rule.threshold_pct,
            comparator=comparator,
            measurement_period=rule.measurement_period,
            warnings=tuple(
                warnings
                + [f"Comparator '{comparator}' is ambiguous or unsupported."]
            ),
        )

    if rule.threshold_pct is None:
        return ParticipationRuleResult(
            rule_id=rule.rule_id,
            outcome=RULE_OUTCOME_REVIEW_REQUIRED,
            methodology_id=methodology.methodology_id,
            methodology_version=methodology.version,
            numerator_definition=rule.numerator,
            denominator_definition=rule.denominator,
            comparator=comparator,
            measurement_period=rule.measurement_period,
            warnings=tuple(warnings + ["Threshold is not defined."]),
        )

    numerator = numerator_resolver(inputs)
    if numerator is None:
        return ParticipationRuleResult(
            rule_id=rule.rule_id,
            outcome=RULE_OUTCOME_INSUFFICIENT_DATA,
            methodology_id=methodology.methodology_id,
            methodology_version=methodology.version,
            numerator_definition=rule.numerator,
            denominator_definition=rule.denominator,
            threshold_pct=rule.threshold_pct,
            comparator=comparator,
            measurement_period=rule.measurement_period,
            warnings=tuple(warnings),
        )

    denominator, denominator_field = resolve_denominator_value(rule.denominator, inputs)
    if denominator is None or denominator_field is None:
        return ParticipationRuleResult(
            rule_id=rule.rule_id,
            outcome=RULE_OUTCOME_INSUFFICIENT_DATA,
            methodology_id=methodology.methodology_id,
            methodology_version=methodology.version,
            numerator_definition=rule.numerator,
            numerator_raw_value=float(numerator),
            denominator_definition=rule.denominator,
            threshold_pct=rule.threshold_pct,
            comparator=comparator,
            measurement_period=rule.measurement_period,
            warnings=tuple(warnings),
        )

    if denominator == 0:
        return ParticipationRuleResult(
            rule_id=rule.rule_id,
            outcome=RULE_OUTCOME_INSUFFICIENT_DATA,
            methodology_id=methodology.methodology_id,
            methodology_version=methodology.version,
            numerator_definition=rule.numerator,
            numerator_raw_value=float(numerator),
            denominator_definition=rule.denominator,
            denominator_raw_value=0.0,
            threshold_pct=rule.threshold_pct,
            comparator=comparator,
            measurement_period=rule.measurement_period,
            warnings=tuple(warnings + ["Denominator is zero."]),
        )

    ratio_pct = (numerator / denominator) * Decimal("100")
    threshold_pct = Decimal(str(rule.threshold_pct))
    outcome = compare_ratio_to_threshold(ratio_pct, threshold_pct, comparator)

    return ParticipationRuleResult(
        rule_id=rule.rule_id,
        outcome=outcome,
        methodology_id=methodology.methodology_id,
        methodology_version=methodology.version,
        numerator_definition=rule.numerator,
        numerator_raw_value=float(numerator),
        denominator_definition=rule.denominator,
        denominator_raw_value=float(denominator),
        ratio_pct=float(ratio_pct),
        threshold_pct=rule.threshold_pct,
        comparator=comparator,
        measurement_period=rule.measurement_period,
        source_dates=inputs.source_evidence,
        warnings=tuple(warnings),
    )


def aggregate_rule_outcomes(
    rule_results: Sequence[ParticipationRuleResult],
) -> str:
    if not rule_results:
        return FINANCIAL_SCREEN_OUTCOME_REVIEW_REQUIRED

    outcomes = {rule.outcome for rule in rule_results}
    if RULE_OUTCOME_FAIL in outcomes:
        return FINANCIAL_SCREEN_OUTCOME_FAIL
    if RULE_OUTCOME_REVIEW_REQUIRED in outcomes:
        return FINANCIAL_SCREEN_OUTCOME_REVIEW_REQUIRED
    if RULE_OUTCOME_INSUFFICIENT_DATA in outcomes:
        return FINANCIAL_SCREEN_OUTCOME_INSUFFICIENT_DATA

    evaluated = [
        rule
        for rule in rule_results
        if rule.outcome in {RULE_OUTCOME_PASS, RULE_OUTCOME_FAIL}
    ]
    if evaluated and all(rule.outcome == RULE_OUTCOME_PASS for rule in evaluated):
        return FINANCIAL_SCREEN_OUTCOME_PASS
    return FINANCIAL_SCREEN_OUTCOME_REVIEW_REQUIRED


def _methodology_complete_from_evaluation(
    methodology: MethodologyDefinition,
    *,
    financial_rules_evaluated: bool,
    overall_outcome: str,
    rule_results: Sequence[ParticipationRuleResult],
) -> bool:
    if not methodology.financial_screen_complete_methodology:
        return False
    return (
        financial_rules_evaluated
        and overall_outcome == FINANCIAL_SCREEN_OUTCOME_PASS
        and all(rule.outcome == RULE_OUTCOME_PASS for rule in rule_results)
    )


def evaluate_financial_rules(
    methodology_id: str,
    inputs: ParticipationFinancialInputs,
) -> ParticipationFinancialScreenResult:
    methodology = get_methodology(methodology_id)
    if methodology is None:
        raise ValueError(f"Unknown methodology_id: {methodology_id}")

    rule_results = tuple(
        evaluate_ratio_rule(rule=rule, methodology=methodology, inputs=inputs)
        for rule in methodology.rules
    )
    overall_outcome = aggregate_rule_outcomes(rule_results)
    financial_rules_evaluated = any(
        rule.outcome in {RULE_OUTCOME_PASS, RULE_OUTCOME_FAIL}
        for rule in rule_results
    )
    methodology_complete = _methodology_complete_from_evaluation(
        methodology,
        financial_rules_evaluated=financial_rules_evaluated,
        overall_outcome=overall_outcome,
        rule_results=rule_results,
    )

    warnings: List[str] = []
    if methodology.notes:
        warnings.append(methodology.notes)
    if financial_rules_evaluated and not methodology_complete:
        warnings.append(
            "Financial rule subset evaluated; full methodology completeness is not claimed."
        )

    return ParticipationFinancialScreenResult(
        symbol=inputs.symbol,
        methodology_id=methodology.methodology_id,
        methodology_version=methodology.version,
        rule_results=rule_results,
        overall_outcome=overall_outcome,
        as_of_date=inputs.as_of_date,
        financial_rules_evaluated=financial_rules_evaluated,
        methodology_complete=methodology_complete,
        warnings=tuple(warnings),
    )
