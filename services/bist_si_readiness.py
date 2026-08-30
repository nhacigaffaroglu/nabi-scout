"""Read-only BIST Security Intelligence readiness audit.

Does not enable SI, lift 8E, change scores, or persist. Refuses YTD/Q as FY/TTM.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from services.kap_financial_bridge import kap_security_facts_payload
from services.kap_financial_contract import KapNormalizedBundle
from services.kap_financial_normalization import fy_facts_only
from services.security_intelligence_contract import (
    DIM_BALANCE_SHEET,
    DIM_DATA_QUALITY,
    DIM_GROWTH,
    DIM_MOMENTUM,
    DIM_PROFITABILITY,
    DIM_QUALITY,
    DIM_RISK,
    DIM_VALUATION,
    PERIOD_FY,
    PERIOD_Q,
    PERIOD_TTM,
    PERIOD_YTD,
    SecurityFacts,
)


SI_EVALUATION_BLOCKED_BY_READINESS = "SI_EVALUATION_BLOCKED_BY_READINESS"

STATUS_READY = "READY"
STATUS_PARTIAL = "PARTIAL"
STATUS_BLOCKED = "BLOCKED"
STATUS_NOT_APPLICABLE = "NOT_APPLICABLE"

EVAL_SAFE = "SAFE_TO_RUN"
EVAL_INSUFFICIENT = "RUN_WITH_INSUFFICIENT_DATA"
EVAL_UNSAFE = "UNSAFE_TO_RUN"

CORE_SI_DIMENSIONS = (
    DIM_QUALITY,
    DIM_GROWTH,
    DIM_PROFITABILITY,
    DIM_BALANCE_SHEET,
    DIM_VALUATION,
)

# Fields the current engine actually scores. Not the full SecurityFacts surface.
ENGINE_SCORED_FIELDS = {
    DIM_QUALITY: ("roic", "roe", "roa"),
    DIM_GROWTH: (
        "revenue_cagr_3y",
        "eps_cagr_3y",
        "fcf_cagr_3y",
        "revenue_growth_yoy",
        "eps_growth_yoy",
    ),
    DIM_PROFITABILITY: ("roic", "operating_margin", "fcf_margin", "net_margin", "gross_margin"),
    DIM_BALANCE_SHEET: ("current_ratio", "debt_to_equity", "net_debt_to_fcf", "interest_coverage"),
    DIM_VALUATION: ("pe", "price_to_sales", "price_to_book"),
    DIM_MOMENTUM: ("return_3m", "return_6m", "return_1y", "drawdown"),
    DIM_RISK: ("debt_to_equity", "net_debt_to_fcf", "current_ratio", "interest_coverage"),
}


def kap_period_kinds(bundle: Optional[KapNormalizedBundle]) -> frozenset[str]:
    if bundle is None:
        return frozenset()
    return frozenset(item.period_kind for item in bundle.mapped if item.period_kind)


def kap_payload_is_si_eligible(payload: Mapping[str, Any]) -> bool:
    period = str(payload.get("period_kind") or "").upper()
    if period in {PERIOD_YTD, PERIOD_TTM, PERIOD_Q}:
        return False
    if period != PERIOD_FY:
        return False
    return any(
        payload.get(field) is not None
        for field in (
            "revenue",
            "operating_income",
            "net_income",
            "total_assets",
            "equity",
            "cash",
            "roe",
            "roa",
        )
    )


def financials_present(facts: SecurityFacts) -> bool:
    return any(
        getattr(facts, field, None) is not None
        for field in (
            "revenue",
            "operating_income",
            "net_income",
            "total_assets",
            "equity",
            "cash",
            "roe",
            "roa",
            "roic",
            "operating_margin",
            "net_margin",
            "gross_margin",
            "current_ratio",
            "debt_to_equity",
        )
    )


def classify_shadow_evaluation(
    facts: SecurityFacts,
    *,
    kap_bundle: Optional[KapNormalizedBundle] = None,
) -> str:
    """Empty identity facts may evaluate fail-closed. YTD financials must not."""
    if facts.period_kind in {PERIOD_YTD, PERIOD_Q}:
        return EVAL_UNSAFE
    if financials_present(facts):
        if kap_bundle is not None:
            payload = kap_security_facts_payload(kap_bundle)
            if not kap_payload_is_si_eligible(payload) and facts.period_kind != PERIOD_FY:
                return EVAL_UNSAFE
        if facts.period_kind == PERIOD_FY:
            return EVAL_SAFE
        return EVAL_UNSAFE
    return EVAL_INSUFFICIENT


def dimension_readiness(
    facts: SecurityFacts,
    *,
    kap_bundle: Optional[KapNormalizedBundle] = None,
) -> dict[str, str]:
    """Current-engine readiness. YTD KAP cannot make a dimension READY."""
    periods = kap_period_kinds(kap_bundle)
    ytd_only = bool(periods) and not bool(fy_facts_only(kap_bundle.mapped if kap_bundle else ()))
    result: dict[str, str] = {}
    for name, fields in ENGINE_SCORED_FIELDS.items():
        present = sum(1 for field in fields if getattr(facts, field, None) is not None)
        if ytd_only:
            result[name] = STATUS_BLOCKED
            continue
        if present == len(fields):
            result[name] = STATUS_READY
        elif present:
            result[name] = STATUS_PARTIAL
        else:
            result[name] = STATUS_BLOCKED
    if ytd_only or not financials_present(facts):
        result[DIM_DATA_QUALITY] = STATUS_BLOCKED
    elif facts.completeness_pct is not None and facts.completeness_pct >= 50:
        result[DIM_DATA_QUALITY] = STATUS_PARTIAL
    else:
        result[DIM_DATA_QUALITY] = STATUS_BLOCKED
    return result


@dataclass(frozen=True)
class BistSiReadinessAudit:
    symbol: str
    facts_build_ok: bool
    kap_periods: tuple[str, ...]
    fy_fact_count: int
    shadow_evaluation: str
    readiness_block: str
    dimensions: dict[str, str]
    persisted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "facts_build_ok": self.facts_build_ok,
            "kap_periods": list(self.kap_periods),
            "fy_fact_count": self.fy_fact_count,
            "shadow_evaluation": self.shadow_evaluation,
            "readiness_block": self.readiness_block,
            "dimensions": dict(self.dimensions),
            "persisted": self.persisted,
        }


def audit_bist_si_readiness(
    facts: SecurityFacts,
    *,
    kap_bundle: Optional[KapNormalizedBundle] = None,
) -> BistSiReadinessAudit:
    periods = tuple(sorted(kap_period_kinds(kap_bundle)))
    fy_count = len(fy_facts_only(kap_bundle.mapped)) if kap_bundle is not None else 0
    shadow = classify_shadow_evaluation(facts, kap_bundle=kap_bundle)
    block = SI_EVALUATION_BLOCKED_BY_READINESS if shadow != EVAL_SAFE else ""
    return BistSiReadinessAudit(
        symbol=facts.symbol,
        facts_build_ok=True,
        kap_periods=periods,
        fy_fact_count=fy_count,
        shadow_evaluation=shadow,
        readiness_block=block,
        dimensions=dimension_readiness(facts, kap_bundle=kap_bundle),
        persisted=False,
    )


def inventory_kap_si_fields(bundle: KapNormalizedBundle) -> dict[str, str]:
    """Classify KAP fields against current SI needs. No new derivations."""
    mapped = {item.field: item.period_kind for item in bundle.mapped}
    derived = {item.field: item.period_compatibility for item in bundle.derived if item.value is not None}
    inventory = {
        "revenue": "AVAILABLE_CANONICAL" if "revenue" in mapped else "NOT_AVAILABLE",
        "operating_income": "AVAILABLE_CANONICAL" if "operating_income" in mapped else "NOT_AVAILABLE",
        "net_income": "AVAILABLE_CANONICAL" if "net_income" in mapped else "NOT_AVAILABLE",
        "total_assets": "AVAILABLE_CANONICAL" if "total_assets" in mapped else "NOT_AVAILABLE",
        "equity": "AVAILABLE_CANONICAL" if "equity" in mapped else "NOT_AVAILABLE",
        "cash": "AVAILABLE_CANONICAL" if "cash" in mapped else "NOT_AVAILABLE",
        "current_assets": "AVAILABLE_CANONICAL" if "current_assets" in mapped else "NOT_AVAILABLE",
        "current_liabilities": "AVAILABLE_CANONICAL" if "current_liabilities" in mapped else "NOT_AVAILABLE",
        "accounts_receivable": "AVAILABLE_CANONICAL" if "accounts_receivable" in mapped else "NOT_AVAILABLE",
        "total_debt": "NOT_AVAILABLE",
        "interest_bearing_debt": "NOT_AVAILABLE",
        "gross_profit": "AVAILABLE_RAW_ONLY",
        "operating_cash_flow": "AVAILABLE_RAW_ONLY",
        "capex": "AVAILABLE_RAW_ONLY",
        "free_cash_flow": "METHODOLOGY_UNRESOLVED",
        "ebit": "METHODOLOGY_UNRESOLVED",
        "ebitda": "NOT_AVAILABLE",
        "roe": "DERIVABLE_WITH_EXISTING_METHODOLOGY" if "roe" in derived else "NOT_AVAILABLE",
        "roa": "DERIVABLE_WITH_EXISTING_METHODOLOGY" if "roa" in derived else "NOT_AVAILABLE",
        "roic": "NOT_AVAILABLE",
        "current_ratio": "DERIVABLE_WITH_EXISTING_METHODOLOGY" if "current_ratio" in derived else "NOT_AVAILABLE",
        "shares_outstanding": "NOT_AVAILABLE",
        "market_cap": "NOT_AVAILABLE",
        "ttm": "NOT_AVAILABLE",
        "fy": "NOT_AVAILABLE" if not fy_facts_only(bundle.mapped) else "AVAILABLE_CANONICAL",
    }
    return inventory


def scored_fields_present(facts: SecurityFacts, dimension: str) -> tuple[str, ...]:
    return tuple(
        field
        for field in ENGINE_SCORED_FIELDS.get(dimension, ())
        if getattr(facts, field, None) is not None
    )
