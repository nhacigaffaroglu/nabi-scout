from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Dict, Optional, Tuple

from services.participation_financial_provenance import FinancialFieldProvenance

from services.participation_intelligence_contract import (
    RULE_OUTCOME_FAIL,
    RULE_OUTCOME_INSUFFICIENT_DATA,
    RULE_OUTCOME_PASS,
    RULE_OUTCOME_REVIEW_REQUIRED,
    ParticipationRuleResult,
)

FINANCIAL_SCREEN_OUTCOME_PASS = RULE_OUTCOME_PASS
FINANCIAL_SCREEN_OUTCOME_FAIL = RULE_OUTCOME_FAIL
FINANCIAL_SCREEN_OUTCOME_REVIEW_REQUIRED = RULE_OUTCOME_REVIEW_REQUIRED
FINANCIAL_SCREEN_OUTCOME_INSUFFICIENT_DATA = RULE_OUTCOME_INSUFFICIENT_DATA


@dataclass(frozen=True)
class ParticipationFinancialInputs:
    symbol: str
    as_of_date: Optional[date] = None
    total_debt: Optional[float] = None
    interest_bearing_debt: Optional[float] = None
    cash: Optional[float] = None
    cash_and_interest_bearing_securities: Optional[float] = None
    cash_plus_interest_bearing_securities: Optional[float] = None
    cash_and_interest_bearing_items: Optional[float] = None
    interest_taking_deposits: Optional[float] = None
    accounts_receivable: Optional[float] = None
    total_assets: Optional[float] = None
    market_capitalization: Optional[float] = None
    average_market_cap_24m: Optional[float] = None
    average_market_value_of_equity_36m: Optional[float] = None
    total_revenue: Optional[float] = None
    total_income: Optional[float] = None
    non_permissible_revenue: Optional[float] = None
    non_permissible_income_excluding_interest: Optional[float] = None
    non_compliant_activities_income: Optional[float] = None
    prohibited_component_income: Optional[float] = None
    source_evidence: Tuple[Tuple[str, str], ...] = field(default_factory=tuple)
    field_provenance: Tuple[Tuple[str, FinancialFieldProvenance], ...] = field(
        default_factory=tuple
    )

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["source_evidence"] = dict(self.source_evidence)
        payload["field_provenance"] = {
            field_name: {
                "source": provenance.source,
                "source_fields": list(provenance.source_fields),
                "period": provenance.period,
            }
            for field_name, provenance in self.field_provenance
        }
        if self.as_of_date is not None:
            payload["as_of_date"] = self.as_of_date.isoformat()
        return payload


@dataclass(frozen=True)
class ParticipationFinancialScreenResult:
    symbol: str
    methodology_id: str
    methodology_version: str
    rule_results: Tuple[ParticipationRuleResult, ...]
    overall_outcome: str
    as_of_date: Optional[date] = None
    financial_rules_evaluated: bool = False
    methodology_complete: bool = False
    warnings: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "methodology_id": self.methodology_id,
            "methodology_version": self.methodology_version,
            "rule_results": [rule.to_dict() for rule in self.rule_results],
            "overall_outcome": self.overall_outcome,
            "as_of_date": self.as_of_date.isoformat() if self.as_of_date else None,
            "financial_rules_evaluated": self.financial_rules_evaluated,
            "methodology_complete": self.methodology_complete,
            "warnings": list(self.warnings),
        }
