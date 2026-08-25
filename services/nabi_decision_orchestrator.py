"""NABI Decision Orchestrator v3. Composes canonical engines; no new score.

Locked precedence: Participation → evidence completeness → attractiveness →
timing → portfolio fit → wealth/new money → final recommendation.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence, Tuple

from config.participation_catalog import is_configured_participation_symbol
from services.candidate_pipeline_presentation import ACTIONABLE_DECISIONS, display_nabi_score
from services.investment_thesis_contract import InvestmentThesisView
from services.nabi_decision_contract import (
    ACTION_BLOCKED_PARTICIPATION,
    ACTION_CONSIDER_NEW_POSITION,
    ACTION_CONSIDER_TOP_UP,
    ACTION_NO_ACTION,
    ACTION_RESEARCH_FIRST,
    ACTION_WAIT,
    ACTION_WATCH,
    CandidateInvestmentDecision,
    DECISION_PRECEDENCE,
    DecisionAuditRecord,
    DecisionV3Brief,
    FIT_PRESENTATION,
    NabiDecisionV3,
    REASON_ATTRACTIVENESS_WATCH,
    REASON_DEPLOY_NEW,
    REASON_DEPLOY_TOP_UP,
    REASON_EVIDENCE_LOW,
    REASON_EVIDENCE_MEDIUM,
    REASON_EXTERNAL_SIGNAL_NOT_AUTHORITY,
    REASON_FIT_POOR,
    REASON_NO_DEPLOYMENT_SUPPORT,
    REASON_PARTICIPATION_BLOCKED,
    REASON_TIMING_FAVORABLE,
    REASON_TIMING_NEUTRAL,
    REASON_TIMING_UNKNOWN,
    REASON_TIMING_WAIT,
    REASON_WEALTH_PRIORITY,
    TIMING_FAVORABLE,
    TIMING_NEUTRAL,
    TIMING_UNKNOWN,
    TIMING_WAIT,
)
from services.nabi_recommendation_history_contract import logical_event_identity
from services.nabi_opportunity_comparison import best_deploy_comparison
from services.nabi_portfolio_fit import (
    FIT_POOR,
    assess_portfolio_fit,
)
from services.nabi_recommendation import (
    ACTION_REVIEW_GOAL_PLAN,
    ACTION_REVIEW_NEW_MONEY,
    NABIRecommendation,
    build_nabi_recommendation,
    rank_recommendation_opportunities,
)
from services.participation_authority import resolve_authoritative_participation
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.research_intelligence_contract import (
    COMPLETENESS_HIGH,
    COMPLETENESS_LOW,
    COMPLETENESS_MEDIUM,
    RESEARCH_STATE_INSUFFICIENT,
    RESEARCH_STATE_NOT_APPLICABLE,
    VALUATION_ATTRACTIVE,
    VALUATION_EXPENSIVE,
    VALUATION_FAIR,
    VALUATION_UNKNOWN,
    ResearchEvidenceRef,
    ResearchIntelligence,
)
from services.research_intelligence_service import build_research_intelligence
from services.wealth_new_money_allocation import (
    REASON_CANDIDATE,
    REASON_EXISTING_HOLDING_TOPUP,
    REASON_STRONG_CANDIDATE,
    AllocationPlan,
)

WATCH_DECISIONS = frozenset({"İZLE", "IZLE"})
WEALTH_PRIORITY_ACTIONS = frozenset({ACTION_REVIEW_GOAL_PLAN, ACTION_REVIEW_NEW_MONEY})
_PROMOTE_NEW = frozenset({REASON_STRONG_CANDIDATE, REASON_CANDIDATE})


def _text(value: Any) -> str:
    return str(value or "").strip()


def _symbol(row: Mapping[str, Any]) -> str:
    return _text(row.get("symbol")).upper()


def _decision_class(row: Mapping[str, Any]) -> str:
    return _text(row.get("decision") or row.get("decision_label"))


def _is_catalog_etf(row: Mapping[str, Any], symbol: str) -> bool:
    return bool(
        row.get("is_etf")
        or _text(row.get("asset_type")).upper() == "ETF"
        or is_configured_participation_symbol(symbol)
    )


def derive_timing_state(research: ResearchIntelligence) -> str:
    """Deterministic timing from Research Intelligence only. No momentum engine."""
    if research.research_completeness == COMPLETENESS_LOW or research.research_state in {
        RESEARCH_STATE_INSUFFICIENT,
        RESEARCH_STATE_NOT_APPLICABLE,
    }:
        return TIMING_UNKNOWN
    if research.valuation_classification == VALUATION_EXPENSIVE:
        return TIMING_WAIT
    if research.why_now and research.valuation_classification in {
        VALUATION_ATTRACTIVE,
        VALUATION_FAIR,
    }:
        return TIMING_FAVORABLE
    if research.research_completeness in {COMPLETENESS_HIGH, COMPLETENESS_MEDIUM} and (
        research.thesis_points or research.quality_context not in {"", "UNKNOWN"}
    ):
        if research.valuation_classification == VALUATION_UNKNOWN:
            return TIMING_UNKNOWN
        return TIMING_NEUTRAL
    return TIMING_UNKNOWN


def _allocation_support(
    symbol: str,
    allocation: Optional[AllocationPlan],
) -> Optional[str]:
    if allocation is None:
        return None
    for item in allocation.recommendations:
        if _text(item.symbol).upper() != symbol:
            continue
        if item.reason_code == REASON_EXISTING_HOLDING_TOPUP:
            return ACTION_CONSIDER_TOP_UP
        if item.reason_code in _PROMOTE_NEW:
            return ACTION_CONSIDER_NEW_POSITION
    return None


def _timing_reason(timing: str) -> str:
    if timing == TIMING_FAVORABLE:
        return REASON_TIMING_FAVORABLE
    if timing == TIMING_NEUTRAL:
        return REASON_TIMING_NEUTRAL
    if timing == TIMING_WAIT:
        return REASON_TIMING_WAIT
    return REASON_TIMING_UNKNOWN


def evaluate_candidate_investment(
    candidate: Mapping[str, Any],
    *,
    snapshot: Optional[Mapping[str, Any]] = None,
    thesis: Optional[InvestmentThesisView] = None,
    extra_evidence: Sequence[ResearchEvidenceRef] = (),
    allocation: Optional[AllocationPlan] = None,
    portfolio_view: Any = None,
    now: Optional[datetime] = None,
) -> CandidateInvestmentDecision:
    symbol = _symbol(candidate)
    authority = resolve_authoritative_participation(
        symbol,
        candidate=candidate,
        snapshot=snapshot,
        catalog_status=None,
    )
    research = build_research_intelligence(
        candidate=candidate,
        snapshot=snapshot,
        thesis=thesis,
        extra_evidence=extra_evidence,
        now=now,
    )
    fit = assess_portfolio_fit(
        candidate, portfolio_view=portfolio_view, allocation=allocation
    )
    timing = derive_timing_state(research)
    reasons: list[str] = []
    if extra_evidence:
        reasons.append(REASON_EXTERNAL_SIGNAL_NOT_AUTHORITY)
    decision = _decision_class(candidate)
    catalog = _is_catalog_etf(candidate, symbol)

    if not authority.approved or authority.status != PARTICIPATION_STATUS_UYGUN:
        reasons.append(REASON_PARTICIPATION_BLOCKED)
        action = ACTION_BLOCKED_PARTICIPATION
        why = "Participation is not Uygun; no downstream signal may bypass this gate."
    elif (
        not catalog
        and (
            research.research_completeness == COMPLETENESS_LOW
            or research.research_state == RESEARCH_STATE_INSUFFICIENT
        )
    ):
        reasons.append(REASON_EVIDENCE_LOW)
        action = ACTION_RESEARCH_FIRST
        why = "Halal-approved but Research Intelligence completeness is LOW/INSUFFICIENT."
    elif decision in WATCH_DECISIONS or decision not in ACTIONABLE_DECISIONS:
        reasons.append(REASON_ATTRACTIVENESS_WATCH)
        action = ACTION_WATCH
        why = "Approved and researched attractiveness is insufficient for deployment."
    elif timing == TIMING_WAIT:
        reasons.append(REASON_TIMING_WAIT)
        action = ACTION_WAIT
        why = "Attractive candidate, but Research Intelligence timing argues against acting now."
    elif timing == TIMING_UNKNOWN:
        reasons.append(REASON_TIMING_UNKNOWN)
        action = ACTION_WAIT
        why = "Attractive candidate, but timing evidence is UNKNOWN."
    elif fit.fit == FIT_POOR:
        reasons.append(REASON_FIT_POOR)
        action = ACTION_WAIT
        why = fit.reason or "Portfolio-fit / concentration context argues against deployment now."
    else:
        if research.research_completeness == COMPLETENESS_MEDIUM:
            reasons.append(REASON_EVIDENCE_MEDIUM)
        reasons.append(_timing_reason(timing))
        deploy = _allocation_support(symbol, allocation)
        if deploy == ACTION_CONSIDER_TOP_UP:
            reasons.append(REASON_DEPLOY_TOP_UP)
            action = ACTION_CONSIDER_TOP_UP
            why = f"{symbol} has canonical top-up support."
        elif deploy == ACTION_CONSIDER_NEW_POSITION:
            reasons.append(REASON_DEPLOY_NEW)
            action = ACTION_CONSIDER_NEW_POSITION
            why = f"{symbol} has canonical new-position support."
        else:
            reasons.append(REASON_NO_DEPLOYMENT_SUPPORT)
            action = ACTION_NO_ACTION
            why = "No canonical New Money / allocation path supports deployment."

    return CandidateInvestmentDecision(
        symbol=symbol,
        final_action=action,
        participation_status=authority.status or "missing",
        research_completeness=research.research_completeness,
        decision_class=decision,
        nabi_score=display_nabi_score(candidate),
        timing_state=timing,
        portfolio_fit=fit.fit,
        reason_codes=tuple(dict.fromkeys(reasons)),
        evidence_references=research.evidence_references,
        why=why,
        investable_research=research.investable,
    )


def _fallback_selected(
    evaluated: Sequence[CandidateInvestmentDecision],
) -> Optional[CandidateInvestmentDecision]:
    """Book-level action when no ranked opportunity exists. Does not invent CONSIDER_*."""
    if not evaluated:
        return None
    order = (
        ACTION_RESEARCH_FIRST,
        ACTION_WATCH,
        ACTION_WAIT,
        ACTION_NO_ACTION,
        ACTION_BLOCKED_PARTICIPATION,
    )
    by_action: dict[str, list[CandidateInvestmentDecision]] = {action: [] for action in order}
    for item in evaluated:
        by_action.setdefault(item.final_action, []).append(item)
    for action in order:
        rows = by_action.get(action) or []
        if rows:
            return rows[0]
    return evaluated[0]


def _audit_id(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def present_decision_v3_brief(view: NabiDecisionV3) -> DecisionV3Brief:
    return DecisionV3Brief(
        final_action=view.final_action,
        timing_state=view.timing_state,
        portfolio_fit=FIT_PRESENTATION.get(view.portfolio_fit, view.portfolio_fit),
        why=view.why,
        symbol=view.deployment_symbol or view.opportunity_leader,
    )


def build_nabi_decision_v3(
    *,
    candidates: Sequence[Mapping[str, Any]] = (),
    snapshots: Optional[Mapping[str, Mapping[str, Any]]] = None,
    theses: Optional[Mapping[str, InvestmentThesisView]] = None,
    extra_evidence: Optional[Mapping[str, Sequence[ResearchEvidenceRef]]] = None,
    decision: Any = None,
    presented_actions: Any = None,
    allocation: Optional[AllocationPlan] = None,
    goal_dashboard: Any = None,
    portfolio_view: Any = None,
    new_money_brief: Any = None,
    valuation_complete: Optional[bool] = None,
    now: Optional[datetime] = None,
    recommendation: Optional[NABIRecommendation] = None,
) -> NabiDecisionV3:
    generated_at = (now or datetime.now(timezone.utc)).isoformat()
    rec = recommendation or build_nabi_recommendation(
        candidates=candidates,
        decision=decision,
        presented_actions=presented_actions,
        allocation=allocation,
        goal_dashboard=goal_dashboard,
        portfolio_view=portfolio_view,
        new_money_brief=new_money_brief,
        valuation_complete=valuation_complete,
    )
    by_symbol = {_symbol(row): row for row in candidates if _symbol(row)}
    snapshots = snapshots or {}
    theses = theses or {}
    extra_evidence = extra_evidence or {}
    evaluated = tuple(
        evaluate_candidate_investment(
            row,
            snapshot=snapshots.get(_symbol(row)),
            thesis=theses.get(_symbol(row)),
            extra_evidence=extra_evidence.get(_symbol(row), ()),
            allocation=allocation,
            portfolio_view=portfolio_view,
            now=now,
        )
        for row in candidates
        if _symbol(row)
    )
    by_decision = {item.symbol: item for item in evaluated}
    ranked = rank_recommendation_opportunities(candidates)
    ranking = tuple(_symbol(row) for row in ranked)
    opportunity_leader = ranking[0] if ranking else None
    deploy = best_deploy_comparison(rec.comparisons)
    deployment_symbol = deploy.symbol if deploy is not None else None

    consider_pool = [
        by_decision[symbol]
        for symbol in ranking
        if symbol in by_decision
        and by_decision[symbol].final_action
        in {ACTION_CONSIDER_NEW_POSITION, ACTION_CONSIDER_TOP_UP}
        and by_decision[symbol].portfolio_fit != FIT_POOR
    ]
    if deployment_symbol and deployment_symbol in by_decision:
        chosen = by_decision[deployment_symbol]
        if chosen.final_action in {ACTION_CONSIDER_NEW_POSITION, ACTION_CONSIDER_TOP_UP}:
            selected = chosen
        elif consider_pool:
            selected = consider_pool[0]
        else:
            selected = chosen
    elif consider_pool:
        selected = consider_pool[0]
    elif opportunity_leader and opportunity_leader in by_decision:
        selected = by_decision[opportunity_leader]
    else:
        selected = _fallback_selected(evaluated)

    if selected is None:
        final_action = ACTION_NO_ACTION
        timing = TIMING_UNKNOWN
        fit = "UNKNOWN"
        why = "No safe or useful investment action."
        reasons: Tuple[str, ...] = (ACTION_NO_ACTION,)
        symbol = None
        participation = None
        completeness = None
        decision_class = None
        score = None
        refs: Tuple[Any, ...] = ()
    else:
        final_action = selected.final_action
        timing = selected.timing_state
        fit = selected.portfolio_fit
        why = selected.why
        reasons = selected.reason_codes
        symbol = selected.symbol
        participation = selected.participation_status
        completeness = selected.research_completeness
        decision_class = selected.decision_class
        score = selected.nabi_score
        refs = selected.evidence_references
        if selected.final_action in {ACTION_CONSIDER_NEW_POSITION, ACTION_CONSIDER_TOP_UP}:
            deployment_symbol = selected.symbol

    wealth_action = rec.action_code
    dashboard_primary = wealth_action
    reason_codes = tuple(dict.fromkeys((*reasons, wealth_action)))
    if wealth_action in WEALTH_PRIORITY_ACTIONS:
        reason_codes = tuple(dict.fromkeys((*reason_codes, REASON_WEALTH_PRIORITY)))

    logical_id = logical_event_identity(
        symbol=symbol,
        final_action=final_action,
        participation_status=participation,
        research_completeness=completeness,
        decision_class=decision_class,
        nabi_score=score,
        timing_state=timing,
        portfolio_fit=fit,
        wealth_action=wealth_action,
        reason_codes=reason_codes,
    )
    audit = DecisionAuditRecord(
        recommendation_id=_audit_id(
            "|".join(
                (
                    final_action,
                    symbol or "",
                    wealth_action,
                    ",".join(reason_codes),
                    generated_at,
                )
            )
        ),
        generated_at=generated_at,
        symbol=symbol,
        final_action=final_action,
        participation_status=participation,
        research_completeness=completeness,
        decision_class=decision_class,
        nabi_score=score,
        timing_state=timing,
        portfolio_fit=fit,
        wealth_action=wealth_action,
        reason_codes=reason_codes,
        evidence_references=refs,
        persisted=False,
        logical_event_id=logical_id,
    )
    return NabiDecisionV3(
        decision_precedence=DECISION_PRECEDENCE,
        opportunity_ranking=ranking,
        opportunity_leader=opportunity_leader,
        deployment_symbol=deployment_symbol,
        final_action=final_action,
        wealth_action=wealth_action,
        dashboard_primary=dashboard_primary,
        timing_state=timing,
        portfolio_fit=fit,
        why=why,
        candidate_decisions=evaluated,
        audit=audit,
        persisted=False,
    )
