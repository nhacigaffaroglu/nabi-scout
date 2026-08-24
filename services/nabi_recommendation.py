"""NABI intelligence recommendation v1. Orchestration only; no new scoring math.

Composes canonical Decision Intelligence, New Money Allocation, opportunities,
portfolio fit, and participation authority. Advisory; not execution. LLM is not used.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence, Tuple

from components.portfolio_decision_center_ui import CONTRIBUTION_PLAN_TITLE
from services.candidate_pipeline_presentation import (
    display_nabi_score,
)
from services.nabi_opportunity_comparison import (
    OpportunityComparison,
    RANKING_POLICY,
    best_deploy_comparison,
    build_opportunity_comparisons,
    company_rank_key,
    compare_with_alternative,
    comparison_halal_eligible,
    existing_vs_new_copy,
)
from services.nabi_portfolio_fit import (
    FIT_GOOD,
    FIT_NEUTRAL,
    FIT_POOR,
    FIT_UNKNOWN,
    assess_portfolio_fit,
    fit_label_tr,
    holding_weights,
)
from services.participation_intelligence_contract import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    PARTICIPATION_STATUS_UYGUN,
)
from services.portfolio_decision_intelligence import (
    DecisionCategory,
    DecisionPriority,
    PortfolioDecisionView,
)
from services.research_workflow_service import normalize_research_status
from services.wealth_new_money_allocation import (
    REASON_CANDIDATE,
    REASON_EXISTING_HOLDING_TOPUP,
    REASON_STRONG_CANDIDATE,
    AllocationPlan,
)

ACTION_NO_ACTION = "NO_ACTION"
ACTION_REVIEW_GOAL_PLAN = "REVIEW_GOAL_PLAN"
ACTION_REVIEW_NEW_MONEY = "REVIEW_NEW_MONEY"
ACTION_RESEARCH_OPPORTUNITY = "RESEARCH_OPPORTUNITY"
ACTION_CONSIDER_NEW_POSITION = "CONSIDER_NEW_POSITION"
ACTION_CONSIDER_TOP_UP = "CONSIDER_TOP_UP"
ACTION_HOLD_CURRENT_PORTFOLIO = "HOLD_CURRENT_PORTFOLIO"

DEPLOY_EXISTING = "DEPLOY_EXISTING"
DEPLOY_NEW = "DEPLOY_NEW"
DEPLOY_SPLIT = "SPLIT"
DEPLOY_HOLD_CASH = "HOLD_CASH"
DEPLOY_NO_SAFE_PLAN = "NO_SAFE_PLAN"

WEALTH_PAGE = "pages/10_Wealth.py"
FIRSATLAR_PAGE = "pages/5_Firsatlar.py"
SECTION_RECOMMENDATION = "NABI ÖNERİSİ"
WEALTH_CTA = "Wealth"
FIRSATLAR_CTA = "Fırsatlar"

NO_APPROVED_HALAL_OPPORTUNITY = (
    "Şu anda katılım onaylı, yatırım eşiğini aşan fırsat yok."
)
FEATURED_OPPORTUNITY_TEMPLATE = "Bugün öne çıkan fırsat: {symbol}"
POOR_FIT_NOT_PRIMARY = (
    "{symbol} katılım onaylı bir aday; portföy uyumu zayıf olduğu için birincil ekleme değil."
)
RANKING_LIMITATION = (
    "Fırsat sıralaması yeni skor üretmez; mevcut karar sınıfı, geçerli NABI Score, "
    "araştırma tamamlığı ve sembol sırasını kullanır. Portföy uyumu bu sırayı değiştirmez. "
    "Çapraz faktör ağırlığı yoktur."
)

OUTCOME_HORIZONS = ("7D", "30D", "90D", "1Y")
OUTCOME_STATES = (
    "OUTPERFORMED",
    "UNDERPERFORMED",
    "NEUTRAL",
    "INSUFFICIENT_HISTORY",
)
OUTCOME_TRACKING_LIMITATION = (
    "Outcome tracking is designed only. No benchmark, return series, or retroactive "
    "scoring is computed. Future states require a later persistence and market-data layer."
)

_ACTION_SUMMARY = {
    ACTION_NO_ACTION: "Bugün işlem yapma.",
    ACTION_REVIEW_GOAL_PLAN: "Katkı planını gözden geçir.",
    ACTION_REVIEW_NEW_MONEY: "Yeni para dağılımını incele.",
    ACTION_RESEARCH_OPPORTUNITY: "Öne çıkan fırsatı araştır.",
    ACTION_CONSIDER_NEW_POSITION: "Yeni pozisyonu değerlendir.",
    ACTION_CONSIDER_TOP_UP: "Mevcut pozisyonu artırmayı değerlendir.",
    ACTION_HOLD_CURRENT_PORTFOLIO: "Mevcut portföyü koru.",
}

_CONFIDENCE_TR = {
    CONFIDENCE_HIGH: "Yüksek",
    CONFIDENCE_MEDIUM: "Orta",
    CONFIDENCE_LOW: "Düşük",
}

_DATA_BLOCKER_IDS = frozenset({"incomplete_valuation", "missing_planning_fx"})
_PLAN_GAP_ID = "contribution_plan_below_required"
_CONCENTRATION_ID = "concentration_review"


@dataclass(frozen=True)
class RecommendationOpportunity:
    symbol: str
    classification: Optional[str]
    nabi_score: Optional[float]
    research_complete: bool
    completeness: Optional[float]
    current_holding: bool
    current_weight_pct: Optional[float]


@dataclass(frozen=True)
class NewMoneyIntelligence:
    amount_label: Optional[str]
    allocated_label: Optional[str]
    residual_label: Optional[str]
    use_all: bool
    use_some: bool
    leave_residual: bool
    top_up_symbols: Tuple[str, ...]
    new_opportunity_symbols: Tuple[str, ...]
    no_valid_deployment: bool
    forced_full_allocation: bool
    limitation: Optional[str]
    preview_symbols: Tuple[str, ...]
    deploy_decision: str


@dataclass(frozen=True)
class RecommendationCardCopy:
    section_title: str
    today: str
    why: str
    new_money: str
    opportunity: str
    risk: str
    confidence: str
    wealth_cta: str
    firsatlar_cta: str
    featured_symbol: Optional[str] = None
    featured_why: Optional[str] = None
    featured_fit_label: Optional[str] = None
    alternative_line: Optional[str] = None
    existing_vs_new: Optional[str] = None
    alternative_symbol: Optional[str] = None


@dataclass(frozen=True)
class RecommendationAuditRecord:
    recommendation_id: str
    generated_at: Optional[str]
    primary_action: str
    symbol: Optional[str]
    participation_status: Optional[str]
    decision_class: Optional[str]
    nabi_score: Optional[float]
    portfolio_fit: str
    fit_reasons: Tuple[str, ...]
    confidence: str
    wealth_snapshot_reference: Optional[str]
    goal_reference: Optional[str]
    evaluation_reference: Optional[str]
    research_reference: Optional[str]
    participation_snapshot_reference: Optional[str]
    recommendation_reason_codes: Tuple[str, ...]
    persisted: bool = False


@dataclass(frozen=True)
class NABIRecommendation:
    primary_action: str
    action_code: str
    summary: str
    why_now: str
    why_not: Optional[str]
    confidence: str
    confidence_reason: str
    portfolio_fit: str
    portfolio_fit_reason: str
    halal_status: str
    halal_evidence: str
    opportunity: Optional[RecommendationOpportunity]
    symbol: Optional[str]
    classification: Optional[str]
    nabi_score: Optional[float]
    new_money_amount: Optional[str]
    recommended_allocation_preview: Tuple[str, ...]
    goal_impact: Optional[str]
    risk_flags: Tuple[str, ...]
    limitations: Tuple[str, ...]
    evidence_refs: Tuple[str, ...]
    destination: str
    destination_label: str
    new_money: NewMoneyIntelligence
    opportunity_line: str
    risk_line: str
    new_money_line: str
    comparisons: Tuple[OpportunityComparison, ...] = ()
    deploy_decision: str = DEPLOY_NO_SAFE_PLAN
    existing_vs_new: Optional[str] = None
    fit_reason_codes: Tuple[str, ...] = ()
    post_allocation_weight_pct: Optional[float] = None
    alternative_line: Optional[str] = None
    featured_why: Optional[str] = None
    audit: Optional[RecommendationAuditRecord] = None


def _text(value: Any) -> str:
    return str(value or "").strip()


def _symbol(row: Mapping[str, Any]) -> str:
    return _text(row.get("symbol")).upper()


def _decision_label(row: Mapping[str, Any]) -> str:
    return _text(row.get("decision") or row.get("decision_label"))


def _completeness(row: Mapping[str, Any]) -> Optional[float]:
    raw = row.get("data_completeness")
    if raw in (None, ""):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _research_complete(row: Mapping[str, Any]) -> bool:
    return normalize_research_status(row.get("research_status")) == "TAMAMLANDI"


def confidence_label_tr(level: str) -> str:
    return _CONFIDENCE_TR.get(level, level)


def recommendation_halal_eligible(candidate: Mapping[str, Any]) -> bool:
    """Hard firewall: only Uygun or configured catalog ETFs may be recommended."""
    return comparison_halal_eligible(candidate)


def rank_recommendation_opportunities(
    candidates: Sequence[Mapping[str, Any]],
) -> Tuple[Mapping[str, Any], ...]:
    """Company-quality lexicographic rank. Portfolio fit does not reorder this list.

    Order after participation/evaluation eligibility:
    GÜÇLÜ ADAY > ADAY, then valid NABI Score, then research completeness, then symbol.
    Completeness percent is not a weight; no cross-factor score is invented.
    """
    eligible = [row for row in candidates if recommendation_halal_eligible(row)]
    eligible.sort(key=company_rank_key)
    return tuple(eligible)


def _action_by_id(
    decision: Optional[PortfolioDecisionView], action_id: str
) -> Optional[Any]:
    if decision is None:
        return None
    if decision.primary_action.id == action_id:
        return decision.primary_action
    for action in decision.actions:
        if action.id == action_id:
            return action
    return None


def _has_data_blocker(decision: Optional[PortfolioDecisionView]) -> bool:
    if decision is None:
        return False
    action = decision.primary_action
    if action.id in _DATA_BLOCKER_IDS:
        return True
    if (
        action.category == DecisionCategory.DATA
        and action.priority in {DecisionPriority.CRITICAL, DecisionPriority.HIGH}
    ):
        return True
    return False


def _has_plan_gap(
    decision: Optional[PortfolioDecisionView],
    presented_actions: Any = None,
) -> bool:
    if _action_by_id(decision, _PLAN_GAP_ID) is not None:
        return True
    if presented_actions is None:
        return False
    if getattr(presented_actions, "healthy", False):
        return False
    for action in getattr(presented_actions, "visible_actions", ()) or ():
        title = _text(getattr(action, "title", None))
        action_id = _text(getattr(action, "id", None))
        if title == CONTRIBUTION_PLAN_TITLE or action_id in {
            _PLAN_GAP_ID,
            "contrib",
        }:
            return True
    return False


def _has_concentration_signal(decision: Optional[PortfolioDecisionView]) -> bool:
    return _action_by_id(decision, _CONCENTRATION_ID) is not None


def _holding_map(portfolio_view: Any) -> dict[str, float]:
    return holding_weights(portfolio_view)


def evaluate_portfolio_fit(
    candidate: Optional[Mapping[str, Any]],
    *,
    portfolio_view: Any = None,
    allocation: Optional[AllocationPlan] = None,
) -> Tuple[str, str]:
    assessment = assess_portfolio_fit(
        candidate, portfolio_view=portfolio_view, allocation=allocation
    )
    return assessment.fit, assessment.reason


def _deploy_decision(
    *,
    allocation: Optional[AllocationPlan],
    top_up: Tuple[str, ...],
    new_syms: Tuple[str, ...],
    allocated: Any,
    no_plan: bool,
    limitation: Optional[str],
) -> str:
    if allocation is None:
        return DEPLOY_NO_SAFE_PLAN
    try:
        allocated_value = float(allocated)
    except (TypeError, ValueError):
        allocated_value = 0.0
    if allocated_value <= 0:
        return DEPLOY_NO_SAFE_PLAN if (no_plan or limitation) else DEPLOY_HOLD_CASH
    if top_up and new_syms:
        return DEPLOY_SPLIT
    if top_up:
        return DEPLOY_EXISTING
    if new_syms:
        return DEPLOY_NEW
    return DEPLOY_HOLD_CASH


def _build_new_money(
    allocation: Optional[AllocationPlan],
    brief: Any = None,
) -> NewMoneyIntelligence:
    amount_label = getattr(brief, "amount_label", None) if brief is not None else None
    allocated_label = getattr(brief, "allocated_label", None) if brief is not None else None
    residual_label = getattr(brief, "residual_label", None) if brief is not None else None
    unavailable = getattr(brief, "unavailable_reason", None) if brief is not None else None
    brief_symbols = tuple(
        _text(getattr(row, "symbol", None)).upper()
        for row in (getattr(brief, "recommendations", None) or ())
        if _text(getattr(row, "symbol", None))
    )

    if allocation is None:
        no_plan = bool(unavailable) and not brief_symbols
        return NewMoneyIntelligence(
            amount_label=amount_label,
            allocated_label=allocated_label,
            residual_label=residual_label,
            use_all=False,
            use_some=bool(brief_symbols),
            leave_residual=bool(residual_label) and residual_label not in {"0", "0 TL"},
            top_up_symbols=(),
            new_opportunity_symbols=(),
            no_valid_deployment=no_plan,
            forced_full_allocation=False,
            limitation=unavailable,
            preview_symbols=brief_symbols[:3],
            deploy_decision=DEPLOY_NO_SAFE_PLAN,
        )

    top_up = tuple(
        _text(item.symbol).upper()
        for item in allocation.recommendations
        if item.reason_code == REASON_EXISTING_HOLDING_TOPUP
    )
    new_syms = tuple(
        _text(item.symbol).upper()
        for item in allocation.recommendations
        if item.reason_code in {REASON_STRONG_CANDIDATE, REASON_CANDIDATE}
    )
    preview = tuple(
        _text(item.symbol).upper() for item in allocation.recommendations[:3]
    )
    allocated = allocation.total_allocated
    residual = allocation.residual_cash
    input_amount = allocation.input_amount
    use_all = allocated > 0 and residual == 0
    use_some = allocated > 0 and residual > 0
    limitation = None
    if allocation.limitations:
        limitation = allocation.limitations[0]
    elif unavailable:
        limitation = unavailable
    no_deploy = allocated <= 0
    return NewMoneyIntelligence(
        amount_label=amount_label or f"{input_amount} {allocation.currency}",
        allocated_label=allocated_label or str(allocated),
        residual_label=residual_label or str(residual),
        use_all=use_all,
        use_some=use_some,
        leave_residual=residual > 0,
        top_up_symbols=top_up,
        new_opportunity_symbols=new_syms,
        no_valid_deployment=no_deploy,
        forced_full_allocation=False,
        limitation=limitation,
        preview_symbols=preview or brief_symbols[:3],
        deploy_decision=_deploy_decision(
            allocation=allocation,
            top_up=top_up,
            new_syms=new_syms,
            allocated=allocated,
            no_plan=no_deploy,
            limitation=limitation,
        ),
    )


def _goal_bits(goal_dashboard: Any) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    if goal_dashboard is None:
        return None, None, None
    current = None
    required = None
    reach = None
    plan = getattr(goal_dashboard, "current_plan", None)
    if plan is not None:
        current = _text(getattr(plan, "starting_monthly_label", None)) or None
    req = getattr(goal_dashboard, "required", None)
    if req is not None:
        required = _text(getattr(req, "required_label", None)) or None
    alt = getattr(goal_dashboard, "target_date_alternative", None)
    if alt is not None:
        year = getattr(alt, "reach_year", None)
        reach = str(year) if year is not None else _text(getattr(alt, "reach_date_label", None)) or None
    return current, required, reach


def _new_money_line(money: NewMoneyIntelligence) -> str:
    if money.limitation and money.no_valid_deployment:
        return money.limitation
    if money.no_valid_deployment:
        return "Güvenli bir yeni para dağıtımı üretilemedi."
    amount = money.amount_label or "aylık katkı"
    if money.use_all and money.preview_symbols:
        return f"{amount} için öneri: tümü → " + " · ".join(money.preview_symbols)
    if money.use_some and money.preview_symbols:
        residual = money.residual_label or "kalan nakit"
        return (
            f"{amount} için kısmi dağılım: "
            + " · ".join(money.preview_symbols)
            + f" · kalan {residual}."
        )
    if money.top_up_symbols:
        return "Mevcut pozisyonlara tamamlama önizlemesi: " + " · ".join(money.top_up_symbols)
    if money.preview_symbols:
        return f"{amount} için dağılım önizlemesi: " + " · ".join(money.preview_symbols)
    return f"{amount} için dağılım önizlemesi mevcut."


def _destination_for(action_code: str) -> Tuple[str, str]:
    if action_code in {
        ACTION_RESEARCH_OPPORTUNITY,
        ACTION_CONSIDER_NEW_POSITION,
    }:
        return FIRSATLAR_PAGE, FIRSATLAR_CTA
    return WEALTH_PAGE, WEALTH_CTA


def present_recommendation_card(rec: NABIRecommendation) -> RecommendationCardCopy:
    featured = rec.comparisons[0] if rec.comparisons else None
    alternative = rec.comparisons[1] if len(rec.comparisons) > 1 else None
    return RecommendationCardCopy(
        section_title=SECTION_RECOMMENDATION,
        today=rec.summary,
        why=rec.why_now,
        new_money=rec.new_money_line,
        opportunity=rec.opportunity_line,
        risk=rec.risk_line or "Belirgin ek risk bayrağı yok.",
        confidence=confidence_label_tr(rec.confidence),
        wealth_cta=WEALTH_CTA,
        firsatlar_cta=FIRSATLAR_CTA,
        featured_symbol=featured.symbol if featured else None,
        featured_why=rec.featured_why,
        featured_fit_label=fit_label_tr(featured.portfolio_fit) if featured else None,
        alternative_line=rec.alternative_line,
        existing_vs_new=rec.existing_vs_new,
        alternative_symbol=alternative.symbol if alternative else None,
    )


def opportunity_intelligence_summary(rec: NABIRecommendation) -> str:
    return rec.opportunity_line


def _audit_id(
    *,
    action_code: str,
    symbol: Optional[str],
    fit: str,
    confidence: str,
    opportunity_line: str,
    fit_reasons: Tuple[str, ...],
) -> str:
    payload = "|".join(
        (
            action_code,
            symbol or "",
            fit,
            confidence,
            opportunity_line,
            ",".join(fit_reasons),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def build_recommendation_audit_record(
    *,
    action_code: str,
    symbol: Optional[str],
    participation_status: Optional[str],
    decision_class: Optional[str],
    nabi_score: Optional[float],
    portfolio_fit: str,
    fit_reasons: Tuple[str, ...],
    confidence: str,
    opportunity_line: str,
    reason_codes: Tuple[str, ...],
    wealth_snapshot_reference: Optional[str] = None,
    goal_reference: Optional[str] = None,
    evaluation_reference: Optional[str] = None,
    research_reference: Optional[str] = None,
    participation_snapshot_reference: Optional[str] = None,
) -> RecommendationAuditRecord:
    return RecommendationAuditRecord(
        recommendation_id=_audit_id(
            action_code=action_code,
            symbol=symbol,
            fit=portfolio_fit,
            confidence=confidence,
            opportunity_line=opportunity_line,
            fit_reasons=fit_reasons,
        ),
        generated_at=None,
        primary_action=action_code,
        symbol=symbol,
        participation_status=participation_status,
        decision_class=decision_class,
        nabi_score=nabi_score,
        portfolio_fit=portfolio_fit,
        fit_reasons=fit_reasons,
        confidence=confidence,
        wealth_snapshot_reference=wealth_snapshot_reference,
        goal_reference=goal_reference,
        evaluation_reference=evaluation_reference,
        research_reference=research_reference,
        participation_snapshot_reference=participation_snapshot_reference,
        recommendation_reason_codes=reason_codes,
        persisted=False,
    )


def _opportunity_from_row(
    row: Mapping[str, Any],
    holdings: Mapping[str, float],
) -> RecommendationOpportunity:
    symbol = _symbol(row)
    return RecommendationOpportunity(
        symbol=symbol,
        classification=_decision_label(row) or None,
        nabi_score=display_nabi_score(row),
        research_complete=_research_complete(row),
        completeness=_completeness(row),
        current_holding=symbol in holdings,
        current_weight_pct=holdings.get(symbol),
    )


def build_nabi_recommendation(
    *,
    candidates: Sequence[Mapping[str, Any]] = (),
    decision: Optional[PortfolioDecisionView] = None,
    presented_actions: Any = None,
    allocation: Optional[AllocationPlan] = None,
    goal_dashboard: Any = None,
    portfolio_view: Any = None,
    new_money_brief: Any = None,
    valuation_complete: Optional[bool] = None,
) -> NABIRecommendation:
    ranked = rank_recommendation_opportunities(candidates)
    holdings = _holding_map(portfolio_view)
    comparisons = build_opportunity_comparisons(
        ranked,
        portfolio_view=portfolio_view,
        allocation=allocation,
    )
    featured_row = ranked[0] if ranked else None
    leader = comparisons[0] if comparisons else None
    deploy = best_deploy_comparison(comparisons)
    alternative = comparisons[1] if len(comparisons) > 1 else None
    if leader is not None:
        fit = leader.portfolio_fit
        fit_reason = leader.fit_reason
        fit_codes = leader.fit_reason_codes
        post_weight = leader.post_allocation_weight_pct
    else:
        fit, fit_reason = evaluate_portfolio_fit(
            None, portfolio_view=portfolio_view, allocation=allocation
        )
        fit_codes = ()
        post_weight = None
    featured = (
        _opportunity_from_row(featured_row, holdings) if featured_row is not None else None
    )
    action_target = None
    action_fit_reason = fit_reason
    if deploy is not None:
        deploy_row = next(
            (row for row in ranked if _symbol(row) == deploy.symbol),
            None,
        )
        if deploy_row is not None:
            action_target = _opportunity_from_row(deploy_row, holdings)
            action_fit_reason = deploy.fit_reason

    money = _build_new_money(allocation, new_money_brief)
    current_monthly, required_monthly, reach_year = _goal_bits(goal_dashboard)
    data_blocker = _has_data_blocker(decision)
    if valuation_complete is False:
        data_blocker = True
    plan_gap = _has_plan_gap(decision, presented_actions)
    concentration = _has_concentration_signal(decision)
    promote_opportunity = action_target is not None and not data_blocker
    top_up_available = bool(money.top_up_symbols) and not money.no_valid_deployment
    alternative_line = (
        compare_with_alternative(leader, alternative) if leader is not None else None
    )
    featured_why = leader.rank_reason if leader is not None else None

    if data_blocker:
        action_code = ACTION_NO_ACTION
        why_now = "Kritik servet veya kur kanıtı tamam değil; işlem önerisi üretilmedi."
        why_not = "Eksik değerleme ile alım/satım yönlendirmesi yapılmaz."
    elif plan_gap:
        action_code = ACTION_REVIEW_GOAL_PLAN
        why_now = "2031 hedefi için mevcut katkı planı gerekli hızın altında."
        why_not = "Önce plan boşluğu kapanmadan yeni işlem birincil öneri değil."
    elif promote_opportunity and action_target is not None and not action_target.research_complete:
        action_code = ACTION_RESEARCH_OPPORTUNITY
        why_now = (
            f"{action_target.symbol} katılım onaylı ve yatırım eşiğini aşıyor; "
            "araştırma tamam değil."
        )
        why_not = None
    elif promote_opportunity and action_target is not None and action_target.current_holding:
        action_code = ACTION_CONSIDER_TOP_UP
        why_now = f"{action_target.symbol} mevcut pozisyon ve katılım onaylı fırsat."
        why_not = None
    elif promote_opportunity and action_target is not None:
        action_code = ACTION_CONSIDER_NEW_POSITION
        why_now = f"{action_target.symbol} katılım onaylı. {action_fit_reason}"
        why_not = None
    elif top_up_available:
        action_code = ACTION_REVIEW_NEW_MONEY
        why_now = "Katılım eşiğini aşan yeni fırsat yok; mevcut açık katman tamamlanabilir."
        why_not = None
    elif concentration:
        action_code = ACTION_HOLD_CURRENT_PORTFOLIO
        why_now = "Portföyde yoğunluk incelemesi açık; yeni ekleme birincil değil."
        why_not = "Yoğunluk sinyali varken yeni pozisyon öne çıkarılmaz."
    else:
        action_code = ACTION_NO_ACTION
        why_now = "Karar eşiğini aşan bir işlem yok."
        why_not = "Zorunlu işlem yok; beklemek geçerli bir sonuç."

    vs_new = None
    if comparisons and action_code in {
        ACTION_CONSIDER_NEW_POSITION,
        ACTION_CONSIDER_TOP_UP,
        ACTION_REVIEW_NEW_MONEY,
        ACTION_NO_ACTION,
        ACTION_HOLD_CURRENT_PORTFOLIO,
    }:
        vs_new = existing_vs_new_copy(
            deploy_decision=money.deploy_decision,
            has_new_opportunity=bool(money.new_opportunity_symbols)
            or any(not item.current_position for item in comparisons),
            has_top_up=bool(money.top_up_symbols),
        )

    evidence: list[str] = []
    if current_monthly:
        evidence.append(f"Mevcut aylık katkı: {current_monthly}")
    if required_monthly:
        evidence.append(f"Gerekli başlangıç aylık katkı: {required_monthly}")
    if reach_year:
        evidence.append(f"Tahmini ulaşma: {reach_year}")
    evidence.append(
        NO_APPROVED_HALAL_OPPORTUNITY
        if featured is None
        else f"Öne çıkan fırsat: {featured.symbol} ({featured.classification or '—'})"
    )
    if not concentration:
        evidence.append("Kritik tekil pozisyon yoğunlaşması sinyali yok.")
    if money.preview_symbols:
        evidence.append("Yeni para önizleme: " + " · ".join(money.preview_symbols))
    elif money.limitation:
        evidence.append(money.limitation)
    evidence.append(RANKING_LIMITATION)
    evidence.append(RANKING_POLICY)
    if alternative_line:
        evidence.append(alternative_line)
    if vs_new:
        evidence.append(vs_new)
    evidence = [item for item in evidence if item]

    limitations: list[str] = [RANKING_LIMITATION]
    risk_flags: list[str] = []
    if data_blocker or valuation_complete is False:
        limitations.append("Değerleme veya planlama kur kanıtı eksik.")
        risk_flags.append("incomplete_valuation")
    if decision is not None:
        limitations.extend(str(item) for item in decision.limitations if item)
    if money.limitation:
        limitations.append(money.limitation)
    research_subject = action_target if promote_opportunity and action_target else featured
    if research_subject is not None and not research_subject.research_complete:
        limitations.append(f"{research_subject.symbol} araştırması tamamlanmadı.")
        risk_flags.append("incomplete_research")
    if featured is not None and fit == FIT_POOR:
        risk_flags.append("poor_portfolio_fit")
    if leader is not None:
        limitations.extend(leader.limitations)

    complete_valuation = valuation_complete is not False
    if decision is not None:
        complete_valuation = complete_valuation and decision.evidence_complete
    if data_blocker or valuation_complete is False:
        confidence = CONFIDENCE_LOW
        confidence_reason = "Kanıt eksik; güven düşük."
    elif (
        research_subject is not None
        and not research_subject.research_complete
        and promote_opportunity
    ):
        confidence = CONFIDENCE_MEDIUM
        confidence_reason = "Katılım çözülmüş; araştırma tamamlanmadığı için güven orta."
    elif complete_valuation:
        confidence = CONFIDENCE_HIGH
        confidence_reason = "Katılım ve kanonik plan/değerleme kanıtı yeterli."
    else:
        confidence = CONFIDENCE_MEDIUM
        confidence_reason = "Kısmi kanıt; yönlendirme temkinli."

    halal_status = PARTICIPATION_STATUS_UYGUN if featured is not None else "YOK"
    if featured is None:
        halal_evidence = "Birincil öneri katılım reddi/bekleme statüsüne dayanmaz; onaylı fırsat yok."
    else:
        halal_evidence = (
            f"{featured.symbol} katılım Uygun veya katalog ETF; "
            "Uygun Değil / Kontrol Et / Pending önerilmez."
        )

    goal_impact = None
    if plan_gap and current_monthly and required_monthly:
        goal_impact = f"{current_monthly} < {required_monthly}"
    elif reach_year:
        goal_impact = f"Tahmini ulaşma {reach_year}"

    destination, destination_label = _destination_for(action_code)
    if featured is None:
        opportunity_line = NO_APPROVED_HALAL_OPPORTUNITY
    elif fit == FIT_POOR and deploy is None:
        opportunity_line = POOR_FIT_NOT_PRIMARY.format(symbol=featured.symbol)
    else:
        opportunity_line = FEATURED_OPPORTUNITY_TEMPLATE.format(symbol=featured.symbol)
    unique_limitations = tuple(dict.fromkeys(limitations))
    human_risks = [
        item
        for item in unique_limitations
        if item != RANKING_LIMITATION and not item.replace("_", "").isupper()
    ]
    if "incomplete_valuation" in risk_flags:
        human_risks = ["Değerleme kanıtı eksik."] + human_risks
    if "incomplete_research" in risk_flags and research_subject is not None:
        human_risks.append(f"{research_subject.symbol} araştırması tamamlanmadı.")
    if "poor_portfolio_fit" in risk_flags and featured is not None:
        human_risks.append(f"{featured.symbol} portföy uyumu zayıf.")
    risk_line = "; ".join(dict.fromkeys(human_risks)) or None

    reason_codes = tuple(
        dict.fromkeys(
            (
                action_code,
                money.deploy_decision,
                *fit_codes,
            )
        )
    )
    audit = build_recommendation_audit_record(
        action_code=action_code,
        symbol=featured.symbol if featured else None,
        participation_status=leader.participation_status if leader else None,
        decision_class=featured.classification if featured else None,
        nabi_score=featured.nabi_score if featured else None,
        portfolio_fit=fit,
        fit_reasons=fit_codes,
        confidence=confidence,
        opportunity_line=opportunity_line,
        reason_codes=reason_codes,
        wealth_snapshot_reference="portfolio_view" if portfolio_view is not None else None,
        goal_reference="goal_dashboard" if goal_dashboard is not None else None,
        evaluation_reference=featured.symbol if featured else None,
        research_reference=(
            f"{research_subject.symbol}:"
            f"{'TAMAMLANDI' if research_subject.research_complete else 'OPEN'}"
            if research_subject is not None
            else None
        ),
        participation_snapshot_reference=(
            f"{leader.symbol}:{leader.participation_status}" if leader is not None else None
        ),
    )

    return NABIRecommendation(
        primary_action=_ACTION_SUMMARY[action_code],
        action_code=action_code,
        summary=_ACTION_SUMMARY[action_code],
        why_now=why_now,
        why_not=why_not,
        confidence=confidence,
        confidence_reason=confidence_reason,
        portfolio_fit=fit,
        portfolio_fit_reason=fit_reason,
        halal_status=halal_status,
        halal_evidence=halal_evidence,
        opportunity=featured,
        symbol=featured.symbol if featured else None,
        classification=featured.classification if featured else None,
        nabi_score=featured.nabi_score if featured else None,
        new_money_amount=money.amount_label,
        recommended_allocation_preview=money.preview_symbols,
        goal_impact=goal_impact,
        risk_flags=tuple(dict.fromkeys(risk_flags)),
        limitations=unique_limitations,
        evidence_refs=tuple(evidence),
        destination=destination,
        destination_label=destination_label,
        new_money=money,
        opportunity_line=opportunity_line,
        risk_line=risk_line,
        new_money_line=_new_money_line(money),
        comparisons=comparisons,
        deploy_decision=money.deploy_decision,
        existing_vs_new=vs_new,
        fit_reason_codes=fit_codes,
        post_allocation_weight_pct=post_weight,
        alternative_line=alternative_line,
        featured_why=featured_why,
        audit=audit,
    )
