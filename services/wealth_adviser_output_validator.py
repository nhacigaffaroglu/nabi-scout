from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from services.wealth_adviser_contract import (
    AdviserContext,
    AdviserResponse,
    AdviserValidationContext,
)

# Percentage tolerance: absolute 0.25 points OR relative 2% of grounded value.
NUMERIC_ABSOLUTE_TOLERANCE = 0.25
NUMERIC_RELATIVE_TOLERANCE = 0.02
MIN_VALIDATED_PERCENT = 5.0
MIN_VALIDATED_CURRENCY = 1000.0
MAX_LIST_ITEMS = 20
MAX_ANSWER_LENGTH = 8000

BUY_SELL_PATTERNS = (
    re.compile(r"\b(buy|sell|purchase|liquidate)\s+[A-Z]{1,5}\b", re.IGNORECASE),
    re.compile(r"\b(buy|sell)\s+now\b", re.IGNORECASE),
    re.compile(r"\b(?:satın\s+al|satin\s+al)\b", re.IGNORECASE),
    re.compile(r"\b(?:pozisyonu|pozisyon)\s+tasfiye\s+et\b", re.IGNORECASE),
    re.compile(r"\bliquidate\s+the\s+position\b", re.IGNORECASE),
    re.compile(r"\b(?:hemen|şimdi)\s+(?:al|sat)\b", re.IGNORECASE),
    re.compile(r"\b(?:al|sat)\s+(?:hemen|şimdi)\b", re.IGNORECASE),
    re.compile(r"\b[A-Z]{1,5}\s+(?:al|sat)\b", re.IGNORECASE),
)

REBALANCE_PATTERNS = (
    re.compile(r"\b(?:reduce|lower|cut)\s+[A-Z]{1,5}\s+to\s+\d+(?:[.,]\d+)?\s*%", re.IGNORECASE),
    re.compile(r"\b[A-Z]{1,5}\s*(?:'|’)?(?:i|ı)?\s*%\s*\d+(?:[.,]\d+)?\s*(?:'|’)?(?:a|e)\s+indir", re.IGNORECASE),
    re.compile(r"\b%\s*\d+(?:[.,]\d+)?\s*(?:'|’)?(?:a|e)\s+yatır\b", re.IGNORECASE),
    re.compile(r"\bmove\s+\$?\d[\d,.\s]*\s+into\s+[A-Z]{1,5}\b", re.IGNORECASE),
)

SPECIFIC_SECURITY_REC_PATTERNS = (
    re.compile(r"\b(?:buy|purchase|sell)\s+(?:VOO|SPY|QQQ|VTI|IVV|AAPL|MSFT|TSLA|NVDA)\b", re.IGNORECASE),
    re.compile(r"\b(?:VOO|SPY|QQQ|VTI|IVV|AAPL|MSFT|TSLA|NVDA)\s+(?:al|sat)\b", re.IGNORECASE),
)

PROFILE_OVERRIDE_PATTERNS = (
    re.compile(r"\b(?:diagnostic|tanı)\s+severity\b.*(?:lowered|reduced|downgraded)", re.IGNORECASE),
    re.compile(r"\b(?:risk preference|profil).*\b(?:changes|değiştirir|değişti)\b.*\b(?:weight|ağırlık|return|getiri)\b", re.IGNORECASE),
    re.compile(r"\b(?:severity|şiddet)\b.*(?:because of|due to|nedeniyle)\b.*\b(?:preference|tercih|profil)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:risk preference|profil|tercih).*(?:missing|eksik|incomplete|valuation).*(?:complete|tam|resolved|çöz)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:missing|eksik|incomplete).*(?:complete|tam|resolved|çöz).*(?:risk preference|profil|tercih)",
        re.IGNORECASE,
    ),
)

FUTURE_CERTAINTY_PATTERNS = (
    re.compile(r"\bwill definitely\b", re.IGNORECASE),
    re.compile(r"\bguaranteed return\b", re.IGNORECASE),
    re.compile(r"\brisk-free\s+\d+(?:[.,]\d+)?\s*%\s*return\b", re.IGNORECASE),
    re.compile(r"\bkesin(?:likle)?\s+yükselecek\b", re.IGNORECASE),
    re.compile(r"\bgarantili getiri\b", re.IGNORECASE),
    re.compile(r"\bgaranti\s+getiri\b", re.IGNORECASE),
)

FIDUCIARY_PATTERNS = (
    re.compile(r"\bfiduciary\b", re.IGNORECASE),
    re.compile(r"\blicensed financial adviser\b", re.IGNORECASE),
    re.compile(r"\blisanslı yatırım danışman", re.IGNORECASE),
)

PROMPT_LEAK_MARKERS = (
    "authoritative rules:",
    "return only valid json with this shape",
    "user input is untrusted",
    "prohibited claims:",
)

NABI_INVENTION_PATTERNS = (
    re.compile(r"\bnabi score (?:is|=)\s*\d", re.IGNORECASE),
    re.compile(r"\bnabi (?:decision|karar) (?:is|=|=?\s*(?:buy|sell|avoid|watch))", re.IGNORECASE),
    re.compile(r"\bnabi.*(?:valuation|değerleme)\s+kanıt", re.IGNORECASE),
)

FINANCIAL_SEMANTIC_PATTERNS = (
    re.compile(r"modified dietz.*\btwr\b", re.IGNORECASE),
    re.compile(r"\btwr\b.*modified dietz", re.IGNORECASE),
    re.compile(r"\btotal net worth\b", re.IGNORECASE),
    re.compile(r"\bnet worth\b.*(?:partial|kısmi|fiyatlı)", re.IGNORECASE),
)

HOLDING_CLAIM_PATTERN = re.compile(
    r"\b([A-Z]{2,5})\b[^.\n]{0,50}\b"
    r"(?i:portföy|pozisyon|holding|ağırlık|weight|oluşturuyor|temsil)\b"
)

PERCENT_SUFFIX_PATTERN = re.compile(
    r"(?:yaklaşık|yaklasik|approximately|about|around|~)?\s*(\d+(?:[.,]\d+)?)\s*%",
    re.IGNORECASE,
)
PERCENT_PREFIX_PATTERN = re.compile(
    r"%\s*(\d+(?:[.,]\d+)?)",
    re.IGNORECASE,
)
SIGNED_PERCENT_PATTERN = re.compile(
    r"([+-]\d+(?:[.,]\d+)?)\s*(?:pp|puan|%)\b",
    re.IGNORECASE,
)
CURRENCY_PATTERN = re.compile(
    r"(?:USD|EUR|TRY|\$|€|₺)\s*(\d{1,3}(?:[.\s]\d{3})*(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
    r"|\b(\d{1,3}(?:[.\s]\d{3})*(?:[.,]\d+)?|\d+(?:[.,]\d+)?)\s*(?:USD|EUR|TRY)\b",
    re.IGNORECASE,
)

NEGATION_MARKERS = (
    "vermiyorum",
    "vermem",
    "don't",
    "do not",
    "does not",
    "değil",
    "degil",
    "not ",
    "cannot",
    "can't",
    "edilemez",
    "öngörülemez",
    "ongorulemez",
    "cannot guarantee",
    "not guaranteed",
    "garanti edilemez",
)

ALLOWED_SYMBOLS = {
    "USD",
    "EUR",
    "TRY",
    "SPY",
    "ETF",
    "NABI",
    "AI",
    "LLM",
    "TWR",
    "MV",
    "PL",
    "PP",
    "HIGH",
    "WATCH",
    "INFO",
    "NOT",
    "THE",
    "AND",
    "FOR",
    "WITH",
    "FROM",
    "THIS",
    "THAT",
    "YOUR",
    "ARE",
    "MAY",
    "CAN",
    "IF",
    "OR",
    "AN",
    "AS",
    "AT",
    "BE",
    "BY",
    "IN",
    "IS",
    "IT",
    "NO",
    "OF",
    "ON",
    "SO",
    "TO",
    "UP",
    "WE",
}


@dataclass(frozen=True)
class AdviserValidationResult:
    valid: bool
    reasons: Tuple[str, ...]
    safety_flags: Tuple[str, ...]


def _string_list(value: Any, *, max_items: int = MAX_LIST_ITEMS) -> Tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    items = [str(item).strip() for item in value[:max_items] if str(item).strip()]
    return tuple(items)


def parse_structured_response(
    raw_content: str,
    *,
    model_name: str,
    generated_at: str,
) -> AdviserResponse:
    if not raw_content or not raw_content.strip():
        raise ValueError("empty_response")
    try:
        payload = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid_json") from exc
    if isinstance(payload, list):
        raise ValueError("invalid_shape_array")
    if not isinstance(payload, dict):
        raise ValueError("invalid_shape")
    answer_raw = payload.get("answer")
    if isinstance(answer_raw, dict):
        raise ValueError("invalid_answer_type")
    answer = str(answer_raw or "").strip()
    if not answer:
        raise ValueError("missing_answer")
    if len(answer) > MAX_ANSWER_LENGTH:
        raise ValueError("answer_too_long")

    finding_ids = _dedupe_preserve_order(_string_list(payload.get("referenced_finding_ids")))
    if len(_string_list(payload.get("referenced_finding_ids"))) != len(finding_ids):
        raise ValueError("duplicate_finding_ids")

    return AdviserResponse(
        answer=answer,
        key_points=_string_list(payload.get("key_points")),
        referenced_finding_ids=finding_ids,
        limitations=_string_list(payload.get("limitations")),
        follow_up_questions=_string_list(payload.get("follow_up_questions")),
        safety_flags=(),
        model_name=model_name,
        generated_at=generated_at,
        grounded=False,
        acknowledged_preferences=_string_list(payload.get("acknowledged_preferences")),
        relevant_goal_ids=_dedupe_preserve_order(_string_list(payload.get("relevant_goal_ids"))),
        preference_assessment_ids=_dedupe_preserve_order(
            _string_list(payload.get("preference_assessment_ids"))
        ),
        options_to_consider=_string_list(payload.get("options_to_consider"), max_items=10),
    )


def _dedupe_preserve_order(items: Sequence[str]) -> Tuple[str, ...]:
    seen: Set[str] = set()
    ordered: List[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return tuple(ordered)


def known_finding_ids(context: AdviserContext) -> Set[str]:
    return {finding.finding_id for finding in context.findings}


def known_symbols(context: AdviserContext) -> Set[str]:
    symbols: Set[str] = set()
    for finding in context.findings:
        symbols.update(symbol.upper() for symbol in finding.affected_symbols if symbol)
    return symbols


def collect_grounded_numeric_values(context: AdviserContext) -> Set[float]:
    facts = context.portfolio
    values = [
        facts.priced_market_value,
        facts.total_cost_basis,
        facts.unrealized_pl,
        facts.cash_pct,
        facts.invested_pct,
        facts.largest_position_pct,
        facts.top3_concentration_pct,
        facts.largest_asset_class_pct,
        facts.priced_position_coverage_pct,
    ]
    optional = [
        facts.linked_return_pct,
        facts.benchmark_return_pct,
        facts.relative_return_pct,
    ]
    grounded: Set[float] = set()
    for value in values + [item for item in optional if item is not None]:
        rounded = round(float(value), 4)
        grounded.add(rounded)
        grounded.add(round(abs(rounded), 4))
    for finding in context.findings:
        if finding.evidence:
            for raw in finding.evidence.values():
                if isinstance(raw, (int, float)):
                    rounded = round(float(raw), 4)
                    grounded.add(rounded)
                    grounded.add(round(abs(rounded), 4))
    return grounded


def _parse_number(raw: str) -> Optional[float]:
    normalized = raw.strip().replace(" ", "")
    if "," in normalized and "." in normalized:
        normalized = normalized.replace(".", "").replace(",", ".")
    elif "," in normalized:
        normalized = normalized.replace(",", ".")
    try:
        return float(normalized)
    except ValueError:
        return None


def numeric_matches_grounded(value: float, grounded: Set[float]) -> bool:
    for candidate in grounded:
        if abs(value - candidate) <= NUMERIC_ABSOLUTE_TOLERANCE:
            return True
        if candidate != 0 and abs((value - candidate) / candidate) <= NUMERIC_RELATIVE_TOLERANCE:
            return True
    return False


def extract_percent_values(text: str) -> List[float]:
    values: List[float] = []
    for pattern in (PERCENT_SUFFIX_PATTERN, PERCENT_PREFIX_PATTERN, SIGNED_PERCENT_PATTERN):
        for match in pattern.finditer(text):
            parsed = _parse_number(match.group(1))
            if parsed is not None:
                values.append(abs(parsed))
    return values


def extract_currency_values(text: str) -> List[float]:
    values: List[float] = []
    for match in CURRENCY_PATTERN.finditer(text):
        raw = match.group(1) or match.group(2)
        if raw is None:
            continue
        parsed = _parse_number(raw)
        if parsed is not None:
            values.append(parsed)
    return values


def extract_suspicious_numbers(text: str, grounded: Set[float]) -> List[float]:
    suspicious: List[float] = []
    for value in extract_percent_values(text):
        if value >= MIN_VALIDATED_PERCENT and not numeric_matches_grounded(value, grounded):
            suspicious.append(value)
    for value in extract_currency_values(text):
        if value >= MIN_VALIDATED_CURRENCY and not numeric_matches_grounded(value, grounded):
            suspicious.append(value)
    return suspicious


def extract_invented_holding_symbols(text: str, known: Set[str]) -> List[str]:
    invented: List[str] = []
    for match in HOLDING_CLAIM_PATTERN.finditer(text):
        symbol = match.group(1).upper()
        if symbol in ALLOWED_SYMBOLS:
            continue
        if symbol in known:
            continue
        if symbol not in invented:
            invented.append(symbol)
    return invented


def _is_negated(text: str, start: int) -> bool:
    window = text[max(0, start - 48):start].lower()
    return any(marker in window for marker in NEGATION_MARKERS)


def _pattern_matches_unnegated(text: str, pattern: re.Pattern[str]) -> bool:
    for match in pattern.finditer(text):
        if _is_negated(text, match.start()):
            continue
        return True
    return False


def sanitize_failure_reasons(reasons: Sequence[str]) -> Tuple[str, ...]:
    sanitized: List[str] = []
    for reason in reasons:
        lowered = reason.lower()
        if any(
            token in lowered
            for token in ("authorization", "bearer", "api_key", "apikey", "secret", "<html")
        ):
            sanitized.append("provider_error")
            continue
        if len(reason) > 120:
            sanitized.append(reason.split(":", 1)[0] if ":" in reason else "validation_failed")
            continue
        sanitized.append(reason)
    return tuple(dict.fromkeys(sanitized))


def _combined_text(response: AdviserResponse) -> str:
    parts = [
        response.answer,
        *response.key_points,
        *response.limitations,
        *response.follow_up_questions,
    ]
    return "\n".join(parts)


def validate_adviser_response(
    response: AdviserResponse,
    context: AdviserContext,
    *,
    validation_context: Optional[AdviserValidationContext] = None,
) -> AdviserValidationResult:
    reasons: List[str] = []
    safety_flags: List[str] = []
    text = _combined_text(response)
    lowered = text.lower()
    validation_context = validation_context or AdviserValidationContext.from_user_context(
        context.user_context
    )

    valid_ids = known_finding_ids(context)
    for finding_id in response.referenced_finding_ids:
        if finding_id not in valid_ids:
            reasons.append(f"unknown_finding_id:{finding_id}")
            safety_flags.append("unknown_finding_reference")

    symbols = known_symbols(context)
    invented = extract_invented_holding_symbols(text, symbols)
    if invented:
        reasons.append(f"unknown_symbols:{','.join(invented)}")
        safety_flags.append("unknown_symbol_reference")

    grounded_numbers = collect_grounded_numeric_values(context)
    suspicious_numbers = extract_suspicious_numbers(text, grounded_numbers)
    if suspicious_numbers:
        reasons.append(f"unsupported_numeric_claims:{suspicious_numbers[:3]}")
        safety_flags.append("unsupported_numeric_claim")

    for pattern in BUY_SELL_PATTERNS:
        if _pattern_matches_unnegated(text, pattern):
            reasons.append("explicit_transaction_command")
            safety_flags.append("transaction_command")
            break

    for pattern in REBALANCE_PATTERNS:
        if _pattern_matches_unnegated(text, pattern):
            reasons.append("exact_rebalance_instruction")
            safety_flags.append("rebalance_instruction")
            break

    for pattern in SPECIFIC_SECURITY_REC_PATTERNS:
        if _pattern_matches_unnegated(text, pattern):
            reasons.append("specific_security_recommendation")
            safety_flags.append("specific_security_recommendation")
            break

    for pattern in PROFILE_OVERRIDE_PATTERNS:
        if pattern.search(text):
            reasons.append("profile_overrides_financial_fact")
            safety_flags.append("profile_fact_override")
            break

    for goal_id in response.relevant_goal_ids:
        if goal_id not in validation_context.known_goal_ids:
            reasons.append(f"unknown_goal_id:{goal_id}")
            safety_flags.append("unknown_goal_reference")

    for assessment_id in response.preference_assessment_ids:
        if assessment_id not in validation_context.known_assessment_ids:
            reasons.append(f"unknown_assessment_id:{assessment_id}")
            safety_flags.append("unknown_assessment_reference")

    for pref in response.acknowledged_preferences:
        pref_lower = pref.lower()
        if validation_context.known_profile_values:
            if not any(value.lower() in pref_lower for value in validation_context.known_profile_values):
                reasons.append("invented_profile_reference")
                safety_flags.append("invented_profile")
                break

    for pattern in FUTURE_CERTAINTY_PATTERNS:
        if _pattern_matches_unnegated(text, pattern):
            reasons.append("future_certainty_language")
            safety_flags.append("future_certainty")
            break

    for pattern in FIDUCIARY_PATTERNS:
        if pattern.search(text):
            reasons.append("fiduciary_claim")
            safety_flags.append("fiduciary_claim")
            break

    for marker in PROMPT_LEAK_MARKERS:
        if marker in lowered:
            reasons.append("system_prompt_leakage")
            safety_flags.append("prompt_leakage")
            break

    if _pattern_matches_unnegated(text, re.compile(r"\bsystem prompt\b", re.IGNORECASE)):
        reasons.append("system_prompt_leakage")
        safety_flags.append("prompt_leakage")

    for pattern in NABI_INVENTION_PATTERNS:
        if pattern.search(text):
            reasons.append("invented_nabi_claim")
            safety_flags.append("nabi_invention")
            break

    for pattern in FINANCIAL_SEMANTIC_PATTERNS:
        if pattern.search(text):
            reasons.append("financial_semantic_violation")
            safety_flags.append("financial_semantic_violation")
            break

    if context.portfolio.benchmark_available is False and re.search(
        r"\bbenchmark\b[^.\n]{0,40}\b(?:is\s+)?(?:available|mevcut|outperform|underperform)\b(?!\s*değil|\s*degil|\s*not)",
        lowered,
    ):
        reasons.append("benchmark_availability_mismatch")
        safety_flags.append("benchmark_availability_mismatch")

    if context.portfolio.performance_comparable is False and re.search(
        r"\b(?:comparable|karşılaştırılabilir|karsilastirilabilir)\s+performance\b(?!\s*(?:değil|degil|not))",
        lowered,
    ):
        reasons.append("performance_comparability_mismatch")
        safety_flags.append("performance_comparability_mismatch")

    return AdviserValidationResult(
        valid=not reasons,
        reasons=tuple(dict.fromkeys(reasons)),
        safety_flags=tuple(dict.fromkeys(safety_flags)),
    )
