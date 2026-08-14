from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from services.company_intelligence_contract import CompanyIntelligenceView
from services.investment_thesis_contract import (
    DecisionIntelligenceView,
    EARNINGS_CONTEXT,
    EvidenceCoverage,
    ExpectationTension,
    InvalidationCondition,
    InvestmentThesisView,
    MonitoringItem,
    THESIS_VERSION,
    ThesisAssumption,
    ThesisCatalyst,
    ThesisRisk,
    ThesisEvidence,
    VALUATION_CONTEXT,
)
from services.investment_thesis_evidence_engine import (
    collect_thesis_evidence,
    evidence_priority,
    partition_evidence,
)

_INSUFFICIENT_SUMMARY = (
    "Mevcut veri güvenilir bir yatırım tezi oluşturmak için yetersiz."
)


def _valuation_context_label(view: CompanyIntelligenceView) -> str:
    section = view.valuation
    if section is None or not section.metrics:
        return "VALUATION_UNAVAILABLE"
    positions = [
        metric.position
        for metric in section.metrics
        if metric.meaningful and metric.position != "INSUFFICIENT_DATA"
    ]
    if not positions:
        return "VALUATION_UNAVAILABLE"
    above = sum(
        1
        for position in positions
        if position in {"ABOVE_HISTORICAL_MEDIAN", "ABOVE_HISTORICAL_RANGE"}
    )
    below = sum(
        1
        for position in positions
        if position in {"BELOW_HISTORICAL_MEDIAN", "BELOW_HISTORICAL_RANGE"}
    )
    if above > below and above >= len(positions) / 2:
        return "VALUATION_DEMANDING"
    if below > above and below >= len(positions) / 2:
        return "VALUATION_SUPPORTIVE"
    return "VALUATION_NEUTRAL"


def _earnings_context_label(
    supporting: Tuple[ThesisEvidence, ...],
    weakening: Tuple[ThesisEvidence, ...],
) -> str:
    earnings_support = sum(
        1 for item in supporting if item.category in {"EARNINGS", "PROFITABILITY", "CASH_FLOW"}
    )
    earnings_weak = sum(
        1 for item in weakening if item.category in {"EARNINGS", "PROFITABILITY", "CASH_FLOW"}
    )
    if earnings_support == 0 and earnings_weak == 0:
        return "EARNINGS_UNAVAILABLE"
    if earnings_support > earnings_weak:
        return "EARNINGS_SUPPORT"
    if earnings_weak > earnings_support:
        return "EARNINGS_WEAKENING"
    return "EARNINGS_MIXED"


def _evidence_coverage(view: CompanyIntelligenceView) -> EvidenceCoverage:
    dq = view.data_quality

    def _status(flag: bool, partial: bool = False) -> str:
        if flag:
            return "available"
        if partial:
            return "partial"
        return "unavailable"

    if dq is None:
        return EvidenceCoverage(
            financials="unavailable",
            earnings="unavailable",
            valuation="unavailable",
            peers="unavailable",
            news="unavailable",
            participation="unavailable",
        )
    return EvidenceCoverage(
        financials=_status(dq.financial_history_available),
        earnings=_status(
            dq.quarterly_comparison_available,
            partial=not dq.earnings_expectations_available,
        ),
        valuation=_status(
            dq.valuation_available,
            partial=not dq.historical_valuation_available,
        ),
        peers=_status(dq.peer_data_available),
        news=_status(dq.news_available),
        participation="unavailable",
    )


def _confidence_level(
    coverage: EvidenceCoverage,
    evidence: Tuple[ThesisEvidence, ...],
    view: CompanyIntelligenceView,
) -> str:
    score = 0
    for section in (
        coverage.financials,
        coverage.earnings,
        coverage.valuation,
        coverage.peers,
        coverage.news,
    ):
        if section == "available":
            score += 2
        elif section == "partial":
            score += 1
    material_evidence = [
        item
        for item in evidence
        if item.category != "DATA_QUALITY" and item.polarity != "UNKNOWN"
    ]
    if not material_evidence:
        return "LOW"
    if len(material_evidence) >= 4:
        score += 1
    elif len(material_evidence) <= 1:
        score -= 2
    dq = view.data_quality
    if dq and dq.provider_failures:
        score -= 2
    if dq and dq.partial_sections:
        score -= 1
    if view.peers and view.peers.limitations and not view.peers.observations:
        return "LOW"
    if view.valuation is None:
        score -= 2
    if score >= 8:
        return "HIGH"
    if score >= 4:
        return "MEDIUM"
    return "LOW"


def _evidence_balance(
    supporting: Tuple[ThesisEvidence, ...],
    weakening: Tuple[ThesisEvidence, ...],
    confidence: str,
) -> str:
    if confidence == "LOW" and len(supporting) + len(weakening) < 2:
        return "INSUFFICIENT_DATA"

    def _weight(items: Tuple[ThesisEvidence, ...]) -> int:
        weights = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
        return sum(weights.get(item.materiality, 1) for item in items)

    support_weight = _weight(supporting)
    weakness_weight = _weight(weakening)
    if support_weight == 0 and weakness_weight == 0:
        return "INSUFFICIENT_DATA"
    if support_weight > weakness_weight * 1.25:
        return "SUPPORT_DOMINANT"
    if weakness_weight > support_weight * 1.25:
        return "WEAKNESS_DOMINANT"
    return "BALANCED"


def _thesis_status(balance: str, confidence: str) -> str:
    if balance == "INSUFFICIENT_DATA" or confidence == "LOW":
        if balance == "INSUFFICIENT_DATA":
            return "INSUFFICIENT_DATA"
    mapping = {
        "SUPPORT_DOMINANT": "SUPPORTED",
        "BALANCED": "MIXED",
        "WEAKNESS_DOMINANT": "WEAKENING",
        "INSUFFICIENT_DATA": "INSUFFICIENT_DATA",
    }
    return mapping.get(balance, "MIXED")


def _expectation_tensions(
    view: CompanyIntelligenceView,
    supporting: Tuple[ThesisEvidence, ...],
    weakening: Tuple[ThesisEvidence, ...],
    valuation_context: str,
    evidence: Tuple[ThesisEvidence, ...],
) -> Tuple[ExpectationTension, ...]:
    tensions: List[ExpectationTension] = []
    all_evidence = evidence
    has_slow_growth = any(item.code == "REVENUE_DECELERATION" for item in weakening)
    has_strong_growth = any(
        item.code in {"REVENUE_ACCELERATION", "REVENUE_YOY_CHANGE"}
        and item.polarity == "SUPPORTS"
        for item in supporting
    )
    has_margin_improve = any(
        item.code in {"GROSS_MARGIN_EXPANSION", "OPERATING_MARGIN_EXPANSION"}
        for item in supporting
    )
    peer_premium = any(item.code == "VALUATION_PREMIUM_VS_PEERS" for item in all_evidence)
    peer_weak_growth = any(item.code == "GROWTH_BELOW_PEER_MEDIAN" for item in all_evidence)

    if valuation_context == "VALUATION_DEMANDING" and has_slow_growth:
        tensions.append(
            ExpectationTension(
                code="HIGH_VALUATION_SLOWING_GROWTH",
                statement=(
                    "Değerleme tarihsel medyanın üzerindeyken gelir büyümesi yavaşlıyor; "
                    "beklenti gerilimi artabilir."
                ),
                status="ACTIVE",
                confidence="MEDIUM",
                evidence=(
                    ("valuation_context", valuation_context),
                    ("growth_signal", "REVENUE_DECELERATION"),
                ),
            )
        )
    if valuation_context == "VALUATION_DEMANDING" and has_strong_growth:
        tensions.append(
            ExpectationTension(
                code="HIGH_VALUATION_STRONG_GROWTH",
                statement=(
                    "Değerleme primi mevcutken büyüme sinyalleri destekleyici; "
                    "primin korunması büyüme sürekliliğine bağlı."
                ),
                status="ACTIVE",
                confidence="MEDIUM",
                evidence=(
                    ("valuation_context", valuation_context),
                    ("growth_signal", "positive"),
                ),
            )
        )
    if valuation_context == "VALUATION_DEMANDING" and has_margin_improve:
        tensions.append(
            ExpectationTension(
                code="HIGH_VALUATION_IMPROVING_MARGINS",
                statement=(
                    "Değerleme yüksek seviyede kalırken marj genişlemesi "
                    "beklenti gerilimini kısmen dengeleyebilir."
                ),
                status="ACTIVE",
                confidence="MEDIUM",
                evidence=(
                    ("valuation_context", valuation_context),
                    ("margin_signal", "expansion"),
                ),
            )
        )
    if peer_premium and peer_weak_growth:
        tensions.append(
            ExpectationTension(
                code="PEER_PREMIUM_WEAKER_GROWTH",
                statement="Emsallere göre değerleme primi varken büyüme emsal medyanının altında.",
                status="ACTIVE",
                confidence="LOW",
                evidence=(
                    ("peer_premium", True),
                    ("peer_growth", "below_median"),
                ),
            )
        )
    if valuation_context == "VALUATION_SUPPORTIVE" and len(weakening) >= 2:
        tensions.append(
            ExpectationTension(
                code="DISCOUNT_WITH_WEAK_FUNDAMENTALS",
                statement=(
                    "Değerleme tarihsel medyanın altında olsa da temel göstergeler "
                    "zayıflama sinyalleri içeriyor."
                ),
                status="ACTIVE",
                confidence="MEDIUM",
                evidence=(
                    ("valuation_context", valuation_context),
                    ("weakness_count", len(weakening)),
                ),
            )
        )
    return tuple(tensions)


def _key_question(
    tensions: Tuple[ExpectationTension, ...],
    supporting: Tuple[ThesisEvidence, ...],
    weakening: Tuple[ThesisEvidence, ...],
    valuation_context: str,
) -> str:
    if tensions:
        code = tensions[0].code
        mapping = {
            "HIGH_VALUATION_SLOWING_GROWTH": (
                "Mevcut büyüme, değerleme primini desteklemeye devam edecek mi?"
            ),
            "HIGH_VALUATION_STRONG_GROWTH": (
                "Güçlü büyüme sürerken değerleme primi korunabilir mi?"
            ),
            "HIGH_VALUATION_IMPROVING_MARGINS": (
                "Marj genişlemesi değerleme primini haklı çıkaracak mı?"
            ),
            "PEER_PREMIUM_WEAKER_GROWTH": (
                "Emsallere göre zayıf büyüme, değerleme primini baskılayacak mı?"
            ),
            "DISCOUNT_WITH_WEAK_FUNDAMENTALS": (
                "Zayıf temellerde değerleme indirimi yeterli bir denge sağlıyor mu?"
            ),
        }
        return mapping.get(code, "Temel göstergelerdeki gerilim nasıl çözülecek?")

    has_leverage = any(item.code == "DEBT_INCREASE" for item in supporting + weakening)
    has_fcf_support = any(item.code == "FCF_CHANGE" for item in supporting)
    if has_leverage and has_fcf_support:
        return "Nakit üretimi borç yükünü yönetmek için yeterli mi?"

    if any(item.code.endswith("COMPRESSION") for item in weakening) and any(
        item.category == "GROWTH" for item in supporting
    ):
        return "Büyüme sürerken marj baskısı geçici mi?"

    if valuation_context == "VALUATION_DEMANDING":
        return "Mevcut değerleme seviyesi temel göstergelerle uyumlu mu?"

    if not supporting and not weakening:
        return "Güvenilir tez oluşturmak için hangi temel veriler tamamlanmalı?"

    return "Temel göstergelerdeki denge nasıl evrilecek?"


def _build_summary(
    supporting: Tuple[ThesisEvidence, ...],
    weakening: Tuple[ThesisEvidence, ...],
    valuation_context: str,
    earnings_context: str,
    confidence: str,
) -> str:
    if confidence == "LOW" and len(supporting) + len(weakening) < 2:
        return _INSUFFICIENT_SUMMARY

    if not supporting and not weakening:
        return _INSUFFICIENT_SUMMARY

    parts: List[str] = []
    if earnings_context == "EARNINGS_SUPPORT":
        parts.append("Kazanç ve karlılık görünümü destekleyici sinyaller içeriyor.")
    elif earnings_context == "EARNINGS_WEAKENING":
        parts.append("Kazanç ve karlılık görünümünde zayıflama sinyalleri var.")
    elif earnings_context == "EARNINGS_MIXED":
        parts.append("Kazanç görünümü karışık sinyaller veriyor.")

    if supporting:
        top = supporting[0].statement.rstrip(".")
        parts.append(f"Destekleyici kanıt: {top}.")
    if weakening:
        top = weakening[0].statement.rstrip(".")
        parts.append(f"Zayıflatan kanıt: {top}.")

    valuation_text = {
        "VALUATION_SUPPORTIVE": "Değerleme tarihsel medyanın altında veya destekleyici bölgede.",
        "VALUATION_NEUTRAL": "Değerleme tarihsel medyan civarında.",
        "VALUATION_DEMANDING": "Değerleme tarihsel medyanın üzerinde; beklentilere duyarlılık artabilir.",
        "VALUATION_UNAVAILABLE": "Değerleme bağlamı sınırlı.",
    }
    parts.append(valuation_text.get(valuation_context, valuation_text["VALUATION_UNAVAILABLE"]))
    return " ".join(parts)


def _build_risks(
    weakening: Tuple[ThesisEvidence, ...],
    view: CompanyIntelligenceView,
) -> Tuple[ThesisRisk, ...]:
    risks: List[ThesisRisk] = []
    for index, evidence in enumerate(weakening):
        if evidence.category not in {"RISK", "BALANCE_SHEET", "CASH_FLOW", "PROFITABILITY", "GROWTH"}:
            continue
        risks.append(
            ThesisRisk(
                risk_id=f"risk-{index + 1}",
                code=evidence.code,
                category=evidence.category,
                severity=evidence.materiality,
                statement=evidence.statement,
                evidence=evidence.evidence,
                likelihood="UNKNOWN",
                impact="QUALITATIVE",
                monitoring_metric=evidence.evidence[0][1] if evidence.evidence else None,
                source=evidence.source,
                confidence=evidence.confidence,
            )
        )
    if view.valuation and _valuation_context_label(view) == "VALUATION_DEMANDING":
        risks.append(
            ThesisRisk(
                risk_id="risk-valuation-expectations",
                code="VALUATION_EXPECTATION_SENSITIVITY",
                category="VALUATION",
                severity="MEDIUM",
                statement=(
                    "Mevcut çoklu tarihsel medyanın üzerinde; büyüme ve marj "
                    "beklentilerinin korunmasına duyarlılık artabilir."
                ),
                evidence=(
                    ("valuation_context", "VALUATION_DEMANDING"),
                    ("source_section", "valuation"),
                ),
                likelihood="UNKNOWN",
                impact="QUALITATIVE",
                monitoring_metric="pe_ratio",
                source="investment_thesis.rules",
                confidence="MEDIUM",
            )
        )
    return tuple(risks[:8])


def _build_catalysts(view: CompanyIntelligenceView) -> Tuple[ThesisCatalyst, ...]:
    items: List[ThesisCatalyst] = []
    for index, catalyst in enumerate(view.catalysts):
        items.append(
            ThesisCatalyst(
                catalyst_id=f"catalyst-{index + 1}",
                catalyst_type=catalyst.catalyst_type,
                description=catalyst.description,
                expected_date=catalyst.date,
                status=catalyst.status,
                source=catalyst.source,
                confidence=catalyst.confidence,
                thesis_relevance="MONITOR",
                limitations=() if catalyst.date else ("Kesin tarih bilinmiyor.",),
            )
        )
    return tuple(items)


def _build_invalidations(
    supporting: Tuple[ThesisEvidence, ...],
    weakening: Tuple[ThesisEvidence, ...],
    valuation_context: str,
    evidence: Tuple[ThesisEvidence, ...],
) -> Tuple[InvalidationCondition, ...]:
    conditions: List[InvalidationCondition] = []
    margin_support = [
        item
        for item in supporting
        if item.code in {"GROSS_MARGIN_EXPANSION", "OPERATING_MARGIN_EXPANSION"}
    ]
    for item in margin_support:
        conditions.append(
            InvalidationCondition(
                condition_id=f"inv-{item.code.lower()}",
                code="MARGIN_SUPPORT_REVERSAL",
                statement=(
                    "Faaliyet marjı, son karşılaştırılabilir dönem aralığının "
                    "anlamlı altına geriler."
                ),
                linked_evidence_ids=(item.evidence_id,),
                monitoring_metric=item.evidence[0][1] if item.evidence else "operating_margin",
                source=item.source,
                confidence=item.confidence,
            )
        )

    fcf_support = [item for item in supporting if item.code == "FCF_CHANGE"]
    for item in fcf_support:
        conditions.append(
            InvalidationCondition(
                condition_id="inv-fcf-negative",
                code="FCF_SUPPORT_REVERSAL",
                statement=(
                    "Serbest nakit akışı, geçici bir neden olmaksızın "
                    "karşılaştırılabilir dönemlerde negatife döner."
                ),
                linked_evidence_ids=(item.evidence_id,),
                monitoring_metric="free_cash_flow",
                source=item.source,
                confidence=item.confidence,
            )
        )

    if valuation_context == "VALUATION_DEMANDING" and any(
        item.code == "REVENUE_DECELERATION" for item in weakening
    ):
        conditions.append(
            InvalidationCondition(
                condition_id="inv-growth-valuation",
                code="GROWTH_VALUATION_MISMATCH",
                statement=(
                    "Gelir/EPS büyümesi belirgin şekilde yavaşlarken değerleme "
                    "tarihsel medyanın üzerinde kalır."
                ),
                linked_evidence_ids=tuple(item.evidence_id for item in weakening[:2]),
                monitoring_metric="revenue",
                source="investment_thesis.rules",
                confidence="MEDIUM",
            )
        )

    if any(item.code == "DEBT_INCREASE" for item in supporting + weakening + evidence) and any(
        item.code == "FCF_DETERIORATION" for item in weakening
    ):
        conditions.append(
            InvalidationCondition(
                condition_id="inv-leverage-fcf",
                code="LEVERAGE_FCF_PRESSURE",
                statement=(
                    "Net kaldıraç artmaya devam ederken serbest nakit akışı "
                    "bozulmaya devam eder."
                ),
                linked_evidence_ids=tuple(item.evidence_id for item in weakening[:2]),
                monitoring_metric="total_debt",
                source="investment_thesis.rules",
                confidence="MEDIUM",
            )
        )
    return tuple(conditions)


def _build_assumptions(
    supporting: Tuple[ThesisEvidence, ...],
) -> Tuple[ThesisAssumption, ...]:
    assumptions: List[ThesisAssumption] = []
    for item in supporting:
        if item.code in {"GROSS_MARGIN_EXPANSION", "OPERATING_MARGIN_EXPANSION"}:
            assumptions.append(
                ThesisAssumption(
                    assumption_id=f"assumption-{item.code.lower()}",
                    statement="Mevcut marj gücü sürdürülebilir.",
                    basis=item.statement,
                    confidence="MEDIUM",
                    required_evidence=(item.evidence_id,),
                    status="UNVERIFIED",
                )
            )
        if item.code == "REVENUE_ACCELERATION":
            assumptions.append(
                ThesisAssumption(
                    assumption_id="assumption-revenue-acceleration",
                    statement="Gelir ivmesi en az bir sonraki dönemde korunur.",
                    basis=item.statement,
                    confidence="MEDIUM",
                    required_evidence=(item.evidence_id,),
                    status="UNVERIFIED",
                )
            )
    return tuple(assumptions)


def _monitoring_plan(
    invalidations: Tuple[InvalidationCondition, ...],
    catalysts: Tuple[ThesisCatalyst, ...],
    supporting: Tuple[ThesisEvidence, ...],
    weakening: Tuple[ThesisEvidence, ...],
) -> Tuple[MonitoringItem, ...]:
    items: List[MonitoringItem] = []
    metrics = {
        "revenue": "Gelir büyümesi",
        "operating_margin": "Faaliyet marjı",
        "free_cash_flow": "Serbest nakit akışı",
        "total_debt": "Toplam borç",
        "pe_ratio": "F/K çarpanı",
    }
    for invalidation in invalidations:
        metric = invalidation.monitoring_metric or "fundamentals"
        items.append(
            MonitoringItem(
                item_id=f"monitor-{invalidation.condition_id}",
                metric_or_event=metrics.get(str(metric), str(metric)),
                why_it_matters=invalidation.statement,
                current_state="İzleniyor",
                invalidation_link=invalidation.condition_id,
                next_known_date=None,
                source=invalidation.source,
            )
        )
    for catalyst in catalysts[:3]:
        items.append(
            MonitoringItem(
                item_id=f"monitor-{catalyst.catalyst_id}",
                metric_or_event=catalyst.description,
                why_it_matters="Bilinen katalizör tarihi veya olayı.",
                current_state=catalyst.status,
                invalidation_link=None,
                next_known_date=catalyst.expected_date,
                source=catalyst.source,
            )
        )
    if not items and (supporting or weakening):
        top = (supporting or weakening)[0]
        items.append(
            MonitoringItem(
                item_id="monitor-primary-metric",
                metric_or_event=top.statement,
                why_it_matters="Tezdeki baskın kanıtın sürekliliği.",
                current_state=top.polarity,
                invalidation_link=None,
                next_known_date=None,
                source=top.source,
            )
        )
    return tuple(items)


def _peer_context_text(view: CompanyIntelligenceView) -> Optional[str]:
    section = view.peers
    if section is None:
        return None
    if section.limitations:
        return "Emsal karşılaştırması sınırlı örnekleme ile üretildi."
    statements = [obs.statement for obs in section.observations[:3]]
    return " ".join(statements) if statements else None


def _news_context_text(view: CompanyIntelligenceView) -> Optional[str]:
    section = view.news
    if section is None or not section.events:
        return None
    material = [event.headline for event in section.events if event.materiality == "MATERIAL"]
    if not material:
        return "Materyal haber bulunmuyor."
    return f"{len(material)} materyal haber olayı kayıtlı."


def _decision_intelligence(
    *,
    thesis_status: str,
    balance: str,
    key_question: str,
    supporting: Tuple[ThesisEvidence, ...],
    weakening: Tuple[ThesisEvidence, ...],
    risks: Tuple[ThesisRisk, ...],
    catalysts: Tuple[ThesisCatalyst, ...],
    tensions: Tuple[ExpectationTension, ...],
    invalidations: Tuple[InvalidationCondition, ...],
    coverage: EvidenceCoverage,
    candidate: Optional[Dict[str, Any]],
) -> DecisionIntelligenceView:
    nabi_context = None
    if candidate:
        decision = candidate.get("decision") or candidate.get("nabi_decision")
        score = candidate.get("nabi_score")
        if decision or score is not None:
            nabi_context = f"NABI kararı: {decision or '—'} · Puan: {score if score is not None else '—'}"
    missing = [key for key, value in coverage.to_dict().items() if value == "unavailable"]
    data_quality = "Tam" if not missing else f"Eksik: {', '.join(missing)}"
    return DecisionIntelligenceView(
        thesis_status=thesis_status,
        evidence_balance=balance,
        key_question=key_question,
        strongest_support=supporting[0].statement if supporting else None,
        strongest_weakness=weakening[0].statement if weakening else None,
        primary_risk=risks[0].statement if risks else None,
        primary_catalyst=catalysts[0].description if catalysts else None,
        valuation_tension=tensions[0].statement if tensions else None,
        invalidation_watch=invalidations[0].statement if invalidations else None,
        data_quality=data_quality,
        nabi_decision_context=nabi_context,
    )


def build_investment_thesis_view(
    view: CompanyIntelligenceView,
    *,
    candidate: Optional[Dict[str, Any]] = None,
    participation_context: Optional[str] = None,
) -> InvestmentThesisView:
    evidence = collect_thesis_evidence(view, candidate=candidate)
    supporting, weakening = partition_evidence(evidence)
    valuation_context = _valuation_context_label(view)
    earnings_context = _earnings_context_label(supporting, weakening)
    coverage = _evidence_coverage(view)
    confidence = _confidence_level(coverage, evidence, view)
    balance = _evidence_balance(supporting, weakening, confidence)
    thesis_status = _thesis_status(balance, confidence)
    tensions = _expectation_tensions(view, supporting, weakening, valuation_context, evidence)
    key_question = _key_question(tensions, supporting, weakening, valuation_context)
    summary = _build_summary(
        supporting,
        weakening,
        valuation_context,
        earnings_context,
        confidence,
    )
    risks = _build_risks(weakening, view)
    catalysts = _build_catalysts(view)
    invalidations = _build_invalidations(supporting, weakening, valuation_context, evidence)
    assumptions = _build_assumptions(supporting)
    monitoring = _monitoring_plan(invalidations, catalysts, supporting, weakening)

    nabi_context = None
    if candidate:
        decision = candidate.get("decision") or candidate.get("nabi_decision")
        if decision:
            nabi_context = f"NABI kararı: {decision} (tez durumundan bağımsız)"

    dq_notes: Tuple[str, ...] = ()
    if view.data_quality:
        dq_notes = view.data_quality.warnings + view.data_quality.partial_sections

    provenance = tuple(
        (f"{item.provider}:{item.data_family}", item.retrieved_at or "")
        for item in view.provenance
    )

    decision = _decision_intelligence(
        thesis_status=thesis_status,
        balance=balance,
        key_question=key_question,
        supporting=supporting,
        weakening=weakening,
        risks=risks,
        catalysts=catalysts,
        tensions=tensions,
        invalidations=invalidations,
        coverage=coverage,
        candidate=candidate,
    )

    return InvestmentThesisView(
        symbol=view.symbol,
        company_name=view.company_name,
        as_of=view.as_of,
        thesis_version=THESIS_VERSION,
        thesis_status=thesis_status,
        thesis_summary=summary,
        key_question=key_question,
        supporting_evidence=supporting,
        weakening_evidence=weakening,
        risks=risks,
        catalysts=catalysts,
        invalidation_conditions=invalidations,
        assumptions=assumptions,
        valuation_context=valuation_context,
        earnings_context=earnings_context,
        peer_context=_peer_context_text(view),
        news_context=_news_context_text(view),
        expectation_tensions=tensions,
        participation_context=participation_context,
        nabi_context=nabi_context,
        confidence=confidence,
        evidence_coverage=coverage,
        monitoring_plan=monitoring,
        decision_intelligence=decision,
        data_quality_notes=dq_notes,
        provenance=provenance,
    )
