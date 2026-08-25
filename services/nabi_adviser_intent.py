"""Deterministic intent routing for NABI Danışman. No LLM."""

from __future__ import annotations

import re
from typing import Mapping, Optional, Tuple

from services.nabi_adviser_contract import (
    INTENT_GENERAL_NABI,
    INTENT_GOAL_EXPLAIN,
    INTENT_NEW_MONEY_SCENARIO,
    INTENT_OPPORTUNITY_COMPARE,
    INTENT_OPPORTUNITY_STATUS,
    INTENT_PARTICIPATION_EXPLAIN,
    INTENT_PORTFOLIO_FIT,
    INTENT_RESEARCH_EXPLAIN,
    INTENT_SYMBOL_EXPLAIN,
    INTENT_TODAY_RECOMMENDATION,
    INTENT_WHY_RECOMMENDATION,
    ParsedAdviserQuestion,
)
from services.wealth_adviser_prompt import extract_focus_symbol, sanitize_user_question

_SYMBOL_RE = re.compile(r"\b[A-Z]{1,5}\b")
_AMOUNT_RE = re.compile(
    r"(?P<amount>\d{1,3}(?:[.\s]\d{3})+|\d+)(?:[.,]\d+)?\s*(?:tl|try|lira)",
    re.IGNORECASE,
)
_IGNORE_SYMBOLS = {
    "AI", "ETF", "USD", "EUR", "TRY", "NABI", "SPY", "VOO", "QQQ", "TWR",
    "THE", "AND", "FOR", "NOT", "NE", "MI", "BU", "VE", "DE", "DA", "TL",
}
_SHORT_FOLLOWUPS = {
    "neden",
    "neden?",
    "neden böyle",
    "neden böyle?",
    "niçin",
    "niçin?",
    "niye",
    "niye?",
    "biraz açar mısın",
    "biraz açar mısın?",
    "biraz açar misin",
    "biraz açar misin?",
    "biraz aç",
    "biraz aç?",
    "daha açar mısın",
    "daha açar mısın?",
}


def extract_compare_symbols(question: str) -> Tuple[str, ...]:
    found: list[str] = []
    for match in _SYMBOL_RE.findall(sanitize_user_question(question).upper()):
        if match in _IGNORE_SYMBOLS or len(match) < 2:
            continue
        if match not in found:
            found.append(match)
    return tuple(found)


def extract_scenario_amount(question: str) -> Tuple[Optional[str], Optional[str]]:
    match = _AMOUNT_RE.search(sanitize_user_question(question))
    if match is None:
        return None, None
    raw = re.sub(r"[.\s]", "", match.group("amount"))
    if not raw.isdigit():
        return None, None
    return raw, "TRY"


def is_short_followup(question: str) -> bool:
    compact = re.sub(r"\s+", " ", sanitize_user_question(question).lower()).strip()
    return compact in _SHORT_FOLLOWUPS


def classify_intent(question: str) -> str:
    text = sanitize_user_question(question).lower()
    symbols = extract_compare_symbols(question)
    amount, _ = extract_scenario_amount(question)
    if is_short_followup(question):
        return INTENT_WHY_RECOMMENDATION
    if amount is not None or any(
        token in text
        for token in ("yeni para", "ekstra", "dağıt", "nereye koy", "koyayım")
    ):
        return INTENT_NEW_MONEY_SCENARIO
    if any(token in text for token in ("2031", "hedef", "yetiş")):
        return INTENT_GOAL_EXPLAIN
    if "research_first" in text or "research first" in text:
        return INTENT_RESEARCH_EXPLAIN
    if any(
        token in text
        for token in ("katılım", "halal", "uygun mu", "alsam", "almalı")
    ) and symbols:
        return INTENT_PARTICIPATION_EXPLAIN
    if len(symbols) >= 2:
        return INTENT_OPPORTUNITY_COMPARE
    if "araştır" in text or "research" in text:
        return INTENT_RESEARCH_EXPLAIN
    if any(token in text for token in ("portföy", "ağırlık", "fazla mı", "uyumu")):
        return INTENT_PORTFOLIO_FIT
    if any(
        token in text
        for token in ("fırsat var", "fırsatlar", "alınabilecek")
    ):
        return INTENT_OPPORTUNITY_STATUS
    if any(token in text for token in ("neden", "niçin", "niye")):
        return INTENT_WHY_RECOMMENDATION
    if any(
        token in text
        for token in (
            "bugün",
            "ne öner",
            "ne yapmalıyım",
        )
    ):
        return INTENT_TODAY_RECOMMENDATION
    if symbols:
        return INTENT_SYMBOL_EXPLAIN
    return INTENT_GENERAL_NABI


def parse_adviser_question(
    question: str,
    conversation_state: Optional[Mapping[str, object]] = None,
) -> ParsedAdviserQuestion:
    cleaned = sanitize_user_question(question)
    symbols = extract_compare_symbols(cleaned)
    amount, currency = extract_scenario_amount(cleaned)
    intent = classify_intent(cleaned)
    inherited: Tuple[str, ...] = ()
    prior = conversation_state or {}
    if intent == INTENT_WHY_RECOMMENDATION and not symbols:
        raw_prior = prior.get("symbols") or ()
        inherited = tuple(
            str(item).upper()
            for item in raw_prior
            if str(item or "").strip()
        )
    focus = extract_focus_symbol(cleaned)
    if intent == INTENT_OPPORTUNITY_COMPARE and symbols:
        focus = symbols[0]
    elif not focus and inherited:
        focus = inherited[0]
    return ParsedAdviserQuestion(
        question=cleaned,
        intent=intent,
        focus_symbol=focus,
        compare_symbols=symbols,
        scenario_amount=amount,
        scenario_currency=currency,
        inherited_symbols=inherited,
    )
