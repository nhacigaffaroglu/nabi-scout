"""Deterministic opportunity comparison. No new score.

Company quality (decision class, NABI Score, research) stays separate from
portfolio suitability. Comparison rank is company-quality lexicographic order.
Portfolio fit does not override attractiveness in that order.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence, Tuple

from config.participation_catalog import is_configured_participation_symbol
from services.candidate_pipeline_presentation import (
    ACTIONABLE_DECISIONS,
    display_nabi_score,
    is_actionable_opportunity,
    participation_is_blocked,
    participation_is_unresolved,
)
from services.nabi_portfolio_fit import (
    FIT_GOOD,
    FIT_POOR,
    PortfolioFitAssessment,
    assess_portfolio_fit,
)
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.research_workflow_service import normalize_research_status
from services.wealth_new_money_allocation import AllocationPlan

MAX_COMPARISON = 3

RANKING_POLICY = (
    "Katılım ve değerlendirme geçerliliği süzgecinden sonra sıra: "
    "karar sınıfı (GÜÇLÜ ADAY > ADAY), geçerli NABI Score, araştırma tamamlığı, sembol. "
    "Portföy uyumu şirket kalitesi sırasını değiştirmez; yeni para / birincil ekleme "
    "kararında ayrı kullanılır."
)


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


def comparison_halal_eligible(candidate: Mapping[str, Any]) -> bool:
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


@dataclass(frozen=True)
class OpportunityComparison:
    symbol: str
    participation_status: str
    decision_class: Optional[str]
    nabi_score: Optional[float]
    evaluation_completeness: Optional[float]
    research_status: Optional[str]
    research_complete: bool
    portfolio_fit: str
    fit_reason_codes: Tuple[str, ...]
    current_position: bool
    current_weight: Optional[float]
    post_allocation_weight_pct: Optional[float]
    affordability: str
    strengths: Tuple[str, ...]
    risks: Tuple[str, ...]
    limitations: Tuple[str, ...]
    rank: int
    rank_reason: str
    fit_reason: str


def company_rank_key(row: Mapping[str, Any]) -> tuple:
    strong = 0 if _decision_label(row) == "GÜÇLÜ ADAY" else 1
    score = display_nabi_score(row)
    rank_score = score if score is not None else -1.0
    research = 0 if _research_complete(row) else 1
    return (strong, -rank_score, research, _symbol(row))


def _strengths(row: Mapping[str, Any], fit: PortfolioFitAssessment) -> Tuple[str, ...]:
    items: list[str] = []
    decision = _decision_label(row)
    if decision:
        items.append(decision)
    score = display_nabi_score(row)
    if score is not None:
        items.append(f"NABI Score {score:.1f}")
    thesis = _text(row.get("main_reason") or row.get("investment_thesis"))
    if thesis:
        items.append(thesis)
    if fit.fit == FIT_GOOD:
        items.append(fit.reason)
    return tuple(items[:3])


def _risks(row: Mapping[str, Any], fit: PortfolioFitAssessment) -> Tuple[str, ...]:
    items: list[str] = []
    risk = _text(row.get("critical_risk"))
    if risk:
        items.append(risk)
    if fit.fit == FIT_POOR:
        items.append(fit.reason)
    if not _research_complete(row):
        items.append("Araştırma tamamlanmadı.")
    return tuple(items[:3])


def _rank_reason(row: Mapping[str, Any], rank: int, ahead: Optional[Mapping[str, Any]]) -> str:
    decision = _decision_label(row) or "ADAY"
    score = display_nabi_score(row)
    score_label = f"{score:.1f}" if score is not None else "—"
    if rank == 1:
        return (
            f"{decision} ve geçerli NABI Score {score_label} "
            "diğer katılım onaylı adaylardan önde."
        )
    if ahead is None:
        return f"{decision}; sıra karar sınıfı ve NABI Score ile belirlendi."
    ahead_score = display_nabi_score(ahead)
    ahead_label = f"{ahead_score:.1f}" if ahead_score is not None else "—"
    return (
        f"{_symbol(ahead)} daha yüksek karar sınıfı veya NABI Score ({ahead_label}) "
        f"taşıyor; {_symbol(row)} {score_label}."
    )


def build_opportunity_comparisons(
    eligible: Sequence[Mapping[str, Any]],
    *,
    portfolio_view: Any = None,
    allocation: Optional[AllocationPlan] = None,
    limit: int = MAX_COMPARISON,
) -> Tuple[OpportunityComparison, ...]:
    ordered = sorted(
        (row for row in eligible if comparison_halal_eligible(row)),
        key=company_rank_key,
    )
    items: list[OpportunityComparison] = []
    for index, row in enumerate(ordered[: max(0, limit)]):
        fit = assess_portfolio_fit(
            row, portfolio_view=portfolio_view, allocation=allocation
        )
        ahead = ordered[0] if index else None
        items.append(
            OpportunityComparison(
                symbol=_symbol(row),
                participation_status=_text(row.get("participation_status")) or "Uygun",
                decision_class=_decision_label(row) or None,
                nabi_score=display_nabi_score(row),
                evaluation_completeness=_completeness(row),
                research_status=_text(row.get("research_status")) or None,
                research_complete=_research_complete(row),
                portfolio_fit=fit.fit,
                fit_reason_codes=fit.reason_codes,
                current_position=fit.current_holding,
                current_weight=fit.current_weight_pct,
                post_allocation_weight_pct=fit.post_allocation_weight_pct,
                affordability=fit.affordability,
                strengths=_strengths(row, fit),
                risks=_risks(row, fit),
                limitations=fit.limitations,
                rank=index + 1,
                rank_reason=_rank_reason(row, index + 1, ahead if index else None),
                fit_reason=fit.reason,
            )
        )
    return tuple(items)


def best_deploy_comparison(
    comparisons: Sequence[OpportunityComparison],
) -> Optional[OpportunityComparison]:
    deployable = [
        item
        for item in comparisons
        if item.portfolio_fit != FIT_POOR
        and item.affordability != "UNAFFORDABLE"
    ]
    if not deployable:
        return None
    good = [item for item in deployable if item.portfolio_fit == FIT_GOOD]
    pool = good or deployable
    return pool[0]


def compare_with_alternative(
    leader: OpportunityComparison,
    alternative: Optional[OpportunityComparison],
) -> Optional[str]:
    if alternative is None or alternative.symbol == leader.symbol:
        return None
    if leader.portfolio_fit == FIT_POOR and alternative.portfolio_fit != FIT_POOR:
        return (
            f"{leader.symbol} yatırım kalitesi açısından öne çıkıyor; ancak mevcut "
            f"portföy uyumu nedeniyle {alternative.symbol} yeni para için daha dengeli olabilir."
        )
    return (
        f"{alternative.symbol} {leader.symbol} karşısında daha düşük karar sınıfı "
        f"veya NABI Score taşıdığı için geride."
    )


def existing_vs_new_copy(
    *,
    deploy_decision: str,
    has_new_opportunity: bool,
    has_top_up: bool,
) -> Optional[str]:
    if deploy_decision == "DEPLOY_EXISTING" and has_new_opportunity:
        return "Yeni pozisyon açmak yerine mevcut pozisyonu artırmak daha uygun."
    if deploy_decision == "DEPLOY_NEW" and has_top_up:
        return (
            "Mevcut uygun pozisyonları artırmak yerine yeni fırsat çeşitlendirmeyi iyileştiriyor."
        )
    if deploy_decision in {"HOLD_CASH", "NO_SAFE_PLAN"} and not has_new_opportunity:
        return "Şu anda ikisi de yeterince güçlü değil."
    if deploy_decision == "SPLIT":
        return "Mevcut pozisyon tamamlama ile yeni fırsat birlikte değerlendirilebilir."
    return None
