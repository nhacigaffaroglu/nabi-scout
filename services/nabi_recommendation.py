"""NABI intelligence recommendation v1. Orchestration only; no new scoring math.

Composes canonical Decision Intelligence, New Money Allocation, opportunities,
and participation authority. Advisory; not execution. LLM is not used.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence, Tuple

from config.participation_catalog import is_configured_participation_symbol
from components.portfolio_decision_center_ui import CONTRIBUTION_PLAN_TITLE
from services.candidate_pipeline_presentation import (
    ACTIONABLE_DECISIONS,
    display_nabi_score,
    is_actionable_opportunity,
    participation_is_blocked,
    participation_is_unresolved,
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
from services.portfolio_intelligence_enrichment_contract import (
    CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT,
)
from services.research_workflow_service import normalize_research_status
from services.wealth_new_money_allocation import (
    REASON_CANDIDATE,
    REASON_EXISTING_HOLDING_TOPUP,
    REASON_OVERWEIGHT_LAYER,
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

FIT_GOOD = "GOOD_FIT"
FIT_NEUTRAL = "NEUTRAL_FIT"
FIT_POOR = "POOR_FIT"
FIT_UNKNOWN = "UNKNOWN"

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
    "Fırsat sıralaması yeni skor üretmez; mevcut karar sınıfı, geçerli NABI Score "
    "ve sembol sırasını kullanır. Çapraz faktör ağırlığı yoktur."
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
_NEW_MONEY_REASON_CODES = frozenset(
    {REASON_EXISTING_HOLDING_TOPUP, REASON_STRONG_CANDIDATE, REASON_CANDIDATE}
)


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
    symbol = _symbol(candidate)
    if not symbol:
        return False
    if participation_is_blocked(candidate):
        return False
    catalog = is_configured_participation_symbol(symbol)
    if participation_is_unresolved(candidate) and not catalog:
        return False
    status = _text(candidate.get("participation_status"))
    if not catalog and status != PARTICIPATION_STATUS_UYGUN:
        return False
    if _decision_label(candidate) not in ACTIONABLE_DECISIONS:
        return False
    return is_actionable_opportunity(candidate)


def rank_recommendation_opportunities(
    candidates: Sequence[Mapping[str, Any]],
) -> Tuple[Mapping[str, Any], ...]:
    """Lexicographic: GÜÇLÜ ADAY > ADAY, then valid NABI Score, then symbol.

    Completeness is not a weight; it is not used for ranking because no canonical
    cross-factor model exists. Same family as Fırsatlar today-card order.
    """
    eligible = [row for row in candidates if recommendation_halal_eligible(row)]

    def _key(row: Mapping[str, Any]) -> tuple:
        strong = 0 if _decision_label(row) == "GÜÇLÜ ADAY" else 1
        score = display_nabi_score(row)
        rank_score = score if score is not None else -1.0
        return (strong, -rank_score, _symbol(row))

    eligible.sort(key=_key)
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
    weights: dict[str, float] = {}
    if portfolio_view is None:
        return weights
    for row in getattr(portfolio_view, "priced_positions", None) or ():
        symbol = _text(getattr(row, "symbol", None)).upper()
        weight = getattr(row, "weight_pct", None)
        if not symbol or weight is None:
            continue
        try:
            weights[symbol] = float(weight)
        except (TypeError, ValueError):
            continue
    return weights


def _skipped_overweight(allocation: Optional[AllocationPlan], symbol: str) -> bool:
    if allocation is None:
        return False
    return any(
        _text(item.symbol).upper() == symbol and item.reason_code == REASON_OVERWEIGHT_LAYER
        for item in allocation.skipped
    )


def _allocation_promotes(allocation: Optional[AllocationPlan], symbol: str) -> bool:
    if allocation is None:
        return False
    return any(
        _text(item.symbol).upper() == symbol
        and item.reason_code in _NEW_MONEY_REASON_CODES
        for item in allocation.recommendations
    )


def evaluate_portfolio_fit(
    candidate: Optional[Mapping[str, Any]],
    *,
    portfolio_view: Any = None,
    allocation: Optional[AllocationPlan] = None,
) -> Tuple[str, str]:
    if candidate is None:
        return FIT_UNKNOWN, "Değerlendirilecek fırsat yok."
    symbol = _symbol(candidate)
    holdings = _holding_map(portfolio_view)
    weight = holdings.get(symbol)
    held = symbol in holdings
    if _skipped_overweight(allocation, symbol):
        return FIT_POOR, f"{symbol} açık katmanda fazla ağırlıkta; yeni ekleme uygun değil."
    if weight is not None and weight >= CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT:
        return (
            FIT_POOR,
            f"{symbol} mevcut ağırlık %{weight:.1f}; tekil yoğunluk eşiği "
            f"%{CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT:.0f}.",
        )
    if _allocation_promotes(allocation, symbol):
        if held:
            return FIT_GOOD, f"{symbol} mevcut pozisyon; açık katmanda tamamlanabilir."
        return FIT_GOOD, f"{symbol} yeni para dağılımında uygun aday."
    if held and weight is not None:
        return FIT_NEUTRAL, f"{symbol} portföyde %{weight:.1f} ağırlıkta."
    if portfolio_view is None and allocation is None:
        return FIT_UNKNOWN, "Portföy uyumu için dağılım kanıtı yok."
    if not held:
        return FIT_NEUTRAL, f"{symbol} mevcut pozisyon değil; yoğunluk eşiği aşılmıyor."
    return FIT_UNKNOWN, "Portföy uyumu belirsiz."


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


def _opportunity_line(
    featured: Optional[RecommendationOpportunity],
    *,
    fit: str,
    promoted: bool,
) -> str:
    if featured is None:
        return NO_APPROVED_HALAL_OPPORTUNITY
    if not promoted and fit == FIT_POOR:
        return POOR_FIT_NOT_PRIMARY.format(symbol=featured.symbol)
    return FEATURED_OPPORTUNITY_TEMPLATE.format(symbol=featured.symbol)


def _destination_for(action_code: str) -> Tuple[str, str]:
    if action_code in {
        ACTION_RESEARCH_OPPORTUNITY,
        ACTION_CONSIDER_NEW_POSITION,
    }:
        return FIRSATLAR_PAGE, FIRSATLAR_CTA
    return WEALTH_PAGE, WEALTH_CTA


def present_recommendation_card(rec: NABIRecommendation) -> RecommendationCardCopy:
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
    )


def opportunity_intelligence_summary(rec: NABIRecommendation) -> str:
    return rec.opportunity_line


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
    featured_row = ranked[0] if ranked else None
    fit, fit_reason = evaluate_portfolio_fit(
        featured_row,
        portfolio_view=portfolio_view,
        allocation=allocation,
    )
    featured = None
    if featured_row is not None:
        symbol = _symbol(featured_row)
        featured = RecommendationOpportunity(
            symbol=symbol,
            classification=_decision_label(featured_row) or None,
            nabi_score=display_nabi_score(featured_row),
            research_complete=_research_complete(featured_row),
            completeness=_completeness(featured_row),
            current_holding=symbol in holdings,
            current_weight_pct=holdings.get(symbol),
        )

    money = _build_new_money(allocation, new_money_brief)
    current_monthly, required_monthly, reach_year = _goal_bits(goal_dashboard)
    data_blocker = _has_data_blocker(decision)
    if valuation_complete is False:
        data_blocker = True
    plan_gap = _has_plan_gap(decision, presented_actions)
    concentration = _has_concentration_signal(decision)
    promote_opportunity = (
        featured is not None
        and fit != FIT_POOR
        and not data_blocker
    )
    top_up_available = bool(money.top_up_symbols) and not money.no_valid_deployment

    if data_blocker:
        action_code = ACTION_NO_ACTION
        why_now = "Kritik servet veya kur kanıtı tamam değil; işlem önerisi üretilmedi."
        why_not = "Eksik değerleme ile alım/satım yönlendirmesi yapılmaz."
    elif plan_gap:
        action_code = ACTION_REVIEW_GOAL_PLAN
        why_now = "2031 hedefi için mevcut katkı planı gerekli hızın altında."
        why_not = "Önce plan boşluğu kapanmadan yeni işlem birincil öneri değil."
    elif promote_opportunity and featured is not None and not featured.research_complete:
        action_code = ACTION_RESEARCH_OPPORTUNITY
        why_now = f"{featured.symbol} katılım onaylı ve yatırım eşiğini aşıyor; araştırma tamam değil."
        why_not = None
    elif promote_opportunity and featured is not None and featured.current_holding:
        action_code = ACTION_CONSIDER_TOP_UP
        why_now = f"{featured.symbol} mevcut pozisyon ve katılım onaylı fırsat."
        why_not = None
    elif promote_opportunity and featured is not None:
        action_code = ACTION_CONSIDER_NEW_POSITION
        why_now = f"{featured.symbol} katılım onaylı. {fit_reason}"
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
    if featured is not None and not featured.research_complete:
        limitations.append(f"{featured.symbol} araştırması tamamlanmadı.")
        risk_flags.append("incomplete_research")
    if featured is not None and fit == FIT_POOR:
        risk_flags.append("poor_portfolio_fit")

    complete_valuation = valuation_complete is not False
    if decision is not None:
        complete_valuation = complete_valuation and decision.evidence_complete
    if data_blocker or valuation_complete is False:
        confidence = CONFIDENCE_LOW
        confidence_reason = "Kanıt eksik; güven düşük."
    elif featured is not None and not featured.research_complete and promote_opportunity:
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
    opportunity_line = _opportunity_line(
        featured, fit=fit, promoted=promote_opportunity
    )
    unique_limitations = tuple(dict.fromkeys(limitations))
    human_risks = [
        item
        for item in unique_limitations
        if item != RANKING_LIMITATION and not item.replace("_", "").isupper()
    ]
    if "incomplete_valuation" in risk_flags:
        human_risks = ["Değerleme kanıtı eksik."] + human_risks
    if "incomplete_research" in risk_flags and featured is not None:
        human_risks.append(f"{featured.symbol} araştırması tamamlanmadı.")
    if "poor_portfolio_fit" in risk_flags and featured is not None:
        human_risks.append(f"{featured.symbol} portföy uyumu zayıf.")
    risk_line = "; ".join(dict.fromkeys(human_risks)) or None

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
    )
