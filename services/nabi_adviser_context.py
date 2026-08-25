"""Build canonical NABI Danışman context. No LLM. No new decision math."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping, Optional, Sequence

from services.candidate_pipeline_presentation import is_actionable_opportunity
from components.portfolio_decision_center_ui import present_action_center
from services.nabi_adviser_contract import (
    INSUFFICIENT_DATA,
    UNKNOWN,
    NabiAdviserContext,
)
from services.nabi_adviser_intent import ParsedAdviserQuestion, parse_adviser_question
from services.nabi_decision_contract import (
    ACTION_BLOCKED_PARTICIPATION,
    ACTION_CONSIDER_NEW_POSITION,
    ACTION_CONSIDER_TOP_UP,
    CandidateInvestmentDecision,
    NabiDecisionV3,
)
from services.nabi_decision_orchestrator import (
    build_nabi_decision_v3,
    evaluate_candidate_investment,
)
from services.nabi_portfolio_fit import assess_portfolio_fit, holding_weights
from services.nabi_recommendation import (
    NABIRecommendation,
    build_nabi_recommendation,
)
from services.participation_authority import resolve_authoritative_participation
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.portfolio_intelligence_enrichment_contract import (
    CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT,
)
from services.research_intelligence_service import build_research_intelligence
from services.wealth_goal_planning import planning_conversion
from services.wealth_new_money_allocation import AllocationPlan, allocate_new_money


def _text(value: Any) -> str:
    return str(value or "").strip()


def _row_by_symbol(
    candidates: Sequence[Mapping[str, Any]], symbol: Optional[str]
) -> Optional[Mapping[str, Any]]:
    if not symbol:
        return None
    needle = symbol.upper()
    for row in candidates:
        if _text(row.get("symbol")).upper() == needle:
            return row
    return {"symbol": needle}


def _decision_dict(item: Optional[CandidateInvestmentDecision]) -> Optional[dict[str, Any]]:
    if item is None:
        return None
    return {
        "symbol": item.symbol,
        "final_action": item.final_action,
        "participation_status": item.participation_status,
        "research_completeness": item.research_completeness,
        "decision_class": item.decision_class or UNKNOWN,
        "nabi_score": item.nabi_score,
        "timing_state": item.timing_state,
        "portfolio_fit": item.portfolio_fit,
        "reason_codes": list(item.reason_codes),
        "why": item.why,
    }


def _recommendation_dict(rec: NABIRecommendation, view: NabiDecisionV3) -> dict[str, Any]:
    return {
        "primary_action": rec.primary_action,
        "action_code": rec.action_code,
        "wealth_action": view.wealth_action,
        "dashboard_primary": view.dashboard_primary,
        "final_action": view.final_action,
        "why_now": rec.why_now,
        "opportunity_line": rec.opportunity_line,
        "summary": rec.summary,
        "opportunity_leader": view.opportunity_leader,
        "deployment_symbol": view.deployment_symbol,
    }


def _goal_dict(goal_dashboard: Any) -> dict[str, Any]:
    if goal_dashboard is None:
        return {"status": UNKNOWN, "copy": INSUFFICIENT_DATA}
    required = getattr(goal_dashboard, "required", None)
    current = getattr(goal_dashboard, "current_plan", None)
    nabi = getattr(goal_dashboard, "nabi", None)
    return {
        "current_monthly": getattr(current, "starting_monthly_label", None),
        "required_monthly": getattr(required, "required_label", None),
        "required_available": bool(getattr(required, "available", False)),
        "status_copy": getattr(current, "status_copy", None),
        "nabi_copy": getattr(nabi, "copy", None),
        "gap_label": getattr(current, "gap_label", None),
    }


def _allocation_dict(plan: Optional[AllocationPlan]) -> dict[str, Any]:
    if plan is None:
        return {"status": UNKNOWN, "copy": INSUFFICIENT_DATA}
    return {
        "input_amount": str(plan.input_amount),
        "currency": plan.currency,
        "total_allocated": str(plan.total_allocated),
        "residual_cash": str(plan.residual_cash),
        "limitations": list(plan.limitations),
        "recommendations": [
            {
                "symbol": item.symbol,
                "existing_or_new": item.existing_or_new,
                "reason_code": item.reason_code,
                "reason_text": item.reason_text,
                "allocated_amount": str(item.allocated_amount),
            }
            for item in plan.recommendations
        ],
        "skipped": [
            {
                "symbol": item.symbol,
                "reason_code": item.reason_code,
            }
            for item in plan.skipped
        ],
    }


def _compose_canonical_answer(
    parsed: ParsedAdviserQuestion,
    *,
    rec: NABIRecommendation,
    view: NabiDecisionV3,
    focus: Optional[CandidateInvestmentDecision],
    comparisons: Sequence[Any],
    goal: dict[str, Any],
    new_money: dict[str, Any],
    weights: Mapping[str, float],
    actionable_count: int,
    participation_status: Optional[str],
) -> str:
    lines: list[str] = []
    intent = parsed.intent
    if intent in {
        "TODAY_RECOMMENDATION",
        "WHY_RECOMMENDATION",
        "GENERAL_NABI",
    }:
        lines.append(f"NABI bugünkü birincil öneri: {rec.primary_action}")
        if rec.why_now:
            lines.append(f"Neden: {rec.why_now}")
        lines.append(rec.opportunity_line)
        if actionable_count == 0:
            lines.append("Şu anda alınabilecek katılım onaylı fırsat yok.")
    elif intent == "GOAL_EXPLAIN":
        lines.append(goal.get("nabi_copy") or goal.get("status_copy") or INSUFFICIENT_DATA)
        if goal.get("current_monthly") and goal.get("required_monthly"):
            lines.append(
                f"Mevcut katkı: {goal['current_monthly']}. "
                f"Gerekli katkı: {goal['required_monthly']}."
            )
    elif intent == "NEW_MONEY_SCENARIO":
        if new_money.get("status") == UNKNOWN:
            lines.append("Yeni para senaryosu için kanonik plan yok; " + INSUFFICIENT_DATA + ".")
        else:
            lines.append(
                f"Kanonik New Money planı {new_money.get('input_amount')} "
                f"{new_money.get('currency')} için hesaplandı."
            )
            recs = new_money.get("recommendations") or []
            if recs:
                for item in recs:
                    lines.append(
                        f"- {item['symbol']}: {item['reason_code']} "
                        f"({item['allocated_amount']} {new_money.get('currency')})"
                    )
            else:
                lines.append("Dağıtılacak onaylı kalem yok; nakit artığı bırakılabilir.")
            lines.append(
                f"Artan nakit: {new_money.get('residual_cash')} {new_money.get('currency')}."
            )
            if new_money.get("limitations"):
                lines.append("Sınırlamalar: " + ", ".join(new_money["limitations"]))
    elif intent == "OPPORTUNITY_COMPARE":
        if not comparisons:
            lines.append("Karşılaştırılacak kanonik fırsat yok; " + INSUFFICIENT_DATA + ".")
        else:
            leader = view.opportunity_leader or comparisons[0].symbol
            lines.append(f"Fırsat sıralamasında birincil aday: {leader}.")
            if view.deployment_symbol and view.deployment_symbol != leader:
                lines.append(
                    f"Portföy uyumu / New Money dağıtımı {view.deployment_symbol} "
                    "adayı tercih edebilir; fırsat sırası değişmez."
                )
            for item in comparisons[:2]:
                lines.append(
                    f"- {item.symbol}: sınıf={item.decision_class or UNKNOWN}, "
                    f"uyum={item.portfolio_fit}, skor={item.nabi_score}"
                )
    elif intent == "PORTFOLIO_FIT":
        symbol = parsed.focus_symbol
        if not symbol:
            lines.append("Odak sembol yok; " + INSUFFICIENT_DATA + ".")
        elif symbol not in weights:
            lines.append(f"{symbol} kanonik portföy ağırlığında yok; {INSUFFICIENT_DATA}.")
        else:
            weight = weights[symbol]
            lines.append(f"{symbol} mevcut ağırlık: %{weight:.1f}.")
            if weight >= CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT:
                lines.append(
                    f"Tekil yoğunluk eşiği %{CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT:.0f} "
                    "üzerinde veya eşit."
                )
            else:
                lines.append("Tekil yoğunluk eşiğinin altında.")
            if focus is not None:
                lines.append(f"Portföy uyumu: {focus.portfolio_fit}.")
    elif intent in {"PARTICIPATION_EXPLAIN", "SYMBOL_EXPLAIN", "RESEARCH_EXPLAIN"}:
        if focus is None:
            lines.append("Sembol için kanonik karar yok; " + INSUFFICIENT_DATA + ".")
        elif focus.final_action == ACTION_BLOCKED_PARTICIPATION or (
            participation_status and participation_status != PARTICIPATION_STATUS_UYGUN
        ):
            lines.append(
                f"{focus.symbol} için Participation {focus.participation_status}. "
                "NABI bunu katılım çözülmeden yatırım önerisi olarak sunamaz."
            )
        else:
            lines.append(
                f"{focus.symbol}: {focus.final_action}. "
                f"{focus.why}"
            )
            if focus.final_action not in {
                ACTION_CONSIDER_NEW_POSITION,
                ACTION_CONSIDER_TOP_UP,
            }:
                lines.append("Bu bir al/sat emri değildir.")
    else:
        lines.append(rec.primary_action)
        if rec.why_now:
            lines.append(rec.why_now)
    return "\n".join(line for line in lines if line)


def build_nabi_adviser_context(
    question: str,
    *,
    candidates: Sequence[Mapping[str, Any]] = (),
    snapshots: Optional[Mapping[str, Mapping[str, Any]]] = None,
    portfolio_view: Any = None,
    decision: Any = None,
    presented_actions: Any = None,
    allocation: Optional[AllocationPlan] = None,
    goal_dashboard: Any = None,
    new_money_brief: Any = None,
    policy: Any = None,
    assets: Sequence[Any] = (),
    positions: Sequence[Any] = (),
    theses: Optional[Mapping[str, Any]] = None,
) -> NabiAdviserContext:
    parsed = parse_adviser_question(question)
    if presented_actions is None and decision is not None:
        presented_actions = present_action_center(decision)
    rec = build_nabi_recommendation(
        candidates=candidates,
        decision=decision,
        presented_actions=presented_actions,
        allocation=allocation,
        goal_dashboard=goal_dashboard,
        portfolio_view=portfolio_view,
        new_money_brief=new_money_brief,
    )
    view = build_nabi_decision_v3(
        candidates=candidates,
        snapshots=snapshots,
        theses=theses,
        allocation=allocation,
        goal_dashboard=goal_dashboard,
        portfolio_view=portfolio_view,
        presented_actions=presented_actions,
        new_money_brief=new_money_brief,
        decision=decision,
        recommendation=rec,
    )
    focus_row = _row_by_symbol(candidates, parsed.focus_symbol)
    focus_snapshot = None
    if parsed.focus_symbol and snapshots:
        focus_snapshot = snapshots.get(parsed.focus_symbol)
    focus_item = None
    research = None
    fit = None
    authority_status = None
    if parsed.focus_symbol:
        authority = resolve_authoritative_participation(
            parsed.focus_symbol,
            candidate=focus_row,
            snapshot=focus_snapshot,
        )
        authority_status = authority.status
        research = build_research_intelligence(
            candidate=focus_row or {"symbol": parsed.focus_symbol},
            snapshot=focus_snapshot,
            thesis=(theses or {}).get(parsed.focus_symbol) if theses else None,
        )
        fit = assess_portfolio_fit(
            focus_row or {"symbol": parsed.focus_symbol},
            portfolio_view=portfolio_view,
            allocation=allocation,
        )
        focus_item = evaluate_candidate_investment(
            focus_row or {"symbol": parsed.focus_symbol},
            snapshot=focus_snapshot,
            thesis=(theses or {}).get(parsed.focus_symbol) if theses else None,
            allocation=allocation,
            portfolio_view=portfolio_view,
        )
    scenario_plan = allocation
    if (
        parsed.intent == "NEW_MONEY_SCENARIO"
        and parsed.scenario_amount
        and portfolio_view is not None
    ):
        conversion = None
        fx_schedule = getattr(goal_dashboard, "fx_schedule", None)
        as_of = getattr(goal_dashboard, "as_of_date", None)
        if fx_schedule is not None:
            year = getattr(as_of, "year", None)
            rate = fx_schedule.usdtry_for_year(year) if year is not None else None
            conversion = planning_conversion(
                rate,
                contribution_currency=parsed.scenario_currency or "TRY",
            )
        scenario_plan = allocate_new_money(
            available_amount=Decimal(parsed.scenario_amount),
            amount_currency=parsed.scenario_currency or "TRY",
            portfolio_view=portfolio_view,
            policy=policy,
            candidates=candidates,
            conversion=conversion,
            assets=assets,
            positions=positions,
        )
    comparisons = rec.comparisons
    if parsed.compare_symbols:
        wanted = {item.upper() for item in parsed.compare_symbols}
        filtered = tuple(item for item in comparisons if item.symbol in wanted)
        if filtered:
            comparisons = filtered
    weights = holding_weights(portfolio_view)
    actionable = sum(1 for row in candidates if is_actionable_opportunity(row))
    new_money = _allocation_dict(scenario_plan)
    goal = _goal_dict(goal_dashboard)
    canonical = _compose_canonical_answer(
        parsed,
        rec=rec,
        view=view,
        focus=focus_item,
        comparisons=comparisons,
        goal=goal,
        new_money=new_money,
        weights=weights,
        actionable_count=actionable,
        participation_status=authority_status or (
            focus_item.participation_status if focus_item else None
        ),
    )
    limitations = list(rec.limitations)
    if research is not None and research.missing_evidence:
        limitations.extend(research.missing_evidence)
    evidence = rec.evidence_refs
    if focus_item is not None:
        evidence = tuple(dict.fromkeys((*evidence, *focus_item.reason_codes)))
    return NabiAdviserContext(
        question=parsed.question,
        intent=parsed.intent,
        focus_symbol=parsed.focus_symbol,
        current_recommendation=_recommendation_dict(rec, view),
        wealth_context={
            "dashboard_primary": view.dashboard_primary,
            "wealth_action": view.wealth_action,
        },
        goal_context=goal,
        new_money_context=new_money,
        candidate_decision=_decision_dict(focus_item),
        participation_status=authority_status
        or (focus_item.participation_status if focus_item else None),
        research_intelligence=(
            {
                "research_state": research.research_state,
                "research_completeness": research.research_completeness,
                "valuation_classification": research.valuation_classification,
                "investable": research.investable,
            }
            if research is not None
            else None
        ),
        portfolio_fit=(
            {"fit": fit.fit, "reason": fit.reason, "reason_codes": list(fit.reason_codes)}
            if fit is not None
            else None
        ),
        opportunity_comparison=tuple(
            {
                "symbol": item.symbol,
                "classification": item.decision_class,
                "nabi_score": item.nabi_score,
                "portfolio_fit": item.portfolio_fit,
            }
            for item in comparisons
        ),
        reason_codes=tuple(view.audit.reason_codes),
        evidence_refs=evidence,
        limitations=tuple(dict.fromkeys(limitations)),
        canonical_answer=canonical,
    )
