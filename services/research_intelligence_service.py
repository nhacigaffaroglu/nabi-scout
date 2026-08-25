"""Research Intelligence synthesis over canonical evidence. No new score.

Consumes Participation, Company Report / investment thesis, NABI evaluation,
existing valuation classification, completeness, opportunity decision, and
portfolio-fit. Does not recompute those engines. Does not persist.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, List, Mapping, Optional, Sequence, Tuple

from config.participation_catalog import is_configured_participation_symbol
from services.candidate_pipeline_presentation import ACTIONABLE_DECISIONS
from services.investment_thesis_contract import InvestmentThesisView
from services.nabi_portfolio_fit import FIT_POOR, PortfolioFitAssessment
from services.participation_authority import resolve_authoritative_participation
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.research_intelligence_contract import (
    COMPLETENESS_HIGH,
    COMPLETENESS_LOW,
    CONFIDENCE_LEVEL_MAP,
    INSUFFICIENT,
    MAX_POINTS,
    RESEARCH_STATE_BLOCKED,
    RESEARCH_STATE_INSUFFICIENT,
    RESEARCH_STATE_NOT_APPLICABLE,
    RESEARCH_STATE_READY,
    RESEARCH_STATE_WATCH,
    ResearchEvidenceRef,
    ResearchIntelligence,
    ResearchIntelligenceBrief,
    THESIS_VALUATION_MAP,
    UNKNOWN,
    VALUATION_EXPENSIVE,
    VALUATION_UNKNOWN,
)
from services.research_workflow_service import normalize_research_status

WATCH_DECISIONS = frozenset({"İZLE", "IZLE"})


def _text(value: Any) -> str:
    return str(value or "").strip()


def _symbol_of(value: Any, candidate: Optional[Mapping[str, Any]]) -> str:
    return _text(value or (candidate or {}).get("symbol")).upper()


def _is_etf(candidate: Optional[Mapping[str, Any]], symbol: str, explicit: Optional[bool]) -> bool:
    if explicit is not None:
        return bool(explicit)
    if candidate and (
        candidate.get("is_etf")
        or _text(candidate.get("asset_type")).upper() == "ETF"
        or _text(candidate.get("security_type")).upper() == "ETF"
    ):
        return True
    return is_configured_participation_symbol(symbol)


def _bounded(items: Iterable[str], *, limit: int = MAX_POINTS) -> Tuple[str, ...]:
    unique: list[str] = []
    for item in items:
        text = _text(item)
        if not text or text in unique:
            continue
        unique.append(text)
        if len(unique) >= limit:
            break
    return tuple(unique)


def _as_texts(value: Any) -> List[str]:
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple)):
        texts: list[str] = []
        for item in value:
            texts.extend(_as_texts(item))
        return texts
    return [_text(value)] if _text(value) else []


def _ref(
    *,
    source_type: str,
    source_reference: str,
    evidence_type: str,
    observed_at: Optional[str] = None,
    statement: str = "",
) -> ResearchEvidenceRef:
    return ResearchEvidenceRef(
        source_type=source_type,
        source_reference=source_reference,
        observed_at=observed_at,
        evidence_type=evidence_type,
        statement=statement,
    )


def _completeness(
    thesis: Optional[InvestmentThesisView],
    candidate: Optional[Mapping[str, Any]],
) -> str:
    if thesis and thesis.confidence:
        mapped = CONFIDENCE_LEVEL_MAP.get(_text(thesis.confidence).upper())
        if mapped:
            return mapped
    if candidate:
        mapped = CONFIDENCE_LEVEL_MAP.get(
            _text(candidate.get("research_confidence_level")).upper()
        )
        if mapped:
            return mapped
        mapped = CONFIDENCE_LEVEL_MAP.get(_text(candidate.get("score_confidence")).upper())
        if mapped:
            return mapped
    return COMPLETENESS_LOW


def _valuation(
    thesis: Optional[InvestmentThesisView],
    candidate: Optional[Mapping[str, Any]],
    refs: List[ResearchEvidenceRef],
) -> Tuple[str, str]:
    if thesis and thesis.valuation_context:
        classification = THESIS_VALUATION_MAP.get(
            thesis.valuation_context, VALUATION_UNKNOWN
        )
        refs.append(
            _ref(
                source_type="investment_thesis",
                source_reference="valuation_context",
                evidence_type="VALUATION",
                observed_at=thesis.as_of,
                statement=thesis.valuation_context,
            )
        )
        metrics = _valuation_metrics(candidate)
        context = thesis.valuation_context
        if metrics:
            context = f"{context}; {metrics}"
        return classification, context
    metrics = _valuation_metrics(candidate)
    if candidate and _text(candidate.get("thesis_valuation_view")):
        refs.append(
            _ref(
                source_type="candidate",
                source_reference="thesis_valuation_view",
                evidence_type="VALUATION",
            )
        )
        text = _text(candidate.get("thesis_valuation_view"))
        if metrics:
            text = f"{text} {metrics}"
        return VALUATION_UNKNOWN, text
    if metrics:
        refs.append(
            _ref(
                source_type="candidate",
                source_reference="valuation_metrics",
                evidence_type="VALUATION",
            )
        )
        return VALUATION_UNKNOWN, metrics
    return VALUATION_UNKNOWN, UNKNOWN


def _valuation_metrics(candidate: Optional[Mapping[str, Any]]) -> str:
    if not candidate:
        return ""
    parts: list[str] = []
    pe = candidate.get("pe_ratio")
    ev = candidate.get("ev_to_ebit")
    pfcf = candidate.get("price_to_fcf")
    if pe not in (None, ""):
        parts.append(f"F/K {pe}")
    if ev not in (None, ""):
        parts.append(f"EV/EBIT {ev}")
    if pfcf not in (None, ""):
        parts.append(f"Fiyat/FCF {pfcf}")
    return ", ".join(parts)


def _quality_context(
    thesis: Optional[InvestmentThesisView],
    candidate: Optional[Mapping[str, Any]],
    refs: List[ResearchEvidenceRef],
) -> str:
    if candidate:
        explanation = _text(candidate.get("quality_explanation"))
        if explanation:
            refs.append(
                _ref(
                    source_type="candidate",
                    source_reference="quality_explanation",
                    evidence_type="QUALITY",
                    statement=explanation,
                )
            )
            return explanation
    if thesis:
        quality_bits = [
            item.statement
            for item in thesis.supporting_evidence
            if item.category in {"PROFITABILITY", "CASH_FLOW", "BALANCE_SHEET", "BUSINESS"}
        ]
        if quality_bits:
            refs.append(
                _ref(
                    source_type="investment_thesis",
                    source_reference="supporting_evidence",
                    evidence_type="QUALITY",
                    observed_at=thesis.as_of,
                )
            )
            return quality_bits[0]
    if candidate and any(
        candidate.get(key) not in (None, "") for key in ("roic", "roe", "roa")
    ):
        refs.append(
            _ref(
                source_type="candidate",
                source_reference="profitability_metrics",
                evidence_type="QUALITY",
            )
        )
        return "Canonical profitability metrics are present (ROIC/ROE/ROA)."
    return UNKNOWN


def _thesis_points(
    thesis: Optional[InvestmentThesisView],
    candidate: Optional[Mapping[str, Any]],
    refs: List[ResearchEvidenceRef],
) -> Tuple[str, ...]:
    points: list[str] = []
    if thesis:
        points.extend(item.statement for item in thesis.supporting_evidence)
        if thesis.thesis_summary:
            points.append(thesis.thesis_summary)
        refs.append(
            _ref(
                source_type="investment_thesis",
                source_reference="supporting_evidence",
                evidence_type="THESIS",
                observed_at=thesis.as_of,
            )
        )
    if candidate:
        points.extend(_as_texts(candidate.get("thesis_strengths")))
        points.extend(_as_texts(candidate.get("memo_strengths")))
        points.extend(_as_texts(candidate.get("positive_reasons")))
        main = _text(candidate.get("main_reason") or candidate.get("investment_thesis"))
        if main:
            points.append(main)
        decision = _text(candidate.get("decision") or candidate.get("decision_label"))
        if decision in ACTIONABLE_DECISIONS:
            points.append(f"Existing NABI evaluation: {decision}")
        refs.append(
            _ref(
                source_type="candidate",
                source_reference="evaluation_and_thesis",
                evidence_type="THESIS",
            )
        )
    return _bounded(points)


def _risk_points(
    thesis: Optional[InvestmentThesisView],
    candidate: Optional[Mapping[str, Any]],
    portfolio_fit: Optional[PortfolioFitAssessment],
    completeness: str,
    valuation_class: str,
    refs: List[ResearchEvidenceRef],
) -> Tuple[str, ...]:
    points: list[str] = []
    if thesis:
        points.extend(item.statement for item in thesis.risks)
        points.extend(item.statement for item in thesis.weakening_evidence)
        refs.append(
            _ref(
                source_type="investment_thesis",
                source_reference="risks",
                evidence_type="RISK",
                observed_at=thesis.as_of,
            )
        )
    if candidate:
        points.extend(_as_texts(candidate.get("thesis_concerns")))
        points.extend(_as_texts(candidate.get("critical_risk")))
        points.extend(_as_texts(candidate.get("decision_top_risks")))
        points.extend(_as_texts(candidate.get("memo_risks")))
        points.extend(_as_texts(candidate.get("hard_flags")))
        refs.append(
            _ref(
                source_type="candidate",
                source_reference="risk_fields",
                evidence_type="RISK",
            )
        )
        if normalize_research_status(candidate.get("research_status")) != "TAMAMLANDI":
            points.append("Research is incomplete.")
    if completeness == COMPLETENESS_LOW:
        points.append("Research completeness is low.")
    if valuation_class == VALUATION_EXPENSIVE:
        points.append("Canonical valuation context is demanding.")
    if portfolio_fit and portfolio_fit.fit == FIT_POOR:
        points.append(portfolio_fit.reason or "Portfolio fit is poor.")
        refs.append(
            _ref(
                source_type="portfolio_fit",
                source_reference="assess_portfolio_fit",
                evidence_type="PORTFOLIO_FIT",
                statement=portfolio_fit.fit,
            )
        )
    return _bounded(points)


def _catalyst_points(
    thesis: Optional[InvestmentThesisView],
    candidate: Optional[Mapping[str, Any]],
    extra: Sequence[ResearchEvidenceRef],
    refs: List[ResearchEvidenceRef],
) -> Tuple[str, ...]:
    points: list[str] = []
    if thesis:
        points.extend(item.description for item in thesis.catalysts)
        if thesis.catalysts:
            refs.append(
                _ref(
                    source_type="investment_thesis",
                    source_reference="catalysts",
                    evidence_type="CATALYST",
                    observed_at=thesis.as_of,
                )
            )
    if candidate:
        points.extend(_as_texts(candidate.get("growth_catalysts")))
        if _as_texts(candidate.get("growth_catalysts")):
            refs.append(
                _ref(
                    source_type="candidate",
                    source_reference="growth_catalysts",
                    evidence_type="CATALYST",
                )
            )
    for item in extra:
        if _text(item.evidence_type).upper() != "CATALYST":
            continue
        statement = _text(item.statement)
        if not statement:
            continue
        points.append(statement)
        refs.append(item)
    return _bounded(points)


def _timing(
    *,
    decision: str,
    completeness: str,
    valuation_class: str,
    thesis: Optional[InvestmentThesisView],
    candidate: Optional[Mapping[str, Any]],
    portfolio_fit: Optional[PortfolioFitAssessment],
    catalysts: Tuple[str, ...],
    refs: List[ResearchEvidenceRef],
) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    why_now: list[str] = []
    why_not: list[str] = []
    watch = decision in WATCH_DECISIONS
    actionable = decision in ACTIONABLE_DECISIONS
    if watch:
        why_not.append("Existing evaluation is İZLE; Research Intelligence does not promote it.")
        refs.append(
            _ref(
                source_type="candidate",
                source_reference="decision",
                evidence_type="OPPORTUNITY_DECISION",
                statement=decision,
            )
        )
    elif actionable:
        why_now.append(f"Existing opportunity decision: {decision}.")
        refs.append(
            _ref(
                source_type="candidate",
                source_reference="decision",
                evidence_type="OPPORTUNITY_DECISION",
                statement=decision,
            )
        )
        if candidate:
            why_now.extend(_as_texts(candidate.get("decision_why_now")))
        if thesis and thesis.thesis_status == "SUPPORTED":
            why_now.append("Existing investment thesis status is SUPPORTED.")
        if valuation_class in THESIS_VALUATION_MAP.values() and valuation_class not in {
            VALUATION_UNKNOWN,
            VALUATION_EXPENSIVE,
        }:
            why_now.append(f"Canonical valuation classification is {valuation_class}.")
        if completeness == COMPLETENESS_HIGH:
            why_now.append("Existing research completeness is HIGH.")
    else:
        if decision:
            why_not.append(f"Existing evaluation is {decision}.")
        else:
            why_not.append("No existing opportunity decision.")

    if completeness != COMPLETENESS_HIGH:
        why_not.append(f"Research completeness is {completeness}.")
    if valuation_class == VALUATION_UNKNOWN:
        why_not.append("Valuation classification is UNKNOWN.")
    elif valuation_class == VALUATION_EXPENSIVE:
        why_not.append("Canonical valuation context is expensive/demanding.")
    if thesis and thesis.thesis_status in {"WEAKENING", "INSUFFICIENT_DATA", "MIXED"}:
        why_not.append(f"Existing thesis status is {thesis.thesis_status}.")
    if not catalysts:
        why_not.append("No evidence-backed catalyst.")
    if portfolio_fit and portfolio_fit.fit == FIT_POOR:
        why_not.append(
            portfolio_fit.reason
            or "Portfolio-fit constraint (explanatory only)."
        )
    if candidate and normalize_research_status(candidate.get("research_status")) != "TAMAMLANDI":
        why_not.append("Research workflow is not complete.")
    return _bounded(why_now), _bounded(why_not)


def _missing(
    thesis: Optional[InvestmentThesisView],
    candidate: Optional[Mapping[str, Any]],
    valuation_class: str,
    catalysts: Tuple[str, ...],
    completeness: str,
) -> Tuple[str, ...]:
    missing: list[str] = []
    if not thesis and not (candidate and _as_texts(candidate.get("thesis_strengths"))):
        missing.append("thesis_evidence")
    if valuation_class == VALUATION_UNKNOWN:
        missing.append("canonical_valuation_classification")
    if not catalysts:
        missing.append("catalyst_evidence")
    if completeness == COMPLETENESS_LOW:
        missing.append("research_completeness")
    if candidate is None:
        missing.append("nabi_evaluation")
    return tuple(missing)


def _empty(
    *,
    symbol: str,
    state: str,
    generated_at: str,
    refs: Sequence[ResearchEvidenceRef] = (),
    missing: Sequence[str] = (),
    completeness: str = COMPLETENESS_LOW,
    why_not: Sequence[str] = (),
) -> ResearchIntelligence:
    return ResearchIntelligence(
        symbol=symbol,
        research_state=state,
        thesis_points=(),
        risk_points=(),
        catalyst_points=(),
        valuation_context=UNKNOWN,
        quality_context=UNKNOWN,
        why_now=(),
        why_not_now=tuple(why_not) if why_not else (),
        research_completeness=completeness,
        missing_evidence=tuple(missing),
        evidence_references=tuple(refs),
        generated_at=generated_at,
        persisted=False,
        investable=False,
        valuation_classification=VALUATION_UNKNOWN,
    )


def build_research_intelligence(
    *,
    symbol: str = "",
    candidate: Optional[Mapping[str, Any]] = None,
    snapshot: Optional[Mapping[str, Any]] = None,
    thesis: Optional[InvestmentThesisView] = None,
    portfolio_fit: Optional[PortfolioFitAssessment] = None,
    extra_evidence: Sequence[ResearchEvidenceRef] = (),
    catalog_status: Optional[str] = None,
    is_etf: Optional[bool] = None,
    now: Optional[datetime] = None,
) -> ResearchIntelligence:
    generated_at = (now or datetime.now(timezone.utc)).isoformat()
    normalized = _symbol_of(symbol, candidate)
    authority = resolve_authoritative_participation(
        normalized,
        candidate=candidate,
        snapshot=snapshot,
        catalog_status=catalog_status,
    )
    gate_ref = _ref(
        source_type="participation_authority",
        source_reference=authority.source,
        evidence_type="PARTICIPATION",
        statement=authority.status or "missing",
    )
    if _is_etf(candidate, normalized, is_etf):
        return _empty(
            symbol=normalized,
            state=RESEARCH_STATE_NOT_APPLICABLE,
            generated_at=generated_at,
            refs=(gate_ref,),
            missing=("equity_company_research",),
            why_not=("Catalog/ETF names stay outside equity Company Research.",),
        )
    if not authority.approved or authority.status != PARTICIPATION_STATUS_UYGUN:
        return _empty(
            symbol=normalized,
            state=RESEARCH_STATE_BLOCKED,
            generated_at=generated_at,
            refs=(gate_ref,),
            missing=("participation_approved",),
            why_not=("Participation is not Uygun; Research Intelligence is not investable.",),
        )

    refs: list[ResearchEvidenceRef] = [gate_ref]
    completeness = _completeness(thesis, candidate)
    valuation_class, valuation_context = _valuation(thesis, candidate, refs)
    quality = _quality_context(thesis, candidate, refs)
    thesis_points = _thesis_points(thesis, candidate, refs)
    catalysts = _catalyst_points(thesis, candidate, extra_evidence, refs)
    risks = _risk_points(
        thesis,
        candidate,
        portfolio_fit,
        completeness,
        valuation_class,
        refs,
    )
    decision = _text((candidate or {}).get("decision") or (candidate or {}).get("decision_label"))
    why_now, why_not_now = _timing(
        decision=decision,
        completeness=completeness,
        valuation_class=valuation_class,
        thesis=thesis,
        candidate=candidate,
        portfolio_fit=portfolio_fit,
        catalysts=catalysts,
        refs=refs,
    )
    missing = _missing(thesis, candidate, valuation_class, catalysts, completeness)
    has_content = bool(
        thesis_points
        or catalysts
        or quality != UNKNOWN
        or valuation_class != VALUATION_UNKNOWN
    )
    if decision in WATCH_DECISIONS:
        state = RESEARCH_STATE_WATCH
    elif has_content:
        state = RESEARCH_STATE_READY
    else:
        state = RESEARCH_STATE_INSUFFICIENT
        if not why_not_now:
            why_not_now = (INSUFFICIENT,)
    seen: set[tuple[str, str, str]] = set()
    unique_refs: list[ResearchEvidenceRef] = []
    for item in refs:
        key = (item.source_type, item.source_reference, item.evidence_type)
        if key in seen:
            continue
        seen.add(key)
        unique_refs.append(item)
    return ResearchIntelligence(
        symbol=normalized,
        research_state=state,
        thesis_points=thesis_points,
        risk_points=risks,
        catalyst_points=catalysts,
        valuation_context=valuation_context or UNKNOWN,
        quality_context=quality,
        why_now=why_now,
        why_not_now=why_not_now,
        research_completeness=completeness,
        missing_evidence=missing,
        evidence_references=tuple(unique_refs),
        generated_at=generated_at,
        persisted=False,
        investable=True,
        valuation_classification=valuation_class,
    )


def present_research_intelligence_brief(
    view: ResearchIntelligence,
) -> Optional[ResearchIntelligenceBrief]:
    if not view.investable or view.research_state in {
        RESEARCH_STATE_BLOCKED,
        RESEARCH_STATE_NOT_APPLICABLE,
        RESEARCH_STATE_INSUFFICIENT,
    }:
        return None
    interesting = " · ".join(view.thesis_points[:2]) or None
    risks = " · ".join(view.risk_points[:2]) or None
    catalysts = " · ".join(view.catalyst_points[:2]) or None
    valuation = None
    if view.valuation_classification != VALUATION_UNKNOWN or (
        view.valuation_context and view.valuation_context != UNKNOWN
    ):
        valuation = f"{view.valuation_classification}"
        if view.valuation_context and view.valuation_context != view.valuation_classification:
            valuation = f"{view.valuation_classification} · {view.valuation_context}"
    timing_parts = []
    if view.why_now:
        timing_parts.append(view.why_now[0])
    if view.why_not_now:
        timing_parts.append(view.why_not_now[0])
    timing = " / ".join(timing_parts) or None
    if not any((interesting, risks, catalysts, valuation, timing)):
        return None
    return ResearchIntelligenceBrief(
        interesting=interesting,
        risks=risks,
        catalysts=catalysts,
        valuation=valuation,
        timing=timing,
    )
