"""NABI Danışman contract. LLM may explain; it may not decide."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Optional, Tuple

INTENT_TODAY_RECOMMENDATION = "TODAY_RECOMMENDATION"
INTENT_WHY_RECOMMENDATION = "WHY_RECOMMENDATION"
INTENT_SYMBOL_EXPLAIN = "SYMBOL_EXPLAIN"
INTENT_OPPORTUNITY_COMPARE = "OPPORTUNITY_COMPARE"
INTENT_OPPORTUNITY_STATUS = "OPPORTUNITY_STATUS"
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
    INTENT_OPPORTUNITY_STATUS,
    INTENT_PORTFOLIO_FIT,
    INTENT_NEW_MONEY_SCENARIO,
    INTENT_GOAL_EXPLAIN,
    INTENT_PARTICIPATION_EXPLAIN,
    INTENT_RESEARCH_EXPLAIN,
    INTENT_GENERAL_NABI,
)

UNKNOWN = "UNKNOWN"
INSUFFICIENT_DATA = "veri yetersiz"
AMOUNT_REQUIRED = "AMOUNT_REQUIRED"
LLM_DISABLED_COPY = "Serbest sohbet açıklamaları için AI sohbeti etkin değil."
USER_SOURCE_COPY = (
    "NABI kararları doğrulanmış portföy ve analiz verilerine dayanır. "
    "AI yalnızca bu kararları açıklamak için kullanılır."
)
AMOUNT_CLARIFICATION = "Ne kadar yeni para dağıtmak istiyorsun?"
PENDING_NEW_MONEY_AMOUNT = "pending_new_money_amount"
NO_ACTIONABLE_OPPORTUNITY = "Şu anda yatırım için onaylanmış bir fırsat yok."
NOT_A_TRADE = "Bu bir al/sat önerisi değildir."
QUICK_QUESTIONS = (
    "Bugün ne yapmalıyım?",
    "Neden?",
    "Fırsat var mı?",
    "Yeni paramı nasıl dağıtmalıyım?",
    "2031 hedefim nasıl gidiyor?",
)

# Presentation-only. Canonical enum values stay unchanged.
ACTION_LABELS_TR = {
    "RESEARCH_FIRST": "Önce araştırmayı tamamla",
    "WATCH": "İzle",
    "WAIT": "Bekle",
    "CONSIDER_NEW_POSITION": "Yeni pozisyon değerlendirilebilir",
    "CONSIDER_TOP_UP": "Pozisyon artırımı değerlendirilebilir",
    "NO_ACTION": "Şimdilik işlem yok",
    "BLOCKED_PARTICIPATION": "Katılım uygun olmadığı için yatırım önerilmez",
    "REVIEW_GOAL_PLAN": "Katkı planını gözden geçir",
    "REVIEW_NEW_MONEY": "Yeni para dağılımını incele",
    "RESEARCH_OPPORTUNITY": "Öne çıkan fırsatı araştır",
    "HOLD_CURRENT_PORTFOLIO": "Mevcut portföyü koru",
}
MISSING_EVIDENCE_LABELS_TR = {
    "thesis_evidence": "yatırım tezi",
    "canonical_valuation_classification": "değerleme sınıflandırması",
    "catalyst_evidence": "katalizör kanıtı",
    "research_completeness": "araştırma tamamlığı",
    "nabi_evaluation": "NABI değerlendirmesi",
}
COMPLETENESS_LABELS_TR = {
    "HIGH": "yüksek",
    "MEDIUM": "orta",
    "LOW": "yetersiz",
}

_ACTION_REPLACE_ORDER = tuple(
    sorted(ACTION_LABELS_TR.keys(), key=len, reverse=True)
)


def present_action_label(code: Optional[str]) -> str:
    text = str(code or "").strip()
    if not text:
        return ""
    return ACTION_LABELS_TR.get(text, text)


def present_missing_evidence(code: str) -> str:
    text = str(code or "").strip()
    return MISSING_EVIDENCE_LABELS_TR.get(text, text.replace("_", " "))


def present_user_text(text: str) -> str:
    rendered = str(text or "")
    for code in _ACTION_REPLACE_ORDER:
        rendered = rendered.replace(code, ACTION_LABELS_TR[code])
    return rendered.replace("UNKNOWN", "belirsiz")


def format_try_display(value: Any, currency: Optional[str] = "TRY") -> str:
    if value in (None, "", UNKNOWN):
        return ""
    raw = str(value).strip().replace(" ", "")
    code = str(currency or "TRY").strip().upper()
    try:
        amount = Decimal(raw.replace(",", ""))
    except (InvalidOperation, ValueError, TypeError):
        if code in {"TRY", "TL"}:
            return f"{value} TL" if "TL" not in str(value) else str(value)
        return f"{value} {code}".strip()
    whole = int(amount.quantize(Decimal("1")))
    grouped = f"{whole:,}".replace(",", ".")
    if code in {"TRY", "TL"}:
        return f"{grouped} TL"
    if code == "USD":
        return f"${grouped}"
    return f"{grouped} {code}"


@dataclass(frozen=True)
class ParsedAdviserQuestion:
    question: str
    intent: str
    focus_symbol: Optional[str]
    compare_symbols: Tuple[str, ...]
    scenario_amount: Optional[str]
    scenario_currency: Optional[str]
    inherited_symbols: Tuple[str, ...] = ()


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
    prior_context: Optional[Mapping[str, Any]] = None

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
            "prior_context": dict(self.prior_context or {}),
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
    followup_state: dict[str, Any]
