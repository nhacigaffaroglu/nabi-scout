"""NABI Danışman contract. LLM may explain; it may not decide."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Tuple

INTENT_TODAY_RECOMMENDATION = "TODAY_RECOMMENDATION"
INTENT_WHY_RECOMMENDATION = "WHY_RECOMMENDATION"
INTENT_SYMBOL_EXPLAIN = "SYMBOL_EXPLAIN"
INTENT_OPPORTUNITY_COMPARE = "OPPORTUNITY_COMPARE"
INTENT_PORTFOLIO_FIT = "PORTFOLIO_FIT"
INTENT_NEW_MONEY_SCENARIO = "NEW_MONEY_SCENARIO"
INTENT_GOAL_EXPLAIN = "GOAL_EXPLAIN"
INTENT_PARTICIPATION_EXPLAIN = "PARTICIPATION_EXPLAIN"
INTENT_RESEARCH_EXPLAIN = "RESEARCH_EXPLAIN"
INTENT_GENERAL_NABI = "GENERAL_NABI"

ADVISER_INTENTS = (
    INTENT_TODAY_RECOMMENDATION,
    INTENT_WHY_RECOMMENDATION,
    INTENT_SYMBOL_EXPLAIN,
    INTENT_OPPORTUNITY_COMPARE,
    INTENT_PORTFOLIO_FIT,
    INTENT_NEW_MONEY_SCENARIO,
    INTENT_GOAL_EXPLAIN,
    INTENT_PARTICIPATION_EXPLAIN,
    INTENT_RESEARCH_EXPLAIN,
    INTENT_GENERAL_NABI,
)

UNKNOWN = "UNKNOWN"
INSUFFICIENT_DATA = "veri yetersiz"
LLM_DISABLED_COPY = "Serbest sohbet açıklamaları için AI sohbeti etkin değil."
QUICK_QUESTIONS = (
    "Bugün ne yapmalıyım?",
    "Neden?",
    "Fırsat var mı?",
    "Yeni paramı nasıl dağıtmalıyım?",
    "2031 hedefim nasıl gidiyor?",
)


@dataclass(frozen=True)
class ParsedAdviserQuestion:
    question: str
    intent: str
    focus_symbol: Optional[str]
    compare_symbols: Tuple[str, ...]
    scenario_amount: Optional[str]
    scenario_currency: Optional[str]


@dataclass(frozen=True)
class NabiAdviserContext:
    question: str
    intent: str
    focus_symbol: Optional[str]
    current_recommendation: dict[str, Any]
    wealth_context: dict[str, Any]
    goal_context: dict[str, Any]
    new_money_context: dict[str, Any]
    candidate_decision: Optional[dict[str, Any]]
    participation_status: Optional[str]
    research_intelligence: Optional[dict[str, Any]]
    portfolio_fit: Optional[dict[str, Any]]
    opportunity_comparison: Tuple[dict[str, Any], ...]
    reason_codes: Tuple[str, ...]
    evidence_refs: Tuple[Any, ...]
    limitations: Tuple[str, ...]
    canonical_answer: str

    def to_llm_payload(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "intent": self.intent,
            "focus_symbol": self.focus_symbol,
            "current_recommendation": self.current_recommendation,
            "wealth_context": self.wealth_context,
            "goal_context": self.goal_context,
            "new_money_context": self.new_money_context,
            "candidate_decision": self.candidate_decision,
            "participation_status": self.participation_status,
            "research_intelligence": self.research_intelligence,
            "portfolio_fit": self.portfolio_fit,
            "opportunity_comparison": list(self.opportunity_comparison),
            "reason_codes": list(self.reason_codes),
            "evidence_refs": [
                item.to_dict() if hasattr(item, "to_dict") else item
                for item in self.evidence_refs
            ],
            "limitations": list(self.limitations),
            "canonical_answer": self.canonical_answer,
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_llm_payload()


@dataclass(frozen=True)
class NabiAdviserAnswer:
    answer: str
    intent: str
    focus_symbol: Optional[str]
    canonical_action: str
    used_llm: bool
    llm_calls: int
    limitations: Tuple[str, ...]
    grounded: bool
    canonical_answer: str
