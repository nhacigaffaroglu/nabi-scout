from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from services.ai_research_summary_contract import EVIDENCE_LEVELS
from services.wealth_adviser_output_validator import (
    BUY_SELL_PATTERNS,
    FIDUCIARY_PATTERNS,
    FUTURE_CERTAINTY_PATTERNS,
    NEGATION_MARKERS,
    PROMPT_LEAK_MARKERS,
    REBALANCE_PATTERNS,
    _pattern_matches_unnegated,
)

MAX_SECTION_LENGTH = 2000
MAX_LIST_ITEMS = 8

# Uppercase tokens that resemble tickers but are financial / research vocabulary.
# Deliberately excludes real ticker symbols (MSFT, AAPL, etc.).
RESEARCH_DOMAIN_ACRONYMS = frozenset(
    {
        "AI",
        "AND",
        "API",
        "CAGR",
        "CF",
        "DATA",
        "EBIT",
        "EBITDA",
        "EPS",
        "EUR",
        "EV",
        "FCF",
        "FMP",
        "FOR",
        "FY",
        "GAAP",
        "HIGH",
        "IB",
        "IFRS",
        "LIMITED",
        "LLM",
        "LOW",
        "MEDIUM",
        "MIXED",
        "MODERATE",
        "MSCI",
        "NABI",
        "NASDAQ",
        "NOT",
        "NYSE",
        "OCF",
        "PE",
        "PEG",
        "PS",
        "ROIC",
        "SEC",
        "SIC",
        "STRONG",
        "THE",
        "TRY",
        "TTM",
        "USD",
        "YOY",
    }
)

_TICKER_LIKE_TOKEN_PATTERN = re.compile(r"\b([A-Z]{2,5})\b")

VALUATION_DISCLAIMER_MARKERS = (
    "göreceli çekicilik",
    "kanıt sınırlı",
    "tarihsel ve benzer",
    "karşılaştırması olmadığı",
    "değerlendirilemez",
    "yapılmamalı",
    "yorumlanamaz",
    "yorumu yapılamaz",
)


VALUATION_ATTRACTIVENESS_PATTERNS = (
    re.compile(r"\bucuz\b", re.IGNORECASE),
    re.compile(r"\bpahalı\b", re.IGNORECASE),
    re.compile(r"\biskontolu\b", re.IGNORECASE),
    re.compile(r"\başırı değerli\b", re.IGNORECASE),
    re.compile(r"\bcazip değerleme\b", re.IGNORECASE),
    re.compile(r"\bcheap\b", re.IGNORECASE),
    re.compile(r"\bexpensive\b", re.IGNORECASE),
    re.compile(r"\bovervalued\b", re.IGNORECASE),
    re.compile(r"\bundervalued\b", re.IGNORECASE),
)


def _valuation_attractiveness_violation(text: str) -> bool:
    lowered = text.lower()
    for pattern in VALUATION_ATTRACTIVENESS_PATTERNS:
        for match in pattern.finditer(text):
            window = lowered[max(0, match.start() - 90): min(len(lowered), match.end() + 40)]
            if _pattern_matches_unnegated(text, pattern):
                if any(marker in window for marker in VALUATION_DISCLAIMER_MARKERS):
                    continue
                return True
    return False

TARGET_PRICE_PATTERNS = (
    re.compile(r"\bhedef fiyat\b", re.IGNORECASE),
    re.compile(r"\btarget price\b", re.IGNORECASE),
    re.compile(r"\badil değer\b", re.IGNORECASE),
    re.compile(r"\bfair value\b", re.IGNORECASE),
)

PARTICIPATION_ENDORSEMENT_PATTERNS = (
    re.compile(
        r"\b(?:uygun olduğu için|katılım açısından uygun olduğu için).{0,40}\b(?:iyi yatırım|alınabilir|alınmalı)\b",
        re.IGNORECASE,
    ),
)

CONFIDENCE_INFLATION_PATTERNS = (
    re.compile(r"\bgüçlü yatırım tezi\b", re.IGNORECASE),
    re.compile(r"\b(?:yatırım )?tezi güçlü\b", re.IGNORECASE),
    re.compile(r"\btez(?:in|i)? güçlü\b", re.IGNORECASE),
    re.compile(r"\btez güveni yüksek\b", re.IGNORECASE),
    re.compile(r"\btez yüksek güven(?:le|ilir)?\b", re.IGNORECASE),
    re.compile(r"\byüksek güven(?:ilir)?(?:lik)?(?:le)?\b", re.IGNORECASE),
    re.compile(r"\bkanıt düzeyi güçlü\b", re.IGNORECASE),
    re.compile(r"\b(?:kanıt|tez) (?:açısından )?güçlü\b", re.IGNORECASE),
    re.compile(r"\bhigh confidence thesis\b", re.IGNORECASE),
    re.compile(r"\boverall thesis confidence is high\b", re.IGNORECASE),
)

CONFIDENCE_INFLATION_POST_NEGATION_MARKERS = (
    " yok",
    " değil",
    " degil",
    "muyor",
    "miyor",
    "amaz",
    "emez",
    "ulamaz",
    "ulamıyor",
    "yetmiyor",
    "yetmez",
    "yetersiz",
    "yetersizdir",
    "oluşmuyor",
    "oluşturulam",
    "oluşturamaz",
    "söylenemez",
    "duyulamaz",
    "yorumlanamaz",
    "edilemez",
    "yapılamaz",
    "kurulamaz",
    "kurulmuyor",
    "desteklenmiyor",
)

THESIS_CONFIDENCE_SCOPE_MARKERS = (
    "yatırım tezi",
    " tez ",
    " tez.",
    " tez,",
    "tezi ",
    "tezde ",
    "tez güven",
    "değerlendirme",
    "araştırma güven",
    "genel güven",
    "kanıt düzeyi",
    "overall thesis",
)

METRIC_CONFIDENCE_SCOPE_MARKERS = (
    "veri güveni",
    "destekleyen veri",
    "sinyal",
    "gözlem",
    "gösterge",
    "metrik",
    "tespit edildi",
    "tespit edilmiş",
    "değişim",
    "trend",
    "gelir",
    "fcf",
    "nakit",
    "sec ",
    "yıllık veri",
    "finansal gözlem",
)

THESIS_INSUFFICIENCY_AFTER_MARKERS = (
    "yetersiz",
    "yetmiyor",
    "yetmez",
    "oluşturulam",
    "kurulamaz",
    "desteklenmiyor",
    "söylenemez",
    "duyulamaz",
)

METRIC_STRENGTH_ALLOWLIST_PATTERNS = (
    re.compile(r"\bgüçlü yönler\b", re.IGNORECASE),
    re.compile(
        r"\b(?:gelir|nakit|fcf|faaliyet|serbest nakit|marj|büyüme|roic|eps|ebit|ebitda|sermaye|finansal görünüm|operasyonel|sinyal)\b[^.\n]{0,28}\bgüçlü\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bgüçlü\b[^.\n]{0,20}\b(?:fcf|fcf marj|nakit|gelir|büyüme|sermaye|faaliyet|sinyal|artış)\b",
        re.IGNORECASE,
    ),
)

NEWS_ABSENCE_INFERENCE_PATTERNS = (
    re.compile(r"\bolumsuz haber bulunmuyor\b", re.IGNORECASE),
    re.compile(r"\bnegative news (?:not found|none)\b", re.IGNORECASE),
    re.compile(r"\bolumsuz gelişme yok\b", re.IGNORECASE),
)


@dataclass(frozen=True)
class AIResearchSummaryConstraints:
    symbol: str
    participation_status: Optional[str]
    thesis_status: Optional[str]
    thesis_confidence: Optional[str]
    evidence_level: str
    earnings_available: bool
    news_available: bool
    peers_available: bool
    historical_valuation_available: bool
    allowed_symbols: Tuple[str, ...] = ()
    context_uppercase_tokens: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ParsedAIResearchSummary:
    financial_outlook: str
    valuation_summary: str
    key_strengths: Tuple[str, ...]
    key_weaknesses: Tuple[str, ...]
    risks_to_watch: Tuple[str, ...]
    missing_evidence: Tuple[str, ...]
    monitoring_points: Tuple[str, ...]
    limitations: Tuple[str, ...]
    evidence_level: str


@dataclass(frozen=True)
class AIResearchSummaryValidationResult:
    valid: bool
    reasons: Tuple[str, ...] = ()
    safety_flags: Tuple[str, ...] = ()


def _string_list(value: Any, *, max_items: int = MAX_LIST_ITEMS) -> List[str]:
    if not isinstance(value, list):
        return []
    items: List[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            items.append(text)
        if len(items) >= max_items:
            break
    return items


def _section_text(value: Any) -> str:
    text = str(value or "").strip()
    return text[:MAX_SECTION_LENGTH]


def _normalize_json_content(raw_content: str) -> str:
    text = str(raw_content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def parse_ai_summary_response(raw_content: str) -> ParsedAIResearchSummary:
    if not raw_content or not raw_content.strip():
        raise ValueError("empty_response")
    payload = json.loads(_normalize_json_content(raw_content))
    if not isinstance(payload, dict):
        raise ValueError("invalid_shape")
    evidence_level = str(payload.get("evidence_level") or "").strip().upper()
    if evidence_level not in EVIDENCE_LEVELS:
        raise ValueError("invalid_evidence_level")
    return ParsedAIResearchSummary(
        financial_outlook=_section_text(payload.get("financial_outlook")),
        valuation_summary=_section_text(payload.get("valuation_summary")),
        key_strengths=tuple(_string_list(payload.get("key_strengths"))),
        key_weaknesses=tuple(_string_list(payload.get("key_weaknesses"))),
        risks_to_watch=tuple(_string_list(payload.get("risks_to_watch"))),
        missing_evidence=tuple(_string_list(payload.get("missing_evidence"))),
        monitoring_points=tuple(_string_list(payload.get("monitoring_points"))),
        limitations=tuple(_string_list(payload.get("limitations"))),
        evidence_level=evidence_level,
    )


def _combined_text(summary: ParsedAIResearchSummary) -> str:
    parts = [
        summary.financial_outlook,
        summary.valuation_summary,
        *summary.key_strengths,
        *summary.key_weaknesses,
        *summary.risks_to_watch,
        *summary.missing_evidence,
        *summary.monitoring_points,
        *summary.limitations,
    ]
    return "\n".join(part for part in parts if part)


def extract_context_uppercase_tokens(context: Any) -> Tuple[str, ...]:
    if context is None:
        return ()
    if isinstance(context, str):
        serialized = context
    else:
        serialized = json.dumps(context, ensure_ascii=False, default=str)
    tokens = {
        match.group(1).upper()
        for match in _TICKER_LIKE_TOKEN_PATTERN.finditer(serialized)
    }
    return tuple(sorted(tokens))


def _permitted_uppercase_tokens(constraints: AIResearchSummaryConstraints) -> set[str]:
    permitted = {symbol.upper() for symbol in constraints.allowed_symbols if symbol}
    permitted.update(RESEARCH_DOMAIN_ACRONYMS)
    permitted.update(token.upper() for token in constraints.context_uppercase_tokens if token)
    return permitted


def _extract_symbols(text: str, *, permitted_tokens: set[str]) -> set[str]:
    return {
        match.group(1).upper()
        for match in _TICKER_LIKE_TOKEN_PATTERN.finditer(text)
        if match.group(1).upper() not in permitted_tokens
    }


def _is_confidence_claim_locally_negated(text: str, start: int, end: int) -> bool:
    before = text[max(0, start - 48):start].lower()
    after = text[end:min(len(text), end + 56)].lower()
    if any(marker in before for marker in NEGATION_MARKERS):
        return True
    return any(marker in after for marker in CONFIDENCE_INFLATION_POST_NEGATION_MARKERS)


def _match_is_metric_strength_allowlisted(text: str, match: re.Match[str]) -> bool:
    window = text[max(0, match.start() - 32):min(len(text), match.end() + 32)]
    return any(pattern.search(window) for pattern in METRIC_STRENGTH_ALLOWLIST_PATTERNS)


def _match_is_high_confidence_pattern(match: re.Match[str]) -> bool:
    return bool(
        re.search(
            r"\\byüksek güven",
            match.re.pattern,
            flags=re.IGNORECASE,
        )
    )


def _match_is_metric_confidence_allowlisted(text: str, match: re.Match[str]) -> bool:
    """Metric/signal-scoped 'yüksek güven' is not thesis-confidence inflation."""
    if not _match_is_high_confidence_pattern(match):
        return False
    window = text[max(0, match.start() - 80):min(len(text), match.end() + 32)].lower()
    if any(marker in window for marker in THESIS_CONFIDENCE_SCOPE_MARKERS):
        return False
    return any(marker in window for marker in METRIC_CONFIDENCE_SCOPE_MARKERS)


def _match_is_thesis_insufficiency_allowlisted(text: str, match: re.Match[str]) -> bool:
    """'Güçlü yatırım tezi ... yetersiz/yetmiyor' states insufficiency, not inflation."""
    if "güçlü yatırım tezi" not in match.group(0).lower():
        if not re.search(r"güçlü yatırım tezi", match.re.pattern, flags=re.IGNORECASE):
            return False
    window = text[match.start():min(len(text), match.end() + 72)].lower()
    return any(marker in window for marker in THESIS_INSUFFICIENCY_AFTER_MARKERS)


def _inflation_match_is_allowlisted(text: str, match: re.Match[str]) -> bool:
    if _is_confidence_claim_locally_negated(text, match.start(), match.end()):
        return True
    if _match_is_metric_strength_allowlisted(text, match):
        return True
    if _match_is_metric_confidence_allowlisted(text, match):
        return True
    if _match_is_thesis_insufficiency_allowlisted(text, match):
        return True
    return False


def _thesis_confidence_inflation_violation(text: str) -> bool:
    return bool(explain_thesis_confidence_inflation_violations(text))


def explain_thesis_confidence_inflation_violations(text: str) -> Tuple[dict[str, Any], ...]:
    """Return structured match details for thesis_confidence_inflation diagnostics."""
    matches: list[dict[str, Any]] = []
    for pattern in CONFIDENCE_INFLATION_PATTERNS:
        for match in pattern.finditer(text):
            if _inflation_match_is_allowlisted(text, match):
                continue
            start = max(0, match.start() - 80)
            end = min(len(text), match.end() + 80)
            matches.append(
                {
                    "pattern": pattern.pattern,
                    "matched_substring": match.group(0),
                    "context_window": text[start:end],
                    "negated": _is_confidence_claim_locally_negated(
                        text, match.start(), match.end()
                    ),
                    "metric_allowlisted": _match_is_metric_strength_allowlisted(text, match)
                    or _match_is_metric_confidence_allowlisted(text, match)
                    or _match_is_thesis_insufficiency_allowlisted(text, match),
                }
            )
    return tuple(matches)


def _summary_field_texts(summary: ParsedAIResearchSummary) -> Tuple[Tuple[str, str], ...]:
    return (
        ("financial_outlook", summary.financial_outlook),
        ("valuation_summary", summary.valuation_summary),
        *(("key_strengths", item) for item in summary.key_strengths),
        *(("key_weaknesses", item) for item in summary.key_weaknesses),
        *(("risks_to_watch", item) for item in summary.risks_to_watch),
        *(("missing_evidence", item) for item in summary.missing_evidence),
        *(("monitoring_points", item) for item in summary.monitoring_points),
        *(("limitations", item) for item in summary.limitations),
    )


def explain_thesis_confidence_inflation_for_summary(
    summary: ParsedAIResearchSummary,
) -> Tuple[dict[str, Any], ...]:
    """Field-aware thesis confidence inflation diagnostics."""
    findings: list[dict[str, Any]] = []
    for field_name, field_text in _summary_field_texts(summary):
        if not field_text:
            continue
        for match in explain_thesis_confidence_inflation_violations(field_text):
            findings.append({"field": field_name, "field_text": field_text, **match})
    return tuple(findings)


def validate_ai_research_summary(
    summary: ParsedAIResearchSummary,
    constraints: AIResearchSummaryConstraints,
) -> AIResearchSummaryValidationResult:
    reasons: List[str] = []
    safety_flags: List[str] = []
    text = _combined_text(summary)
    lowered = text.lower()

    if summary.evidence_level != constraints.evidence_level:
        reasons.append("evidence_level_mismatch")
        safety_flags.append("evidence_level_mismatch")

    permitted_tokens = _permitted_uppercase_tokens(constraints)
    for symbol in _extract_symbols(text, permitted_tokens=permitted_tokens):
        reasons.append(f"unsupported_symbol:{symbol}")
        safety_flags.append("unsupported_symbol")
        break

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

    if not constraints.historical_valuation_available:
        if _valuation_attractiveness_violation(text):
            reasons.append("unsupported_valuation_attractiveness")
            safety_flags.append("valuation_attractiveness")

    for pattern in TARGET_PRICE_PATTERNS:
        if _pattern_matches_unnegated(text, pattern):
            reasons.append("target_price_claim")
            safety_flags.append("target_price")
            break

    for pattern in PARTICIPATION_ENDORSEMENT_PATTERNS:
        if pattern.search(text):
            reasons.append("participation_endorsement")
            safety_flags.append("participation_endorsement")
            break

    if constraints.thesis_status == "INSUFFICIENT_DATA" or constraints.thesis_confidence == "LOW":
        if explain_thesis_confidence_inflation_for_summary(summary):
            reasons.append("thesis_confidence_inflation")
            safety_flags.append("thesis_confidence_inflation")

    if not constraints.news_available:
        for pattern in NEWS_ABSENCE_INFERENCE_PATTERNS:
            if pattern.search(text):
                reasons.append("news_absence_inference")
                safety_flags.append("news_absence_inference")
                break

    if constraints.participation_status:
        wrong_status_patterns = (
            re.compile(r"\buygun değil\b", re.IGNORECASE),
            re.compile(r"\bkontrol et\b", re.IGNORECASE),
        )
        for pattern in wrong_status_patterns:
            if pattern.search(text):
                reasons.append("participation_status_mismatch")
                safety_flags.append("participation_status_mismatch")
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

    return AIResearchSummaryValidationResult(
        valid=not reasons,
        reasons=tuple(dict.fromkeys(reasons)),
        safety_flags=tuple(dict.fromkeys(safety_flags)),
    )
