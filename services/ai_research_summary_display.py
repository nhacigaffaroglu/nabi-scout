from __future__ import annotations

import re
from typing import Iterable, Optional, Tuple

from services.ai_research_summary_contract import AIResearchSummaryView
from services.ai_research_summary_valuation_semantics import (
    ValuationSemantics,
    authoritative_valuation_summary,
    derive_valuation_semantics,
    valuation_semantics_from_snapshot,
)
from services.unified_research_contract import UnifiedResearchContext

_INTERNAL_ENUM_PATTERN = re.compile(
    r"\b(?:VALUATION|EARNINGS|PARTICIPATION|THESIS|NEWS|PEER|CATALYST|DATA|EVIDENCE)_[A-Z0-9_]+\b"
)
_PAREN_ENUM_PATTERN = re.compile(
    r"\s*\(\s*(?:VALUATION|EARNINGS|PARTICIPATION|THESIS|NEWS|PEER|CATALYST|DATA|EVIDENCE)_[A-Z0-9_]+\s*\)",
    re.IGNORECASE,
)
_MISLEADING_NO_VALUATION_MARKERS = (
    "değerleme verisi yok",
    "değerleme oranları yok",
    "değerleme oranı yok",
    "değerleme oranları hesaplanam",
    "değerleme oranı hesaplanam",
    "mevcut değerleme oranları hesaplanam",
    "mevcut oran bulunmuyor",
    "oran bulunmuyor",
    "oranlar mevcut değil",
    "valuation data unavailable",
    "valuation unavailable",
    "valuation_unavailable",
    "ratios unavailable",
)

_PAREN_OBSERVATION_PATTERN = re.compile(
    r"\(\s*(IMPROVING|DECLINING|STABLE|FLAT)\s*,\s*(HIGH|MEDIUM|LOW)\s*confidence\s*\)",
    re.IGNORECASE,
)
_STANDALONE_METRIC_CONFIDENCE_PATTERN = re.compile(
    r"\b(HIGH|MEDIUM|LOW)\s+confidence\b",
    re.IGNORECASE,
)
_TECHNICAL_IDENTIFIER_REPLACEMENTS = (
    (re.compile(r"\bAUTHORITATIVE_RESEARCH_CONTEXT\b", re.IGNORECASE), "mevcut doğrulanmış NABI araştırma verileri"),
    (re.compile(r"\bAUTHORITATIVE_CONSTRAINTS\b", re.IGNORECASE), "mevcut araştırma sınırlamaları"),
    (re.compile(r"\bAUTHORITATIVE_EVIDENCE_LEVEL\b", re.IGNORECASE), "kanıt düzeyi"),
)
_CONTEXT_CODE_REPLACEMENTS = (
    (re.compile(r"\bINSUFFICIENT_DATA\b"), "kanıt yetersiz"),
    (re.compile(r"\bVALUATION_UNAVAILABLE\b"), "tarihsel değerleme karşılaştırması mevcut değil"),
    (re.compile(r"\bEARNINGS_UNAVAILABLE\b"), "kazanç beklentisi verisi mevcut değil"),
    (re.compile(r"\bNEWS_UNAVAILABLE\b"), "haber verisi mevcut değil"),
    (re.compile(r"\bPEERS_UNAVAILABLE\b"), "benzer şirket karşılaştırması mevcut değil"),
    (re.compile(r"\bUNAVAILABLE\b"), "mevcut değil"),
)
_DIRECTION_REPLACEMENTS = (
    (re.compile(r"\bIMPROVING\b"), "artış yönünde"),
    (re.compile(r"\bDECLINING\b"), "gerileme yönünde"),
    (re.compile(r"\bSTABLE\b"), "stabil"),
    (re.compile(r"\bFLAT\b"), "stabil"),
)
_THESIS_CONFIDENCE_PHRASES = (
    (re.compile(r"\bthesis confidence\s+LOW\b", re.IGNORECASE), "yatırım tezi güven düzeyi düşük"),
    (re.compile(r"\bconfidence\s+LOW\b", re.IGNORECASE), "güven düzeyi düşük"),
    (re.compile(r"\bthesis confidence\s+HIGH\b", re.IGNORECASE), "yatırım tezi güven düzeyi yüksek"),
    (re.compile(r"\bconfidence\s+HIGH\b", re.IGNORECASE), "güven düzeyi yüksek"),
)
_LIMITATION_PHRASE_REPLACEMENTS = (
    (
        re.compile(
            r"Araştırma yalnızca AUTHORITATIVE_RESEARCH_CONTEXT[^.]*\.?",
            re.IGNORECASE,
        ),
        "Özet yalnızca mevcut doğrulanmış NABI araştırma verilerine dayanır; dış bilgi veya varsayım kullanılmamıştır.",
    ),
    (
        re.compile(
            r"Thesis durumu INSUFFICIENT_DATA[^.]*confidence LOW[^.]*\.?",
            re.IGNORECASE,
        ),
        "Yatırım tezi için mevcut kanıt yetersiz ve güven düzeyi düşüktür; AI özeti bu sınırı yükseltemez.",
    ),
    (
        re.compile(
            r"Valuation ve earnings kodları[^.]*UNAVAILABLE[^.]*\.?",
            re.IGNORECASE,
        ),
        "Tarihsel değerleme karşılaştırması ve kazanç beklentisi verileri mevcut değildir.",
    ),
)

_PROVIDER_PROSE_REPLACEMENTS = (
    (re.compile(r"\bRATE_LIMIT\b"), "veri sağlayıcı erişim sınırı"),
    (re.compile(r"\(fmp\)", re.IGNORECASE), "(veri sağlayıcı)"),
    (re.compile(r"\bfmp\b", re.IGNORECASE), "veri sağlayıcı"),
)
_MACHINE_TOKENS_FORBIDDEN_IN_PRIMARY = (
    "AUTHORITATIVE_RESEARCH_CONTEXT",
    "AUTHORITATIVE_CONSTRAINTS",
    "INSUFFICIENT_DATA",
    "VALUATION_UNAVAILABLE",
    "UNAVAILABLE",
)


def _translate_paren_observation(match: re.Match[str]) -> str:
    direction = match.group(1).upper()
    confidence = match.group(2).upper()
    direction_tr = {
        "IMPROVING": "artış yönünde",
        "DECLINING": "gerileme yönünde",
        "STABLE": "stabil seyrediyor",
        "FLAT": "stabil seyrediyor",
    }.get(direction, direction.lower())
    conf_tr = {
        "HIGH": "bu sinyalin veri güveni yüksek",
        "MEDIUM": "bu sinyalin veri güveni orta",
        "LOW": "bu sinyalin veri güveni düşük",
    }.get(confidence, confidence.lower())
    return f"({direction_tr}; {conf_tr})"


def _translate_standalone_metric_confidence(match: re.Match[str]) -> str:
    level = match.group(1).upper()
    mapping = {
        "HIGH": "bu sinyalin veri güveni yüksek",
        "MEDIUM": "bu sinyalin veri güveni orta",
        "LOW": "bu sinyalin veri güveni düşük",
    }
    return mapping.get(level, match.group(0))


def strip_internal_enum_labels(text: str) -> str:
    cleaned = _PAREN_ENUM_PATTERN.sub("", str(text or ""))
    cleaned = _INTERNAL_ENUM_PATTERN.sub("", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip(" ,.;")


def polish_user_facing_text(text: str, *, section: str = "general") -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return cleaned

    if section == "limitations":
        for pattern, replacement in _LIMITATION_PHRASE_REPLACEMENTS:
            cleaned = pattern.sub(replacement, cleaned)

    cleaned = _PAREN_OBSERVATION_PATTERN.sub(_translate_paren_observation, cleaned)
    cleaned = _STANDALONE_METRIC_CONFIDENCE_PATTERN.sub(
        _translate_standalone_metric_confidence,
        cleaned,
    )

    for pattern, replacement in _TECHNICAL_IDENTIFIER_REPLACEMENTS:
        cleaned = pattern.sub(replacement, cleaned)
    for pattern, replacement in _THESIS_CONFIDENCE_PHRASES:
        cleaned = pattern.sub(replacement, cleaned)
    for pattern, replacement in _CONTEXT_CODE_REPLACEMENTS:
        cleaned = pattern.sub(replacement, cleaned)
    for pattern, replacement in _DIRECTION_REPLACEMENTS:
        cleaned = pattern.sub(replacement, cleaned)
    for pattern, replacement in _PROVIDER_PROSE_REPLACEMENTS:
        cleaned = pattern.sub(replacement, cleaned)

    cleaned = strip_internal_enum_labels(cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip(" ,.;")


def _valuation_summary_denies_available_metrics(text: str) -> bool:
    if not str(text or "").strip():
        return True
    lowered = text.lower()
    return any(marker in lowered for marker in _MISLEADING_NO_VALUATION_MARKERS)


def resolve_valuation_semantics(
    *,
    unified: Optional[UnifiedResearchContext] = None,
    semantics: Optional[ValuationSemantics] = None,
    semantics_snapshot: Optional[dict] = None,
) -> Optional[ValuationSemantics]:
    if semantics is not None:
        return semantics
    if unified is not None:
        return derive_valuation_semantics(unified)
    return valuation_semantics_from_snapshot(semantics_snapshot)


def enforce_valuation_summary_invariant(
    text: str,
    *,
    semantics: Optional[ValuationSemantics],
) -> str:
    cleaned = polish_user_facing_text(text, section="valuation")
    if semantics is None:
        return cleaned

    authoritative = authoritative_valuation_summary(semantics)
    if authoritative:
        return authoritative

    if semantics.current_metrics_available and _valuation_summary_denies_available_metrics(cleaned):
        fallback = semantics.recommended_summary_framing(include_values=True)
        if fallback:
            return fallback
    return cleaned


def polish_valuation_summary_text(
    text: str,
    *,
    unified: Optional[UnifiedResearchContext] = None,
    semantics: Optional[ValuationSemantics] = None,
    semantics_snapshot: Optional[dict] = None,
) -> str:
    active_semantics = resolve_valuation_semantics(
        unified=unified,
        semantics=semantics,
        semantics_snapshot=semantics_snapshot,
    )
    return enforce_valuation_summary_invariant(text, semantics=active_semantics)


def _polish_string_tuple(
    values: Iterable[str],
    *,
    section: str = "general",
) -> Tuple[str, ...]:
    polished: list[str] = []
    for item in values:
        text = polish_user_facing_text(item, section=section)
        if text:
            polished.append(text)
    return tuple(polished)


def polish_ai_research_summary_view(
    view: AIResearchSummaryView,
    *,
    unified: Optional[UnifiedResearchContext] = None,
    semantics: Optional[ValuationSemantics] = None,
) -> AIResearchSummaryView:
    semantics_snapshot = (
        view.metadata.valuation_semantics
        if view.metadata is not None and view.metadata.valuation_semantics
        else None
    )
    active_semantics = resolve_valuation_semantics(
        unified=unified,
        semantics=semantics,
        semantics_snapshot=semantics_snapshot,
    )
    return AIResearchSummaryView(
        symbol=view.symbol,
        status=view.status,
        evidence_level=view.evidence_level,
        financial_outlook=polish_user_facing_text(view.financial_outlook),
        valuation_summary=polish_valuation_summary_text(
            view.valuation_summary,
            unified=unified,
            semantics=active_semantics,
            semantics_snapshot=semantics_snapshot,
        ),
        key_strengths=_polish_string_tuple(view.key_strengths),
        key_weaknesses=_polish_string_tuple(view.key_weaknesses),
        risks_to_watch=_polish_string_tuple(view.risks_to_watch),
        missing_evidence=_polish_string_tuple(view.missing_evidence),
        monitoring_points=_polish_string_tuple(view.monitoring_points),
        limitations=_polish_string_tuple(view.limitations, section="limitations"),
        generated_at=view.generated_at,
        model_provider=view.model_provider,
        model_name=view.model_name,
        source_context_version=view.source_context_version,
        user_message=polish_user_facing_text(view.user_message),
        metadata=view.metadata,
    )


def primary_text_contains_machine_tokens(text: str) -> bool:
    upper = str(text or "")
    return any(token in upper for token in _MACHINE_TOKENS_FORBIDDEN_IN_PRIMARY)
