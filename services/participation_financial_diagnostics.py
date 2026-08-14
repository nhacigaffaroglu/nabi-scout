from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, List, Mapping, Optional, Sequence

from services.participation_financial_contract import ParticipationFinancialScreenResult
from services.participation_intelligence_contract import (
    RULE_OUTCOME_FAIL,
    RULE_OUTCOME_INSUFFICIENT_DATA,
    RULE_OUTCOME_PASS,
    RULE_OUTCOME_REVIEW_REQUIRED,
    ParticipationRuleResult,
)

RULE_LABELS_TR: Dict[str, str] = {
    "msci.total_debt_to_total_assets": "Borç oranı",
    "msci.cash_and_interest_bearing_to_total_assets": "Nakit ve faizli menkul kıymet oranı",
    "msci.receivables_and_cash_to_total_assets": "Alacak ve nakit oranı",
    "msci.non_permissible_revenue": "İzin verilmeyen gelir oranı",
}

NUMERATOR_LABELS_TR: Dict[str, str] = {
    "total_debt": "Borç",
    "cash_and_interest_bearing_securities": "Nakit + faizli menkul kıymetler",
    "accounts_receivable_plus_cash": "Alacak + nakit",
    "non_permissible_revenue": "İzin verilmeyen gelir",
}

DENOMINATOR_LABELS_TR: Dict[str, str] = {
    "total_assets": "Toplam varlık",
    "total_revenue": "Toplam gelir",
}

OUTCOME_LABELS_TR: Dict[str, str] = {
    RULE_OUTCOME_PASS: "Geçti",
    RULE_OUTCOME_FAIL: "Başarısız",
    RULE_OUTCOME_REVIEW_REQUIRED: "İnceleme gerekli",
    RULE_OUTCOME_INSUFFICIENT_DATA: "Değerlendirilemedi",
}

_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|token|secret|password|authorization)\s*[:=]"),
    re.compile(r"(?i)bearer\s+[a-z0-9\-_.]+"),
)

_INSUFFICIENT_REASONS_TR: Dict[str, str] = {
    "total_debt": "Toplam borç kanıtı bulunamadı.",
    "cash_and_interest_bearing_securities": (
        "Nakit ve faizli menkul kıymet kanıtı eksik; "
        "her iki bileşen aynı bilanço döneminde gerekli."
    ),
    "accounts_receivable_plus_cash": "Alacak veya nakit kanıtı bulunamadı.",
    "non_permissible_revenue": "Yasak gelir segmenti kanıtı bulunamadı.",
}


def _format_amount(value: Optional[float]) -> str:
    if value is None:
        return "—"
    abs_value = abs(value)
    if abs_value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f} milyar"
    if abs_value >= 1_000_000:
        return f"{value / 1_000_000:.2f} milyon"
    return f"{value:,.0f}"


def _format_ratio(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return f"{value:.2f}%"


def _format_threshold(threshold: Optional[float], comparator: Optional[str]) -> str:
    if threshold is None:
        return "—"
    operator = comparator or "<="
    return f"{operator} {threshold:.2f}%"


def _format_period(
    measurement_period: Optional[str],
    as_of_date: Optional[date],
    source_dates: Mapping[str, str],
) -> str:
    period_end = source_dates.get("financial_period_end") or source_dates.get(
        "balance_sheet_period_end"
    )
    if period_end:
        return f"FY {period_end[:10]}"
    if as_of_date is not None:
        return f"FY {as_of_date.isoformat()}"
    if measurement_period:
        return measurement_period
    return "—"


def _source_label(rule: ParticipationRuleResult, source_dates: Mapping[str, str]) -> str:
    if rule.metric_source and rule.metric_source != "—":
        return str(rule.metric_source)
    provider = source_dates.get("provider")
    if provider:
        return str(provider)
    return "—"


def _source_fields_label(rule: ParticipationRuleResult) -> str:
    if rule.metric_source_fields:
        return ", ".join(rule.metric_source_fields)
    return ""


def _insufficient_reason(rule: ParticipationRuleResult) -> str:
    numerator = rule.numerator_definition or ""
    if numerator in _INSUFFICIENT_REASONS_TR:
        return _INSUFFICIENT_REASONS_TR[numerator]
    return "Bu kural için yeterli kanıt bulunamadı."


def format_financial_rule_diagnostic(
    rule: ParticipationRuleResult,
    *,
    as_of_date: Optional[date] = None,
) -> Dict[str, Any]:
    source_dates = dict(rule.source_dates or ())
    rule_name = RULE_LABELS_TR.get(rule.rule_id, rule.rule_id)
    numerator_name = NUMERATOR_LABELS_TR.get(
        rule.numerator_definition or "",
        rule.numerator_definition or "—",
    )
    denominator_name = DENOMINATOR_LABELS_TR.get(
        rule.denominator_definition or "",
        rule.denominator_definition or "—",
    )
    status = OUTCOME_LABELS_TR.get(rule.outcome, rule.outcome)
    payload: Dict[str, Any] = {
        "rule_id": rule.rule_id,
        "rule_name": rule_name,
        "status": status,
        "numerator_name": numerator_name,
        "numerator_value": _format_amount(rule.numerator_raw_value),
        "denominator_name": denominator_name,
        "denominator_value": _format_amount(rule.denominator_raw_value),
        "calculated_ratio": _format_ratio(rule.ratio_pct),
        "threshold": _format_threshold(rule.threshold_pct, rule.comparator),
        "comparison_operator": rule.comparator or "—",
        "fiscal_period": _format_period(
            rule.measurement_period,
            as_of_date,
            source_dates,
        ),
        "statement_date": source_dates.get("balance_sheet_period_end")
        or source_dates.get("financial_period_end")
        or (as_of_date.isoformat() if as_of_date else None),
        "source": _source_label(rule, source_dates),
        "source_field": rule.numerator_definition or "—",
        "source_fields": _source_fields_label(rule),
        "limitations": _insufficient_reason(rule)
        if rule.outcome == RULE_OUTCOME_INSUFFICIENT_DATA
        else "",
    }
    if rule.warnings:
        payload["limitations"] = "; ".join(rule.warnings[:3])
    return payload


def serialize_financial_diagnostics(
    screen: Optional[ParticipationFinancialScreenResult],
    *,
    as_of_date: Optional[date] = None,
) -> List[Dict[str, Any]]:
    if screen is None:
        return []
    return [
        format_financial_rule_diagnostic(rule, as_of_date=as_of_date or screen.as_of_date)
        for rule in screen.rule_results
    ]


def assert_diagnostic_payload_safe(payload: Mapping[str, Any]) -> None:
    for value in payload.values():
        if not isinstance(value, str):
            continue
        for pattern in _SECRET_PATTERNS:
            if pattern.search(value):
                raise ValueError("Diagnostic payload contains sensitive material.")
