from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Tuple

from services.participation_business_contract import BusinessActivityScreenResult
from services.participation_financial_contract import ParticipationFinancialScreenResult
from services.participation_intelligence_contract import (
    RULE_OUTCOME_FAIL,
    RULE_OUTCOME_INSUFFICIENT_DATA,
    RULE_OUTCOME_PASS,
    RULE_OUTCOME_REVIEW_REQUIRED,
)
from services.participation_methodology_registry import get_methodology


EVALUATED_OUTCOMES = frozenset(
    {RULE_OUTCOME_PASS, RULE_OUTCOME_FAIL, RULE_OUTCOME_REVIEW_REQUIRED}
)


@dataclass(frozen=True)
class ParticipationAssessmentCompleteness:
    financial_rules_total: int = 0
    financial_rules_evaluated: int = 0
    business_rules_total: int = 0
    business_rules_evaluated: int = 0
    blocking_missing_capabilities: Tuple[str, ...] = field(default_factory=tuple)
    methodology_complete: bool = False
    assessment_complete: bool = False
    financial_methodology_complete: bool = False
    business_methodology_complete: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "financial_rules_total": self.financial_rules_total,
            "financial_rules_evaluated": self.financial_rules_evaluated,
            "business_rules_total": self.business_rules_total,
            "business_rules_evaluated": self.business_rules_evaluated,
            "blocking_missing_capabilities": list(self.blocking_missing_capabilities),
            "methodology_complete": self.methodology_complete,
            "assessment_complete": self.assessment_complete,
            "financial_methodology_complete": self.financial_methodology_complete,
            "business_methodology_complete": self.business_methodology_complete,
        }


def _count_evaluated_rules(
    screen: Optional[ParticipationFinancialScreenResult | BusinessActivityScreenResult],
) -> tuple[int, int]:
    if screen is None:
        return 0, 0
    total = len(screen.rule_results)
    evaluated = sum(
        1 for rule in screen.rule_results if rule.outcome in EVALUATED_OUTCOMES
    )
    return total, evaluated


def build_assessment_completeness(
    result: Any,
) -> ParticipationAssessmentCompleteness:
    methodology = (
        get_methodology(result.methodology_id) if result.methodology_id else None
    )
    financial_total, financial_evaluated = _count_evaluated_rules(
        result.financial_screen_result
    )
    business_total, business_evaluated = _count_evaluated_rules(
        result.business_screen_result
    )

    financial_methodology_complete = bool(
        result.financial_screen_result
        and result.financial_screen_result.methodology_complete
    )
    business_methodology_complete = bool(
        result.business_screen_result
        and result.business_screen_result.methodology_complete
    )

    blocking = tuple(result.missing_capabilities)
    assessment_complete = (
        financial_total > 0
        and financial_evaluated == financial_total
        and (
            result.business_screen_result is None
            or business_evaluated == business_total
        )
        and not blocking
    )
    methodology_complete = financial_methodology_complete and (
        result.business_screen_result is None or business_methodology_complete
    )

    if methodology is not None and not methodology.financial_screen_complete_methodology:
        methodology_complete = False
        assessment_complete = False

    return ParticipationAssessmentCompleteness(
        financial_rules_total=financial_total,
        financial_rules_evaluated=financial_evaluated,
        business_rules_total=business_total,
        business_rules_evaluated=business_evaluated,
        blocking_missing_capabilities=blocking,
        methodology_complete=methodology_complete,
        assessment_complete=assessment_complete,
        financial_methodology_complete=financial_methodology_complete,
        business_methodology_complete=business_methodology_complete,
    )


MISSING_CAPABILITY_LABELS_TR: Mapping[str, str] = {
    "prohibited_revenue_inference": (
        "Faaliyet gelirlerinin yasaklı alanlardan gelen payı güvenilir biçimde belirlenemedi."
    ),
    "historical_market_cap_24m": (
        "24 aylık tarihsel piyasa değeri verisi eksik veya yetersiz."
    ),
    "historical_market_value_equity_36m": (
        "36 aylık piyasa değeri özsermaye penceresi verisi eksik veya yetersiz."
    ),
    "business_activity_screening": (
        "Faaliyet alanı taraması için yeterli yapılandırılmış kanıt yok."
    ),
    "assessment_persistence": (
        "Katılım incelemesi geçmişi kaydı henüz etkin değil."
    ),
}


def translate_missing_capability(code: str) -> str:
    return MISSING_CAPABILITY_LABELS_TR.get(code, code.replace("_", " "))
