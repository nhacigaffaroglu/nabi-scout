from __future__ import annotations

import re
from typing import Any, Callable, Dict, Iterable, Mapping, MutableMapping

# Transient scan-time metadata persisted in scan_results.candidate_snapshot only.
NON_PERSISTED_CANDIDATE_FIELDS = frozenset({
    "fmp_source_status",
})

# Known investment_candidates columns from setup + migrations through Sprint 9.
PERSISTED_CANDIDATE_COLUMNS = frozenset({
    "annual_periods_found",
    "asset_type",
    "average_volume",
    "capital_allocation_score",
    "capital_efficiency_score",
    "cik",
    "collector_notes",
    "company_name",
    "conviction_score",
    "country",
    "critical_risk",
    "currency",
    "current_price",
    "current_ratio",
    "data_completeness",
    "data_source",
    "debt_to_equity",
    "decision",
    "decision_action",
    "decision_label",
    "decision_not_suitable_for",
    "decision_suitable_for",
    "decision_top_reasons",
    "decision_top_risks",
    "decision_verdict",
    "decision_version",
    "decision_why_now",
    "discount_to_fair_value",
    "dividend_yield",
    "enterprise_value",
    "eps_cagr_3y",
    "eps_growth",
    "ev_to_ebit",
    "exchange_name",
    "exclude_reason",
    "explanation_version",
    "fair_value",
    "fcf_cagr_3y",
    "financial_currency",
    "financial_health_score",
    "financial_period_end",
    "financial_taxonomy",
    "free_cash_flow",
    "free_cash_flow_margin",
    "freshness_label",
    "freshness_score",
    "freshness_status",
    "gross_margin",
    "growth_catalysts",
    "growth_explanation",
    "growth_score",
    "hard_flags",
    "interest_coverage",
    "last_reviewed_at",
    "investment_grade",
    "investment_profile",
    "investment_thesis",
    "liquidity_score",
    "main_reason",
    "market",
    "market_cap",
    "memo_conclusion",
    "memo_risks",
    "memo_strengths",
    "memo_summary",
    "memo_version",
    "memo_watch_items",
    "nabi_score",
    "negative_reasons",
    "net_debt",
    "net_debt_ebitda",
    "net_debt_to_fcf",
    "net_margin",
    "news_catalyst_score",
    "notes",
    "operating_income_estimated",
    "operating_margin",
    "opportunity_score",
    "owner_earnings",
    "participation_score",
    "participation_status",
    "payout_ratio",
    "pe_ratio",
    "pe_source",
    "peg_ratio",
    "peg_ratio_calculated",
    "period_age_days",
    "portfolio_fit_score",
    "positive_reasons",
    "price_to_book",
    "price_to_fcf",
    "price_to_sales",
    "profitability_score",
    "quality_explanation",
    "quality_score",
    "research_confidence",
    "research_confidence_explanation",
    "research_confidence_level",
    "research_confidence_reasons",
    "research_engine_version",
    "research_next_action",
    "research_note",
    "research_status",
    "return_12m",
    "return_3y_annualized",
    "revenue",
    "revenue_cagr_3y",
    "revenue_growth",
    "risk_score",
    "roa",
    "roe",
    "roic",
    "scanner_version",
    "score_confidence",
    "score_factors",
    "score_negative_factors",
    "score_neutral_factors",
    "score_penalty",
    "score_positive_factors",
    "score_reasons",
    "sector_theme",
    "security_type",
    "share_change_3y",
    "shareholder_score",
    "shares_outstanding",
    "source_updated_at",
    "source_url",
    "symbol",
    "thesis_bear_case",
    "thesis_bull_case",
    "thesis_concerns",
    "thesis_evidence",
    "thesis_revisit_conditions",
    "thesis_revisit_trigger",
    "thesis_strengths",
    "thesis_summary",
    "thesis_type",
    "thesis_valuation_view",
    "thesis_version",
    "valuation_explanation",
    "valuation_score",
})

# Optional metadata columns that may lag behind code deploy on some environments.
# Schema fallback may strip these on PGRST204 and retry once.
OPTIONAL_SCHEMA_FALLBACK_FIELDS = frozenset({
    "financial_currency",
    "financial_taxonomy",
    "pe_source",
    "freshness_status",
    "freshness_label",
    "period_age_days",
    "freshness_score",
})

CANONICAL_PERSISTED_COLUMNS = (
    PERSISTED_CANDIDATE_COLUMNS - OPTIONAL_SCHEMA_FALLBACK_FIELDS
)


def prepare_candidate_payload(
    payload: Mapping[str, Any],
    *,
    allowed_columns: Iterable[str] | None = None,
) -> Dict[str, Any]:
    allowed = (
        frozenset(allowed_columns)
        if allowed_columns is not None
        else PERSISTED_CANDIDATE_COLUMNS
    )
    cleaned: Dict[str, Any] = {}
    for key, value in payload.items():
        if key in NON_PERSISTED_CANDIDATE_FIELDS:
            continue
        if key not in allowed:
            continue
        cleaned[key] = value
    return cleaned


def dropped_candidate_fields(
    payload: Mapping[str, Any],
    *,
    allowed_columns: Iterable[str] | None = None,
) -> MutableMapping[str, str]:
    allowed = (
        frozenset(allowed_columns)
        if allowed_columns is not None
        else PERSISTED_CANDIDATE_COLUMNS
    )
    dropped: Dict[str, str] = {}
    for key in payload:
        if key in NON_PERSISTED_CANDIDATE_FIELDS:
            dropped[key] = "scan_snapshot_only"
        elif key not in allowed:
            dropped[key] = "unknown_column"
    return dropped


_MISSING_COLUMN_RE = re.compile(
    r"Could not find the '([^']+)' column",
)


def missing_column_name(exc: Exception) -> str | None:
    message = str(exc)
    if "PGRST204" not in message and "Could not find the" not in message:
        return None
    match = _MISSING_COLUMN_RE.search(message)
    return match.group(1) if match else None


def execute_with_schema_fallback(
    payload: Dict[str, Any],
    write_callable: Callable[[Dict[str, Any]], Any],
) -> Any:
    cleaned = dict(payload)
    while cleaned:
        try:
            return write_callable(cleaned)
        except Exception as exc:
            column = missing_column_name(exc)
            if (
                column
                and column in cleaned
                and column in OPTIONAL_SCHEMA_FALLBACK_FIELDS
            ):
                del cleaned[column]
                continue
            raise
    raise RuntimeError(
        "Candidate write payload became empty after optional schema fallback."
    )
