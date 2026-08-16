from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Sequence, Tuple

from services.decision_learning_engine import contains_psychological_inference
from services.portfolio_ai_adviser_contract import PortfolioAIAdviserResponse
from services.wealth_adviser_output_validator import (
    BUY_SELL_PATTERNS,
    FIDUCIARY_PATTERNS,
    REBALANCE_PATTERNS,
    _is_negated,
    _pattern_matches_unnegated,
)

TARGET_PRICE_PATTERNS = (
    re.compile(r"\bhedef fiyat\b", re.IGNORECASE),
    re.compile(r"\btarget price\b", re.IGNORECASE),
    re.compile(r"\b\d+\s*(usd|tl|try)\s*hedef\b", re.IGNORECASE),
)

BEHAVIORAL_PATTERNS = (
    re.compile(r"\b(fomo|fear|greed|panik|korku|açgözlülük)\b", re.IGNORECASE),
)

FORECAST_PATTERNS = (
    re.compile(r"\b(VaR|value at risk)\b"),
    re.compile(r"\b\d+\s*%\s*(olasılık|probability|ihtimal)\b", re.IGNORECASE),
    re.compile(r"\bkorelasyon\b", re.IGNORECASE),
    re.compile(r"\bcorrelation\b", re.IGNORECASE),
)

INVESTOR_RANK_PATTERNS = (
    re.compile(r"\b(iyi|kötü|başarılı|başarısız)\s+yatırımcı\b", re.IGNORECASE),
    re.compile(r"\binvestor score\b", re.IGNORECASE),
    re.compile(r"\b\d+\s*/\s*100\b"),
)


@dataclass(frozen=True)
class PortfolioAIValidationResult:
    ok: bool
    response: PortfolioAIAdviserResponse
    issues: Tuple[str, ...]


def _string_list(value: Any, *, max_items: int = 8) -> Tuple[str, ...]:
    if not value:
        return ()
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    items = [str(item).strip() for item in value if str(item).strip()]
    return tuple(items[:max_items])


def _contains_trade_instruction(text: str) -> bool:
    for pattern in (*BUY_SELL_PATTERNS, *REBALANCE_PATTERNS, *FIDUCIARY_PATTERNS):
        if _pattern_matches_unnegated(text, pattern):
            return True
    return False


def _contains_target_price(text: str) -> bool:
    return any(pattern.search(text) for pattern in TARGET_PRICE_PATTERNS)


def _participation_override(text: str) -> bool:
    lowered = text.lower()
    return "kontrol et" in lowered and ("uygun" in lowered and "uygun değil" not in lowered)


def _unsupported_risk_metric_claim(text: str, context_payload: Mapping[str, Any]) -> bool:
    context_blob = json.dumps(context_payload, ensure_ascii=False).lower()
    disclaimer_after = (
        "yok",
        "değil",
        "hesaplanmad",
        "üretilmedi",
        "iddiası",
        "forbidden",
        "not forecast",
    )
    for pattern in FORECAST_PATTERNS:
        for match in pattern.finditer(text):
            token = match.group(0).lower()
            if token and token in context_blob:
                continue
            if _is_negated(text, match.start()):
                continue
            after = text[match.end(): match.end() + 48].lower()
            if any(marker in after for marker in disclaimer_after):
                continue
            return True
    return False


def validate_portfolio_ai_response(
    *,
    portfolio_id: str,
    raw_payload: Mapping[str, Any],
    context_payload: Mapping[str, Any],
) -> PortfolioAIValidationResult:
    issues: list[str] = []
    fields = {
        "executive_summary": str(raw_payload.get("executive_summary") or ""),
        "what_changed": _string_list(raw_payload.get("what_changed")),
        "portfolio_implications": _string_list(raw_payload.get("portfolio_implications")),
        "thesis_watch": _string_list(raw_payload.get("thesis_watch")),
        "participation_watch": _string_list(raw_payload.get("participation_watch")),
        "research_gaps": _string_list(raw_payload.get("research_gaps")),
        "questions_to_review": _string_list(raw_payload.get("questions_to_review")),
        "limitations": _string_list(raw_payload.get("limitations")),
        "evidence_references": _string_list(raw_payload.get("evidence_references")),
    }
    all_text = " ".join(
        [fields["executive_summary"]]
        + [item for values in fields.values() if isinstance(values, tuple) for item in values]
    )
    if _contains_trade_instruction(all_text):
        issues.append("trade_instruction")
    if _contains_target_price(all_text):
        issues.append("target_price")
    if _participation_override(all_text):
        issues.append("participation_override")
    if contains_psychological_inference(all_text) or any(
        pattern.search(all_text) for pattern in BEHAVIORAL_PATTERNS
    ):
        issues.append("behavioral_inference")
    if _unsupported_risk_metric_claim(all_text, context_payload):
        issues.append("unsupported_risk_metric")
    if any(pattern.search(all_text) for pattern in INVESTOR_RANK_PATTERNS):
        issues.append("investor_ranking")

    context_blob = json.dumps(context_payload, ensure_ascii=False).lower()
    if "decision_review" in context_payload:
        for outcome_token in ("+%", "kazanç garanti", "guaranteed return"):
            if outcome_token in all_text.lower() and outcome_token not in context_blob:
                issues.append("fabricated_outcome")
                break
    for metric_token in ("%20", "yüzde 20", "20% revenue", "gelir %20"):
        if metric_token in all_text.lower() and metric_token not in context_blob:
            issues.append("unsupported_metric_claim")
            break

    if issues:
        return PortfolioAIValidationResult(
            ok=False,
            response=PortfolioAIAdviserResponse.validation_failed(
                portfolio_id=portfolio_id,
                message="AI portföy yanıtı doğrulamadan geçemedi.",
            ),
            issues=tuple(issues),
        )

    return PortfolioAIValidationResult(
        ok=True,
        response=PortfolioAIAdviserResponse(
            portfolio_id=portfolio_id,
            status="AVAILABLE",
            evidence_level=str(raw_payload.get("evidence_level") or "MEDIUM"),
            executive_summary=fields["executive_summary"],
            what_changed=fields["what_changed"],
            portfolio_implications=fields["portfolio_implications"],
            thesis_watch=fields["thesis_watch"],
            participation_watch=fields["participation_watch"],
            research_gaps=fields["research_gaps"],
            questions_to_review=fields["questions_to_review"],
            limitations=fields["limitations"] or ("Bağlam sınırları geçerlidir.",),
            evidence_references=fields["evidence_references"],
        ),
        issues=(),
    )
