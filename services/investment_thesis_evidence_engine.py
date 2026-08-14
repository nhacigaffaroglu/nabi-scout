from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from services.company_intelligence_contract import (
    CompanyIntelligenceView,
    IntelligenceObservation,
    NewsEvent,
)
from services.investment_thesis_contract import ThesisEvidence

_MATERIALITY_RANK = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
_CONFIDENCE_RANK = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
_CATEGORY_RANK = {
    "PROFITABILITY": 5,
    "GROWTH": 5,
    "CASH_FLOW": 4,
    "EARNINGS": 4,
    "VALUATION": 3,
    "PEERS": 3,
    "BALANCE_SHEET": 3,
    "RISK": 4,
    "NEWS": 2,
    "NABI_CONTEXT": 2,
    "PARTICIPATION": 2,
    "DATA_QUALITY": 1,
    "BUSINESS": 2,
    "CATALYST": 2,
}

_OBSERVATION_RULES: Dict[str, Tuple[str, str, str]] = {
    "GROSS_MARGIN_EXPANSION": ("PROFITABILITY", "SUPPORTS", "HIGH"),
    "OPERATING_MARGIN_EXPANSION": ("PROFITABILITY", "SUPPORTS", "HIGH"),
    "GROSS_MARGIN_COMPRESSION": ("PROFITABILITY", "WEAKENS", "HIGH"),
    "OPERATING_MARGIN_COMPRESSION": ("PROFITABILITY", "WEAKENS", "HIGH"),
    "REVENUE_ACCELERATION": ("GROWTH", "SUPPORTS", "HIGH"),
    "REVENUE_DECELERATION": ("GROWTH", "WEAKENS", "HIGH"),
    "EPS_YOY_CHANGE": ("EARNINGS", "NEUTRAL", "MEDIUM"),
    "FCF_CHANGE": ("CASH_FLOW", "SUPPORTS", "MEDIUM"),
    "FCF_DETERIORATION": ("CASH_FLOW", "WEAKENS", "MEDIUM"),
    "DEBT_INCREASE": ("BALANCE_SHEET", "NEUTRAL", "LOW"),
    "VALUATION_HISTORICAL_CONTEXT": ("VALUATION", "NEUTRAL", "MEDIUM"),
    "PROFITABILITY_ABOVE_PEER_MEDIAN": ("PEERS", "SUPPORTS", "MEDIUM"),
    "PROFITABILITY_BELOW_PEER_MEDIAN": ("PEERS", "WEAKENS", "MEDIUM"),
    "GROWTH_ABOVE_PEER_MEDIAN": ("PEERS", "SUPPORTS", "MEDIUM"),
    "GROWTH_BELOW_PEER_MEDIAN": ("PEERS", "WEAKENS", "MEDIUM"),
    "VALUATION_PREMIUM_VS_PEERS": ("PEERS", "NEUTRAL", "MEDIUM"),
    "VALUATION_DISCOUNT_VS_PEERS": ("PEERS", "NEUTRAL", "MEDIUM"),
}

_REGULATORY_NEWS_CATEGORIES = frozenset(
    {"REGULATORY", "LEGAL", "LITIGATION", "REGULATION", "COMPLIANCE"}
)


def _evidence_id(code: str, source: str, period: Optional[str]) -> str:
    suffix = period or "na"
    return f"{code}:{source}:{suffix}"


def _observation_to_evidence(
    observation: IntelligenceObservation,
    *,
    section: str,
    default_category: Optional[str] = None,
) -> ThesisEvidence:
    rule = _OBSERVATION_RULES.get(observation.code)
    if rule:
        category, polarity, materiality = rule
    else:
        category = default_category or "BUSINESS"
        polarity = "NEUTRAL"
        materiality = "MEDIUM"

    if observation.code == "REVENUE_YOY_CHANGE":
        category = "GROWTH"
        materiality = "MEDIUM"
        if observation.direction == "IMPROVING":
            polarity = "SUPPORTS"
        elif observation.direction == "DETERIORATING":
            polarity = "WEAKENS"
        else:
            polarity = "NEUTRAL"

    if observation.code == "EPS_YOY_CHANGE":
        evidence = dict(observation.evidence)
        eps_pct = evidence.get("eps_yoy_pct")
        if eps_pct is not None:
            try:
                if float(eps_pct) > 0:
                    polarity = "SUPPORTS"
                elif float(eps_pct) < 0:
                    polarity = "WEAKENS"
            except (TypeError, ValueError):
                polarity = "NEUTRAL"

    source = f"company_intelligence.{section}"
    return ThesisEvidence(
        evidence_id=_evidence_id(observation.code, source, observation.period),
        code=observation.code,
        category=category,
        polarity=polarity,
        materiality=materiality,
        statement=observation.statement,
        evidence=(
            ("source_section", section),
            ("source_code", observation.code),
            ("metric", observation.metric),
            ("value", observation.value),
            ("comparison_value", observation.comparison_value),
            ("direction", observation.direction),
            ("period", observation.period),
            *observation.evidence,
        ),
        source=source,
        confidence=observation.confidence,
        as_of=observation.period,
        limitations=observation.limitations,
    )


def _trend_evidence(view: CompanyIntelligenceView) -> List[ThesisEvidence]:
    items: List[ThesisEvidence] = []
    section = view.financial_trends
    if section is None:
        return items
    for observation in section.observations:
        items.append(_observation_to_evidence(observation, section="financial_trends"))
    return items


def _earnings_evidence(view: CompanyIntelligenceView) -> List[ThesisEvidence]:
    items: List[ThesisEvidence] = []
    section = view.earnings
    if section is None:
        return items
    for observation in section.observations:
        items.append(_observation_to_evidence(observation, section="earnings"))
    return items


def _valuation_evidence(view: CompanyIntelligenceView) -> List[ThesisEvidence]:
    items: List[ThesisEvidence] = []
    section = view.valuation
    if section is None:
        return items
    for observation in section.observations:
        items.append(_observation_to_evidence(observation, section="valuation"))
    for metric in section.metrics:
        if not metric.meaningful or metric.position == "INSUFFICIENT_DATA":
            continue
        items.append(
            ThesisEvidence(
                evidence_id=_evidence_id(metric.code, "company_intelligence.valuation", None),
                code=f"VALUATION_{metric.code.upper()}",
                category="VALUATION",
                polarity="NEUTRAL",
                materiality="MEDIUM",
                statement=f"{metric.label} tarihsel bağlamda {metric.position} konumunda.",
                evidence=(
                    ("source_section", "valuation"),
                    ("source_code", metric.code),
                    ("current_value", metric.current_value),
                    ("historical_median", metric.historical_median),
                    ("position", metric.position),
                    ("premium_to_median_pct", metric.premium_to_median_pct),
                ),
                source="company_intelligence.valuation",
                confidence="MEDIUM",
                as_of=view.as_of,
                limitations=metric.limitations,
            )
        )
    return items


def _peer_evidence(view: CompanyIntelligenceView) -> List[ThesisEvidence]:
    items: List[ThesisEvidence] = []
    section = view.peers
    if section is None:
        return items
    insufficient = any(
        "yetersiz" in limitation.lower() or "insufficient" in limitation.lower()
        for limitation in section.limitations
    )
    for observation in section.observations:
        evidence = _observation_to_evidence(observation, section="peers")
        if insufficient:
            evidence = ThesisEvidence(
                evidence_id=evidence.evidence_id,
                code=evidence.code,
                category=evidence.category,
                polarity=evidence.polarity,
                materiality=evidence.materiality,
                statement=evidence.statement,
                evidence=evidence.evidence,
                source=evidence.source,
                confidence="LOW",
                as_of=evidence.as_of,
                limitations=section.limitations + evidence.limitations,
            )
        items.append(evidence)
    if insufficient and not section.observations:
        items.append(
            ThesisEvidence(
                evidence_id="PEER_SAMPLE_INSUFFICIENT:peers:na",
                code="PEER_SAMPLE_INSUFFICIENT",
                category="PEERS",
                polarity="UNKNOWN",
                materiality="LOW",
                statement="Emsal karşılaştırması için yeterli örneklem yok.",
                evidence=(
                    ("source_section", "peers"),
                    ("peer_count", len(section.peer_symbols)),
                    ("limitations", list(section.limitations)),
                ),
                source="company_intelligence.peers",
                confidence="LOW",
                as_of=view.as_of,
                limitations=section.limitations,
            )
        )
    return items


def _news_evidence(view: CompanyIntelligenceView) -> List[ThesisEvidence]:
    items: List[ThesisEvidence] = []
    section = view.news
    if section is None:
        return items
    for event in section.events:
        if event.materiality != "MATERIAL":
            continue
        if event.sentiment and not _is_regulatory_or_factual(event):
            continue
        category = "NEWS"
        polarity = "NEUTRAL"
        materiality = "MEDIUM"
        if _is_regulatory_or_factual(event):
            polarity = "WEAKENS"
            category = "RISK"
            materiality = "HIGH"
        items.append(
            ThesisEvidence(
                evidence_id=f"NEWS:{event.event_id}",
                code=f"NEWS_{event.category}",
                category=category,
                polarity=polarity,
                materiality=materiality,
                statement=event.headline,
                evidence=(
                    ("source_section", "news"),
                    ("event_id", event.event_id),
                    ("category", event.category),
                    ("materiality", event.materiality),
                    ("published_at", event.published_at),
                    ("impact_domains", list(event.impact_domains)),
                ),
                source="company_intelligence.news",
                confidence=event.confidence,
                as_of=event.published_at,
                limitations=("Haber duyarlılığı tek başına tez kanıtı oluşturmaz.",),
            )
        )
    return items


def _is_regulatory_or_factual(event: NewsEvent) -> bool:
    category = (event.category or "").upper()
    if category in _REGULATORY_NEWS_CATEGORIES:
        return True
    domains = {domain.upper() for domain in event.impact_domains}
    return bool(domains.intersection(_REGULATORY_NEWS_CATEGORIES))


def _factual_risk_evidence(view: CompanyIntelligenceView) -> List[ThesisEvidence]:
    items: List[ThesisEvidence] = []
    for observation in view.factual_risks:
        items.append(
            ThesisEvidence(
                evidence_id=_evidence_id(observation.code, "factual_risks", observation.period),
                code=observation.code,
                category="RISK",
                polarity="WEAKENS",
                materiality="HIGH",
                statement=observation.statement,
                evidence=(
                    ("source_section", "factual_risks"),
                    ("source_code", observation.code),
                    *observation.evidence,
                ),
                source="company_intelligence.factual_risks",
                confidence=observation.confidence,
                as_of=observation.period or view.as_of,
                limitations=observation.limitations,
            )
        )
    return items


def _nabi_context_evidence(
    candidate: Optional[Dict[str, Any]],
) -> List[ThesisEvidence]:
    if not candidate:
        return []
    items: List[ThesisEvidence] = []
    decision = candidate.get("decision") or candidate.get("nabi_decision")
    score = candidate.get("nabi_score")
    if decision or score is not None:
        items.append(
            ThesisEvidence(
                evidence_id="NABI_CONTEXT:scanner:na",
                code="NABI_DECISION_CONTEXT",
                category="NABI_CONTEXT",
                polarity="NEUTRAL",
                materiality="LOW",
                statement="Mevcut NABI kararı ve puanı bağlam olarak kaydedildi.",
                evidence=(
                    ("source_section", "nabi_scanner"),
                    ("decision", decision),
                    ("nabi_score", score),
                    ("research_status", candidate.get("research_status")),
                ),
                source="nabi_scanner",
                confidence="HIGH",
                as_of=None,
                limitations=("NABI kararı tez durumunu belirlemez.",),
            )
        )
    return items


def _data_quality_evidence(view: CompanyIntelligenceView) -> List[ThesisEvidence]:
    dq = view.data_quality
    if dq is None:
        return []
    items: List[ThesisEvidence] = []
    if dq.provider_failures:
        items.append(
            ThesisEvidence(
                evidence_id="DATA_QUALITY:provider_failures:na",
                code="PROVIDER_FAILURE",
                category="DATA_QUALITY",
                polarity="UNKNOWN",
                materiality="MEDIUM",
                statement="Bazı veri kaynaklarına erişilemedi.",
                evidence=(
                    ("source_section", "data_quality"),
                    ("provider_failures", list(dq.provider_failures)),
                ),
                source="company_intelligence.data_quality",
                confidence="HIGH",
                as_of=dq.as_of,
                limitations=tuple(dq.warnings),
            )
        )
    return items


def collect_thesis_evidence(
    view: CompanyIntelligenceView,
    *,
    candidate: Optional[Dict[str, Any]] = None,
) -> Tuple[ThesisEvidence, ...]:
    collected: List[ThesisEvidence] = []
    collected.extend(_trend_evidence(view))
    collected.extend(_earnings_evidence(view))
    collected.extend(_valuation_evidence(view))
    collected.extend(_peer_evidence(view))
    collected.extend(_news_evidence(view))
    collected.extend(_factual_risk_evidence(view))
    collected.extend(_nabi_context_evidence(candidate))
    collected.extend(_data_quality_evidence(view))
    return tuple(collected)


def evidence_priority(evidence: ThesisEvidence) -> Tuple[int, int, int, str]:
    return (
        -_MATERIALITY_RANK.get(evidence.materiality, 0),
        -_CONFIDENCE_RANK.get(evidence.confidence, 0),
        -_CATEGORY_RANK.get(evidence.category, 0),
        evidence.evidence_id,
    )


def partition_evidence(
    evidence: Tuple[ThesisEvidence, ...],
) -> Tuple[Tuple[ThesisEvidence, ...], Tuple[ThesisEvidence, ...]]:
    supporting = tuple(
        sorted(
            [item for item in evidence if item.polarity == "SUPPORTS"],
            key=evidence_priority,
        )
    )
    weakening = tuple(
        sorted(
            [item for item in evidence if item.polarity == "WEAKENS"],
            key=evidence_priority,
        )
    )
    return supporting, weakening
