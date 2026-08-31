"""Build canonical NABI Danışman context. No LLM. No new decision math."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping, Optional, Sequence, Tuple

from components.portfolio_decision_center_ui import present_action_center
from services.candidate_pipeline_presentation import is_actionable_opportunity
from services.nabi_adviser_contract import (
    AMOUNT_CLARIFICATION,
    AMOUNT_REQUIRED,
    EIGHT_E_VS_NEW_MONEY_COPY,
    INSUFFICIENT_DATA,
    INTENT_GENERAL_NABI,
    INTENT_GOAL_EXPLAIN,
    INTENT_NEW_MONEY_SCENARIO,
    INTENT_OPPORTUNITY_COMPARE,
    INTENT_OPPORTUNITY_STATUS,
    INTENT_PARTICIPATION_EXPLAIN,
    INTENT_PORTFOLIO_FIT,
    INTENT_RESEARCH_EXPLAIN,
    INTENT_SYMBOL_EXPLAIN,
    INTENT_TODAY_RECOMMENDATION,
    INTENT_WHY_RECOMMENDATION,
    NO_ACTIONABLE_OPPORTUNITY,
    NOT_A_TRADE,
    PENDING_NEW_MONEY_AMOUNT,
    REASON_8E_VS_NEW_MONEY_CONFLICT,
    UNKNOWN,
    NabiAdviserContext,
    format_try_display,
    present_action_label,
    present_missing_evidence,
    present_user_text,
)
from services.nabi_adviser_intent import ParsedAdviserQuestion, parse_adviser_question
from services.nabi_decision_contract import (
    ACTION_CONSIDER_NEW_POSITION,
    ACTION_CONSIDER_TOP_UP,
    CandidateInvestmentDecision,
    NabiDecisionV3,
)
from services.nabi_decision_orchestrator import (
    build_nabi_decision_v3,
    evaluate_candidate_investment,
)
from services.nabi_opportunity_comparison import company_rank_key
from services.nabi_portfolio_fit import (
    FIT_POOR,
    assess_portfolio_fit,
    fit_label_tr,
    holding_weights,
)
from services.nabi_recommendation import (
    ACTION_REVIEW_GOAL_PLAN,
    NABIRecommendation,
    build_nabi_recommendation,
)
from services.participation_authority import resolve_authoritative_participation
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)
from services.portfolio_intelligence_enrichment_contract import (
    CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT,
)
from services.research_intelligence_service import build_research_intelligence
from services.exposure_determinacy_diagnostics import (
    build_exposure_diagnostics,
    eligible_fill_assets,
)
from services.portfolio_allocation_intelligence import (
    AllocationDimension,
    build_allocation_intelligence,
)
from services.official_sp_funds_product import resolve_official_fund_mandates
from services.portfolio_economic_exposure import build_economic_exposure
from services.wealth_goal_planning import planning_conversion
from services.hybrid_exposure_allocation_policy import (
    HybridExposureAllocationPolicy,
    NO_ELIGIBLE_FILL_FOR_ROBUST_UNDERWEIGHT_LAYER,
    NO_ROBUST_UNDERWEIGHT_LAYER,
    PORTFOLIO_EXPOSURE_UNAVAILABLE,
    PORTFOLIO_EXPOSURE_UNSAFE,
    first_live_blocker,
    overlay_adviser_hybrid_fields,
    resolve_hybrid_allocation_policy,
    resolve_hybrid_portfolio_mode,
)
from services.portfolio_security_decision_contract import (
    DECISION_INSUFFICIENT_DATA,
    DECISION_WATCH,
    INCREASE_DECISIONS,
    PortfolioSecurityDecision,
)
from services.portfolio_security_decision_service import (
    evaluate_portfolio_security_for_symbol,
    fail_closed_portfolio_security_decision,
)
from services.wealth_contract import normalize_symbol
from services.wealth_new_money_allocation import (
    AllocationPlan,
    _allocation_buckets_from_exposure,
    allocate_new_money,
    fund_symbols_for_mandate_resolution,
    REASON_DATA_INCOMPLETE,
    REASON_FX_REQUIRED,
    REASON_NO_ELIGIBLE_SECURITY,
)

SECURITY_CONSIDER_ACTIONS = frozenset(
    {ACTION_CONSIDER_NEW_POSITION, ACTION_CONSIDER_TOP_UP}
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _index_security_decisions(
    decisions: Sequence[PortfolioSecurityDecision],
) -> dict[str, PortfolioSecurityDecision]:
    return {normalize_symbol(item.symbol): item for item in decisions if normalize_symbol(item.symbol)}


def resolve_adviser_security_decisions(
    symbols: Sequence[str],
    *,
    provided: Sequence[PortfolioSecurityDecision] = (),
    client: Any = None,
    user_id: Optional[str] = None,
) -> Tuple[PortfolioSecurityDecision, ...]:
    """Load 8E via the 8E.4B path. Injected decisions win. Missing symbols fail closed."""
    by_symbol = _index_security_decisions(provided)
    seen: list[str] = []
    out: list[PortfolioSecurityDecision] = []
    for raw in symbols:
        symbol = normalize_symbol(raw)
        if not symbol or symbol in seen:
            continue
        seen.append(symbol)
        if symbol in by_symbol:
            out.append(by_symbol[symbol])
        elif client is not None:
            out.append(
                evaluate_portfolio_security_for_symbol(client, symbol, user_id=user_id)
            )
        else:
            out.append(fail_closed_portfolio_security_decision(symbol))
    return tuple(out)


def _collect_adviser_symbols(
    parsed: ParsedAdviserQuestion,
    rec: Any,
    view: Any,
    allocation: Optional[AllocationPlan],
    new_money: Mapping[str, Any],
) -> list[str]:
    symbols: list[str] = []
    if parsed.focus_symbol:
        symbols.append(parsed.focus_symbol)
    symbols.extend(parsed.compare_symbols or ())
    symbols.extend(parsed.inherited_symbols or ())
    for value in (
        getattr(rec, "symbol", None),
        getattr(view, "deployment_symbol", None),
        getattr(view, "opportunity_leader", None),
    ):
        if value:
            symbols.append(str(value))
    if allocation is not None:
        symbols.extend(item.symbol for item in allocation.recommendations)
    for item in new_money.get("recommendations") or []:
        if item.get("symbol"):
            symbols.append(str(item["symbol"]))
    return symbols


def _collect_new_money_universe_symbols(
    parsed: ParsedAdviserQuestion,
    rec: Any,
    view: Any,
    candidates: Sequence[Mapping[str, Any]],
    portfolio_view: Any,
) -> list[str]:
    symbols = _collect_adviser_symbols(parsed, rec, view, None, {})
    for row in candidates:
        symbol = row.get("symbol") if isinstance(row, Mapping) else None
        if symbol:
            symbols.append(str(symbol))
    if portfolio_view is not None:
        for bucket in (
            getattr(portfolio_view, "priced_positions", ()) or (),
            getattr(portfolio_view, "unpriced_positions", ()) or (),
            getattr(portfolio_view, "foreign_currency_positions", ()) or (),
        ):
            for item in bucket:
                symbol = getattr(item, "symbol", None)
                if symbol:
                    symbols.append(str(symbol))
    return symbols


def _apply_8e_security_authority(
    rec_dict: dict[str, Any],
    rec: Any,
    decisions_by_symbol: Mapping[str, PortfolioSecurityDecision],
) -> dict[str, Any]:
    """Replace CONSIDER_* recommendation/v3 actions with the 8E decision."""
    overlaid = dict(rec_dict)
    symbol = normalize_symbol(
        getattr(rec, "symbol", None) or overlaid.get("deployment_symbol")
    )
    decision = decisions_by_symbol.get(symbol) if symbol else None
    if overlaid.get("action_code") in SECURITY_CONSIDER_ACTIONS:
        if decision is None:
            overlaid["action_code"] = DECISION_INSUFFICIENT_DATA
            overlaid["primary_action"] = present_action_label(DECISION_INSUFFICIENT_DATA)
            overlaid["final_action"] = DECISION_INSUFFICIENT_DATA
            overlaid["exposure_increase_allowed"] = False
        else:
            overlaid["action_code"] = decision.decision
            overlaid["primary_action"] = present_action_label(decision.decision)
            overlaid["final_action"] = decision.decision
            overlaid["exposure_increase_allowed"] = decision.exposure_increase_allowed
            if decision.primary_reasons:
                overlaid["why_now"] = ", ".join(decision.primary_reasons)
    elif overlaid.get("final_action") in SECURITY_CONSIDER_ACTIONS:
        overlaid["final_action"] = (
            decision.decision if decision is not None else DECISION_INSUFFICIENT_DATA
        )
        overlaid["exposure_increase_allowed"] = (
            decision.exposure_increase_allowed if decision is not None else False
        )
    elif decision is not None:
        overlaid["exposure_increase_allowed"] = decision.exposure_increase_allowed
    return overlaid


def overlay_recommendation_with_8e(
    rec: Any,
    decisions: Sequence[PortfolioSecurityDecision],
) -> Any:
    """Reuse 8F.1 overlay on a frozen NABIRecommendation. No new decision math."""
    from dataclasses import replace

    rec_dict = _apply_8e_security_authority(
        {
            "action_code": rec.action_code,
            "primary_action": rec.primary_action,
            "final_action": rec.action_code,
            "deployment_symbol": rec.symbol,
            "why_now": rec.why_now,
        },
        rec,
        _index_security_decisions(decisions),
    )
    if rec_dict["action_code"] == rec.action_code:
        return rec
    return replace(
        rec,
        action_code=rec_dict["action_code"],
        primary_action=rec_dict["primary_action"],
        summary=rec_dict["primary_action"],
        why_now=rec_dict.get("why_now") or rec.why_now,
    )


def _new_money_eight_e_conflicts(
    *,
    allocation: Optional[AllocationPlan],
    new_money: Mapping[str, Any],
    decisions_by_symbol: Mapping[str, PortfolioSecurityDecision],
    authoritative_symbols: Sequence[str] = (),
) -> Tuple[str, ...]:
    if new_money.get("status") == AMOUNT_REQUIRED:
        return ()
    allowed = {normalize_symbol(item) for item in authoritative_symbols if item}
    symbols: list[str] = []
    if allocation is not None:
        symbols.extend(item.symbol for item in allocation.recommendations)
    symbols.extend(
        str(item.get("symbol") or "")
        for item in (new_money.get("recommendations") or [])
    )
    conflicts: list[str] = []
    for raw in symbols:
        symbol = normalize_symbol(raw)
        if allowed and symbol not in allowed:
            continue
        decision = decisions_by_symbol.get(symbol)
        if decision is not None and not decision.exposure_increase_allowed:
            conflicts.append(REASON_8E_VS_NEW_MONEY_CONFLICT)
    return tuple(dict.fromkeys(conflicts))


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


def _decision_dict(
    item: Optional[CandidateInvestmentDecision],
    security: Optional[PortfolioSecurityDecision] = None,
) -> Optional[dict[str, Any]]:
    if item is None and security is None:
        return None
    payload = {
        "symbol": security.symbol if security is not None else item.symbol,
        "final_action": (
            security.decision if security is not None else item.final_action
        ),
        "participation_status": (
            security.participation_status
            if security is not None and security.participation_status
            else (item.participation_status if item is not None else None)
        ),
        "research_completeness": item.research_completeness if item is not None else None,
        "decision_class": (item.decision_class or UNKNOWN) if item is not None else UNKNOWN,
        "nabi_score": item.nabi_score if item is not None else None,
        "timing_state": item.timing_state if item is not None else None,
        "portfolio_fit": item.portfolio_fit if item is not None else None,
        "reason_codes": list(item.reason_codes) if item is not None else [],
        "why": item.why if item is not None else "",
    }
    if security is not None:
        payload["security_action"] = security.decision
        payload["exposure_increase_allowed"] = security.exposure_increase_allowed
        payload["blocking_reasons"] = list(security.blocking_reasons)
        payload["research_allowed"] = security.research_allowed
    return payload


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
    header = getattr(goal_dashboard, "header", None)
    goal = getattr(goal_dashboard, "goal", None)
    target_date = getattr(goal, "target_date", None) if goal is not None else None
    target_year = getattr(target_date, "year", None)
    required_available = bool(getattr(required, "available", False))
    difference = getattr(required, "difference_label", None) if required_available else None
    return {
        "current_monthly": getattr(current, "starting_monthly_label", None),
        "required_monthly": getattr(required, "required_label", None) if required_available else None,
        "required_available": required_available,
        "status_copy": getattr(current, "status_copy", None),
        "nabi_copy": getattr(nabi, "copy", None),
        "gap_label": getattr(current, "gap_label", None),
        "contribution_gap": difference,
        "target_year": str(target_year) if target_year else None,
        "progress": getattr(header, "progress_caption", None),
        "target_label": getattr(header, "target_wealth_label", None),
    }


def _economic_exposure_context(
    *,
    portfolio_view: Any,
    policy: Any,
    new_money: Mapping[str, Any],
    fund_snapshots: Optional[Mapping[str, Any]] = None,
    security_master: Any = None,
    identity_service: Any = None,
    assets: Sequence[Any] = (),
    positions: Sequence[Any] = (),
    candidates: Sequence[Mapping[str, Any]] = (),
    hybrid_policy: Optional[HybridExposureAllocationPolicy] = None,
) -> Optional[dict[str, Any]]:
    if portfolio_view is None or policy is None:
        return None
    exposure = build_economic_exposure(
        portfolio_view,
        fund_snapshots=fund_snapshots,
        fund_mandates=resolve_official_fund_mandates(
            fund_symbols_for_mandate_resolution(portfolio_view, candidates=candidates)
        ),
        assets=assets,
        positions=positions,
        security_master=security_master,
        identity_service=identity_service,
    )
    intelligence = build_allocation_intelligence(
        portfolio_view,
        policy=policy,
        assets=assets,
        positions=positions,
        exposure_buckets=_allocation_buckets_from_exposure(exposure),
        exposure_view=exposure,
        candidates=list(candidates),
    )
    diagnostics = intelligence.exposure_diagnostics or build_exposure_diagnostics(
        exposure=exposure,
        determinacy=intelligence.exposure_determinacy,
        production_drift=intelligence.drift,
        production_limitations=intelligence.limitations,
        fill_assets=eligible_fill_assets(
            exposure.instruments,
            extra_symbols=candidates,
            assets=assets,
        ),
    )
    payload = diagnostics.to_adviser_dict(new_money=new_money)
    payload["production_layer_statuses"] = [
        {
            "layer": row.bucket_id,
            "status": row.status.value if hasattr(row.status, "value") else str(row.status),
        }
        for row in intelligence.drift
        if row.dimension == AllocationDimension.ECONOMIC_EXPOSURE
    ]
    resolved = hybrid_policy or resolve_hybrid_allocation_policy()
    unpriced = bool(getattr(portfolio_view, "unpriced_position_count", 0)) or bool(
        intelligence.unpriced_holdings
    )
    mode = resolve_hybrid_portfolio_mode(
        policy=resolved,
        determinacy=intelligence.exposure_determinacy,
        valuation_complete=not unpriced,
        unpriced=unpriced,
        dimension=AllocationDimension.ECONOMIC_EXPOSURE.value,
    )
    live = first_live_blocker([str(item) for item in (new_money.get("limitations") or [])])
    return overlay_adviser_hybrid_fields(
        payload,
        policy=resolved,
        mode=mode,
        live_blocker=live,
    )


def _allocation_dict(plan: Optional[AllocationPlan]) -> dict[str, Any]:
    if plan is None:
        return {"status": UNKNOWN, "copy": INSUFFICIENT_DATA}
    return {
        "input_amount": str(plan.input_amount),
        "currency": plan.currency,
        "total_allocated": str(plan.total_allocated),
        "residual_cash": str(plan.residual_cash),
        "limitations": list(plan.limitations),
        "primary_dimension": plan.primary_dimension,
        "hybrid_allocation_active": plan.hybrid_allocation_active,
        "hybrid_portfolio_mode": plan.hybrid_portfolio_mode,
        "hybrid_policy": plan.hybrid_policy,
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
                "reason_text": item.reason_text,
            }
            for item in plan.skipped
        ],
    }


def _evaluate_symbol(
    symbol: str,
    *,
    candidates: Sequence[Mapping[str, Any]],
    snapshots: Optional[Mapping[str, Mapping[str, Any]]],
    theses: Optional[Mapping[str, Any]],
    allocation: Optional[AllocationPlan],
    portfolio_view: Any,
) -> tuple[Mapping[str, Any], CandidateInvestmentDecision, Any, Any, Any]:
    row = _row_by_symbol(candidates, symbol) or {"symbol": symbol}
    snapshot = snapshots.get(symbol) if snapshots else None
    thesis = (theses or {}).get(symbol) if theses else None
    authority = resolve_authoritative_participation(
        symbol, candidate=row, snapshot=snapshot
    )
    research = build_research_intelligence(
        candidate=row, snapshot=snapshot, thesis=thesis
    )
    fit = assess_portfolio_fit(
        row, portfolio_view=portfolio_view, allocation=allocation
    )
    decision = evaluate_candidate_investment(
        row,
        snapshot=snapshot,
        thesis=thesis,
        allocation=allocation,
        portfolio_view=portfolio_view,
    )
    return row, decision, research, fit, authority


def _present_class(value: Any) -> str:
    text = _text(value)
    if not text or text == UNKNOWN:
        return "belirsiz"
    return text


def _score_label(score: Any) -> str:
    if score in (None, ""):
        return ""
    try:
        return f"{float(score):.1f}"
    except (TypeError, ValueError):
        return ""


def _compose_today(rec: NABIRecommendation) -> str:
    lines = [rec.primary_action]
    if rec.why_now and rec.why_now not in rec.primary_action:
        lines.append(rec.why_now)
    return "\n".join(line for line in lines if line)


def _compose_why(
    rec: NABIRecommendation,
    goal: Mapping[str, Any],
    prior: Mapping[str, Any],
) -> str:
    action = _text(prior.get("action_code")) or rec.action_code
    why = _text(prior.get("why_now")) or rec.why_now
    year = _text(goal.get("target_year")) or "2031"
    if action == ACTION_REVIEW_GOAL_PLAN or "katkı planı" in why.lower() or "katkı planını" in rec.primary_action.lower():
        current = _text(goal.get("current_monthly"))
        required = _text(goal.get("required_monthly"))
        gap = _text(goal.get("contribution_gap"))
        if current and required:
            gap_bit = f" ve aylık açık {gap}" if gap else ""
            return (
                f"{year} hedefin için mevcut aylık katkı planın gerekli seviyenin altında. "
                f"Mevcut katkın {current}, hesaplanan gerekli katkı {required}{gap_bit}. "
                "Bu nedenle NABI bugün yeni yatırım aramaktan önce katkı planını "
                "gözden geçirmeni önceliklendiriyor."
            )
        base = why or f"{year} hedefi için mevcut katkı planı gerekli hızın altında."
        return (
            f"{base} Bu nedenle NABI yeni yatırım aramaktan önce katkı planının "
            "gözden geçirilmesini önceliklendiriyor."
        )
    if why:
        return (
            f"{why} Bu nedenle NABI birincil öneriyi "
            f"{rec.primary_action.rstrip('.')} olarak koruyor."
        )
    return rec.primary_action


def _compose_opportunity_status(
    view: NabiDecisionV3,
    actionable_count: int,
    decisions: Sequence[PortfolioSecurityDecision] = (),
) -> str:
    investable = [
        item
        for item in decisions
        if item.decision in INCREASE_DECISIONS and item.exposure_increase_allowed
    ]
    if investable:
        parts = [
            f"{item.symbol}: {present_action_label(item.decision)}"
            for item in investable
        ]
        return "Onaylanmış fırsatlar: " + "; ".join(parts) + f". {NOT_A_TRADE}"
    lines = [NO_ACTIONABLE_OPPORTUNITY]
    watch = [
        item.symbol
        for item in decisions
        if item.decision == DECISION_WATCH
    ]
    if watch:
        lines.append(
            "İzleme listesindeki isimler de şu anda alınabilir fırsat değildir."
        )
    elif actionable_count > 0:
        lines.append(
            "Onaylı isimler olsa da 8E exposure artışına izin vermiyor; "
            "bunlar yatırım fırsatı değildir."
        )
    return "\n".join(lines)


_LAYER_LABELS_TR = {
    "equity": "hisse",
    "etf": "ETF",
    "sukuk": "sukuk",
    "cash": "nakit",
    "fixed_income": "sabit getirili",
    "real_estate": "gayrimenkul",
    "commodity": "emtia",
}


def _layer_label_tr(bucket_id: str) -> str:
    key = str(bucket_id or "").strip()
    return _LAYER_LABELS_TR.get(key.lower(), key)


def _compose_new_money(new_money: Mapping[str, Any]) -> str:
    if new_money.get("status") == AMOUNT_REQUIRED:
        return AMOUNT_CLARIFICATION
    if new_money.get("status") == UNKNOWN:
        return "Yeni para senaryosu için kanonik plan yok; " + INSUFFICIENT_DATA + "."
    currency = new_money.get("currency") or "TRY"
    amount = format_try_display(new_money.get("input_amount"), currency)
    residual = format_try_display(new_money.get("residual_cash"), currency)
    allocated = format_try_display(new_money.get("total_allocated"), currency)
    recs = new_money.get("recommendations") or []
    limitations = [str(item) for item in (new_money.get("limitations") or [])]
    skipped = new_money.get("skipped") or []
    if "TARGET_NOT_CONFIGURED" in limitations:
        return "Yeni para dağılımı için portföy hedefleri henüz tanımlı değil."
    if recs:
        lines = [f"{amount} için mevcut verilere göre dağıtım:"]
        for item in recs:
            allocated_item = format_try_display(item.get("allocated_amount"), currency)
            reason = str(item.get("reason_text") or "").strip()
            lines.append(f"- {item['symbol']}: {reason} ({allocated_item})")
        if residual:
            lines.append(
                f"Dağıtılabilen tutar {allocated}. Kalan {residual} nakitte tutulabilir."
            )
        return "\n".join(lines)
    fx_blocked = any(
        item.get("reason_code") == REASON_FX_REQUIRED for item in skipped
    ) or any("FX" in item for item in limitations)
    if fx_blocked:
        return (
            "Dağılım hesaplanamadı çünkü gerekli kur dönüşümü mevcut değil. "
            f"{residual or amount} nakitte tutulabilir."
        )
    if PORTFOLIO_EXPOSURE_UNAVAILABLE in limitations:
        return (
            "Portföy maruziyeti fiyatlanamadığı için yeni para dağıtılamadı. "
            f"{residual or amount} nakitte tutulabilir."
        )
    if PORTFOLIO_EXPOSURE_UNSAFE in limitations:
        return (
            "Bilinmeyen ekonomik maruziyet onaylı tavanı aştığı için yeni para "
            "dağıtılamadı. "
            f"{residual or amount} nakitte tutulabilir."
        )
    if NO_ROBUST_UNDERWEIGHT_LAYER in limitations:
        return (
            "Dayanıklı açık katman olmadığı için yeni para dağıtılamadı. "
            f"{residual or amount} nakitte tutulabilir."
        )
    if any(
        item == NO_ELIGIBLE_FILL_FOR_ROBUST_UNDERWEIGHT_LAYER
        or item.startswith(f"{NO_ELIGIBLE_FILL_FOR_ROBUST_UNDERWEIGHT_LAYER}:")
        for item in limitations
    ):
        return (
            "Dayanıklı açık katmanlar için uygun doldurma varlığı yok. "
            f"{residual or amount} nakitte tutulabilir."
        )
    if "EXPOSURE_CLASSIFICATION_INCOMPLETE" in limitations:
        return (
            "Ekonomik maruziyet sınıflandırması tamamlanmadığı için yeni para "
            "güvenle dağıtılamadı. "
            f"{residual or amount} nakitte tutulabilir."
        )
    unfilled = [
        _layer_label_tr(item.split(":", 1)[1])
        for item in limitations
        if item.startswith("UNFILLED_UNDERWEIGHT:") and ":" in item
    ]
    if unfilled:
        layers = ", ".join(dict.fromkeys(unfilled))
        return (
            f"Portföyde {layers} katmanında açık var ancak şu anda bu katmanda "
            "eklemeye uygun katılım onaylı bir varlık yok. "
            f"{residual or amount} nakitte tutulabilir."
        )
    if any(item.get("reason_code") == REASON_NO_ELIGIBLE_SECURITY for item in skipped):
        return (
            "Şu anda güvenli stratejik dağıtım için uygun bir varlık yok. "
            f"{residual or amount} nakitte tutulabilir."
        )
    layer_unmapped = any(
        item.get("reason_code") == REASON_DATA_INCOMPLETE
        and "katman" in str(item.get("reason_text") or "").lower()
        for item in skipped
    )
    if layer_unmapped:
        return (
            "Portföy hedefleri tanımlı ancak mevcut uygun varlıklar bu hedeflerin "
            "katmanlarına bağlanamadı. "
            f"{residual or amount} nakitte tutulabilir."
        )
    return (
        "Şu anda güvenli stratejik dağıtım yapılamıyor. "
        f"{residual or amount} nakitte tutulabilir."
    )


def _append_new_money_conflict(answer: str, blockers: Sequence[str]) -> str:
    if REASON_8E_VS_NEW_MONEY_CONFLICT not in blockers:
        return answer
    return "\n".join(
        line
        for line in (answer, EIGHT_E_VS_NEW_MONEY_COPY)
        if line
    )


def _compose_comparison(
    symbols: Sequence[str],
    *,
    candidates: Sequence[Mapping[str, Any]],
    snapshots: Optional[Mapping[str, Mapping[str, Any]]],
    theses: Optional[Mapping[str, Any]],
    allocation: Optional[AllocationPlan],
    portfolio_view: Any,
    decisions: Sequence[PortfolioSecurityDecision] = (),
) -> tuple[str, Tuple[dict[str, Any], ...], Optional[CandidateInvestmentDecision], Optional[Any], Optional[Any], Optional[str]]:
    evaluated: list[dict[str, Any]] = []
    first_research = None
    first_fit = None
    first_status = None
    first_decision = None
    for symbol in symbols:
        row, decision, research, fit, authority = _evaluate_symbol(
            symbol,
            candidates=candidates,
            snapshots=snapshots,
            theses=theses,
            allocation=allocation,
            portfolio_view=portfolio_view,
        )
        payload = {
            "symbol": decision.symbol,
            "classification": decision.decision_class,
            "nabi_score": decision.nabi_score,
            "portfolio_fit": decision.portfolio_fit,
            "participation_status": decision.participation_status,
            "final_action": decision.final_action,
            "research_completeness": decision.research_completeness,
            "missing_evidence": list(research.missing_evidence) if research is not None else [],
            "fit_reason": fit.reason if fit is not None else "",
            "row": row,
        }
        evaluated.append(payload)
        if first_decision is None:
            first_decision = decision
            first_research = research
            first_fit = fit
            first_status = authority.status
    if not evaluated:
        return (
            "Karşılaştırılacak sembol yok; " + INSUFFICIENT_DATA + ".",
            (),
            None,
            None,
            None,
            None,
        )

    quality_bits: list[str] = []
    fit_bits: list[str] = []
    blockers: list[str] = []
    for item in evaluated:
        status = item["participation_status"]
        symbol = item["symbol"]
        if status == PARTICIPATION_STATUS_UYGUN_DEGIL:
            blockers.append(
                f"{symbol} Participation = Uygun Değil; yatırım olarak önerilemez."
            )
        elif status == PARTICIPATION_STATUS_KONTROL_ET:
            blockers.append(
                f"{symbol} Participation = Kontrol Et; karşılaştırma sınırlıdır ve "
                "yatırım olarak önerilemez."
            )
        missing = item.get("missing_evidence") or []
        if missing:
            labels = ", ".join(present_missing_evidence(code) for code in missing)
            quality_bits.append(f"{symbol} için yetersiz boyut: {labels}.")

    eligible_rows = [
        item["row"]
        for item in evaluated
        if item["participation_status"] == PARTICIPATION_STATUS_UYGUN
    ]
    if len(eligible_rows) >= 2:
        ranked = sorted(eligible_rows, key=company_rank_key)
        leader_symbol = _text(ranked[0].get("symbol")).upper()
        leader = next(item for item in evaluated if item["symbol"] == leader_symbol)
        class_label = _present_class(leader.get("classification"))
        score = _score_label(leader.get("nabi_score"))
        score_bit = f", NABI Score {score}" if score else ""
        quality_bits.insert(
            0,
            f"{leader_symbol} önde ({class_label}{score_bit}).",
        )
        other = next(
            (item for item in evaluated if item["symbol"] != leader_symbol),
            None,
        )
        if other:
            other_score = _score_label(other.get("nabi_score"))
            other_bit = f", NABI Score {other_score}" if other_score else ""
            quality_bits.append(
                f"{other['symbol']}: {_present_class(other.get('classification'))}{other_bit}."
            )
    elif len(eligible_rows) == 1:
        only = _text(eligible_rows[0].get("symbol")).upper()
        quality_bits.insert(0, f"yalnızca {only} katılım açısından Uygun.")
    elif not quality_bits:
        quality_bits.append(
            "katılım belirsizliği veya uygun olmama nedeniyle fırsat sırası kurulamaz."
        )

    deployable = [
        item
        for item in evaluated
        if item["participation_status"] == PARTICIPATION_STATUS_UYGUN
        and item["portfolio_fit"] != FIT_POOR
    ]
    poor = [
        item
        for item in evaluated
        if item["participation_status"] == PARTICIPATION_STATUS_UYGUN
        and item["portfolio_fit"] == FIT_POOR
    ]
    for item in evaluated:
        reason = _text(item.get("fit_reason"))
        fit_bits.append(
            f"{item['symbol']} {fit_label_tr(item['portfolio_fit'])}"
            + (f" ({reason})" if reason else "")
            + "."
        )

    conclusion_bits: list[str] = []
    if blockers:
        conclusion_bits.extend(blockers)
    if eligible_rows and poor and deployable:
        leader_symbol = _text(sorted(eligible_rows, key=company_rank_key)[0].get("symbol")).upper()
        deploy_symbol = deployable[0]["symbol"]
        if deploy_symbol != leader_symbol:
            conclusion_bits.append(
                f"{leader_symbol} fırsat kalitesi açısından önde; mevcut portföy "
                f"uyumu nedeniyle {deploy_symbol} dağıtım için daha uygun olabilir."
            )
        else:
            conclusion_bits.append(
                f"{leader_symbol} fırsat kalitesi ve portföy uyumu birlikte değerlendirilmelidir."
            )
    elif not eligible_rows:
        conclusion_bits.append("Katılım belirsiz veya uygun olmayan semboller yatırım olarak öne çıkarılamaz.")
    else:
        conclusion_bits.append("Portföy uyumu fırsat sırasını değiştirmez.")
    conclusion_bits.append(NOT_A_TRADE)

    by_8e = _index_security_decisions(decisions)
    eight_e_bits = []
    for item in evaluated:
        security = by_8e.get(item["symbol"])
        if security is None:
            continue
        eight_e_bits.append(
            f"{security.symbol}: {present_action_label(security.decision)}"
            f" (increase_allowed={str(security.exposure_increase_allowed).lower()})"
        )
    answer_lines = [
        "Fırsat kalitesi açısından: " + " ".join(quality_bits),
        "Portföy uyumu açısından: " + " ".join(fit_bits),
        "Sonuç: " + " ".join(conclusion_bits),
    ]
    if eight_e_bits:
        answer_lines.insert(2, "8E aksiyon: " + "; ".join(eight_e_bits) + ".")
    answer = "\n".join(answer_lines)
    public_rows = tuple(
        {
            "symbol": item["symbol"],
            "classification": item["classification"],
            "nabi_score": item["nabi_score"],
            "portfolio_fit": item["portfolio_fit"],
            "participation_status": item["participation_status"],
            "security_action": (
                by_8e[item["symbol"]].decision if item["symbol"] in by_8e else None
            ),
            "exposure_increase_allowed": (
                by_8e[item["symbol"]].exposure_increase_allowed
                if item["symbol"] in by_8e
                else False
            ),
        }
        for item in evaluated
    )
    return answer, public_rows, first_decision, first_research, first_fit, first_status


def _turkiye_fund_adviser_overlay(
    parsed: ParsedAdviserQuestion,
    *,
    portfolio_view: Any,
    client: Any,
    turkiye_fund_contexts: Sequence[Any],
    new_money: Mapping[str, Any],
) -> tuple[Optional[str], Optional[dict[str, Any]]]:
    from services.fund_product_contract import PILOT_TEFAS_FUND_CODES
    from services.turkiye_fund_portfolio_integration import (
        format_turkiye_fund_adviser_narrative,
        load_turkiye_fund_portfolio_contexts_from_client,
        turkiye_fund_adviser_facts,
    )

    symbol = normalize_symbol(parsed.focus_symbol)
    if not symbol or symbol not in PILOT_TEFAS_FUND_CODES:
        return None, None
    context = None
    for row in turkiye_fund_contexts or ():
        if getattr(row, "fund_code", None) == symbol:
            context = row
            break
    if context is None and client is not None:
        loaded = load_turkiye_fund_portfolio_contexts_from_client(
            client,
            portfolio_view=portfolio_view,
            fund_codes=(symbol,),
        )
        context = loaded[0] if loaded else None
    if context is None:
        return None, None
    allocated = 0
    for rec in new_money.get("recommendations") or ():
        if isinstance(rec, Mapping):
            rec_symbol = rec.get("symbol")
            rec_amount = rec.get("allocated_amount")
        else:
            rec_symbol = getattr(rec, "symbol", None)
            rec_amount = getattr(rec, "allocated_amount", 0)
        if normalize_symbol(rec_symbol) == symbol:
            allocated = rec_amount or 0
            break
    return (
        format_turkiye_fund_adviser_narrative(context, allocation_try=allocated),
        turkiye_fund_adviser_facts(context, allocation_try=allocated),
    )


def _turkiye_fund_scanner_adviser_overlay(
    parsed: ParsedAdviserQuestion,
) -> tuple[Optional[str], Optional[dict[str, Any]]]:
    from services.turkiye_fund_scanner_adviser import turkiye_fund_scanner_adviser_overlay

    return turkiye_fund_scanner_adviser_overlay(parsed.question)


def _compose_canonical_answer(
    parsed: ParsedAdviserQuestion,
    *,
    rec: NABIRecommendation,
    rec_dict: Mapping[str, Any],
    view: NabiDecisionV3,
    focus: Optional[CandidateInvestmentDecision],
    comparison_answer: Optional[str],
    goal: dict[str, Any],
    new_money: dict[str, Any],
    weights: Mapping[str, float],
    actionable_count: int,
    participation_status: Optional[str],
    prior: Mapping[str, Any],
    security_decisions: Sequence[PortfolioSecurityDecision] = (),
    blockers: Sequence[str] = (),
    turkiye_fund_answer: Optional[str] = None,
) -> str:
    intent = parsed.intent
    by_8e = _index_security_decisions(security_decisions)
    focus_8e = by_8e.get(normalize_symbol(parsed.focus_symbol)) if parsed.focus_symbol else None
    if intent == INTENT_TODAY_RECOMMENDATION or intent == "GENERAL_NABI":
        return present_user_text(_compose_today_overlaid(rec, rec_dict))
    if intent == INTENT_WHY_RECOMMENDATION:
        prior_intent = _text(prior.get("intent"))
        if prior_intent == INTENT_OPPORTUNITY_COMPARE and comparison_answer:
            return present_user_text(comparison_answer)
        if prior_intent == INTENT_OPPORTUNITY_STATUS:
            return present_user_text(
                _compose_opportunity_status(view, actionable_count, security_decisions)
            )
        if prior_intent == INTENT_NEW_MONEY_SCENARIO:
            if new_money.get("status") != AMOUNT_REQUIRED:
                return present_user_text(
                    _append_new_money_conflict(_compose_new_money(new_money), blockers)
                )
            return present_user_text(_compose_why(rec, goal, prior))
        return present_user_text(_compose_why(rec, goal, prior))
    if intent == INTENT_GOAL_EXPLAIN:
        lines = [goal.get("nabi_copy") or goal.get("status_copy") or INSUFFICIENT_DATA]
        if goal.get("current_monthly") and goal.get("required_monthly"):
            lines.append(
                f"Mevcut katkı: {goal['current_monthly']}. "
                f"Gerekli katkı: {goal['required_monthly']}."
            )
        return present_user_text("\n".join(line for line in lines if line))
    if intent == INTENT_NEW_MONEY_SCENARIO:
        return present_user_text(
            _append_new_money_conflict(_compose_new_money(new_money), blockers)
        )
    if intent == INTENT_OPPORTUNITY_STATUS:
        return present_user_text(
            _compose_opportunity_status(view, actionable_count, security_decisions)
        )
    if intent == INTENT_OPPORTUNITY_COMPARE:
        return present_user_text(
            comparison_answer
            or ("Karşılaştırılacak kanonik şirket yok; " + INSUFFICIENT_DATA + ".")
        )
    if intent == INTENT_PORTFOLIO_FIT:
        symbol = parsed.focus_symbol
        if not symbol:
            return "Odak sembol yok; " + INSUFFICIENT_DATA + "."
        if symbol not in weights:
            return f"{symbol} kanonik portföy ağırlığında yok; {INSUFFICIENT_DATA}."
        weight = weights[symbol]
        lines = [f"{symbol} mevcut ağırlık: %{weight:.1f}."]
        if weight >= CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT:
            lines.append(
                f"Tekil yoğunluk eşiği %{CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT:.0f} "
                "üzerinde veya eşit."
            )
        else:
            lines.append("Tekil yoğunluk eşiğinin altında.")
        if focus is not None:
            lines.append(f"Portföy uyumu: {fit_label_tr(focus.portfolio_fit)}.")
        if focus_8e is not None:
            lines.append(
                f"8E aksiyon: {present_action_label(focus_8e.decision)} "
                f"(increase_allowed={str(focus_8e.exposure_increase_allowed).lower()})."
            )
        return present_user_text("\n".join(lines))
    if intent in {
        INTENT_PARTICIPATION_EXPLAIN,
        INTENT_SYMBOL_EXPLAIN,
        INTENT_RESEARCH_EXPLAIN,
    }:
        if turkiye_fund_answer:
            return turkiye_fund_answer
        symbol = parsed.focus_symbol or (focus.symbol if focus is not None else None)
        if symbol is None and focus_8e is None:
            return "Sembol için kanonik karar yok; " + INSUFFICIENT_DATA + "."
        action = focus_8e.decision if focus_8e is not None else DECISION_INSUFFICIENT_DATA
        status = (
            (focus_8e.participation_status if focus_8e is not None else None)
            or participation_status
            or (focus.participation_status if focus is not None else None)
        )
        lines = [f"{symbol}: {present_action_label(action)}."]
        if focus_8e is not None:
            if focus_8e.primary_reasons:
                lines.append(" ".join(focus_8e.primary_reasons))
            lines.append(
                f"exposure_increase_allowed="
                f"{str(focus_8e.exposure_increase_allowed).lower()}."
            )
        if status and status != PARTICIPATION_STATUS_UYGUN:
            lines.append(
                f"Participation {status}. "
                "NABI bunu katılım çözülmeden yatırım önerisi olarak sunamaz."
            )
        elif focus is not None and focus_8e is None:
            lines.append(focus.why)
        lines.append(NOT_A_TRADE)
        return present_user_text("\n".join(line for line in lines if line))
    return present_user_text(_compose_today_overlaid(rec, rec_dict))


def _compose_today_overlaid(rec: NABIRecommendation, rec_dict: Mapping[str, Any]) -> str:
    primary = _text(rec_dict.get("primary_action")) or rec.primary_action
    why = _text(rec_dict.get("why_now")) or rec.why_now
    lines = [primary]
    if why and why not in primary:
        lines.append(why)
    return "\n".join(line for line in lines if line)


def build_followup_state(
    parsed: ParsedAdviserQuestion,
    rec: Mapping[str, Any] | NABIRecommendation,
    canonical_answer: str,
    new_money: Mapping[str, Any],
    prior: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    symbols = parsed.compare_symbols or parsed.inherited_symbols
    if not symbols and parsed.focus_symbol:
        symbols = (parsed.focus_symbol,)
    amount = parsed.scenario_amount
    currency = parsed.scenario_currency
    if not amount and new_money.get("status") not in {AMOUNT_REQUIRED, UNKNOWN, None}:
        amount = str(new_money.get("input_amount") or "") or None
        currency = new_money.get("currency") or currency
    action_code = rec.action_code if hasattr(rec, "action_code") else rec.get("action_code")
    primary_action = rec.primary_action if hasattr(rec, "primary_action") else rec.get("primary_action")
    why_now = rec.why_now if hasattr(rec, "why_now") else rec.get("why_now")
    previous = dict(prior or {})
    consumed = (
        parsed.intent == INTENT_NEW_MONEY_SCENARIO
        and bool(amount)
        and new_money.get("status") != AMOUNT_REQUIRED
    )
    explicit_override = parsed.intent not in {
        INTENT_GENERAL_NABI,
        INTENT_WHY_RECOMMENDATION,
        INTENT_NEW_MONEY_SCENARIO,
    }
    if new_money.get("status") == AMOUNT_REQUIRED:
        pending = True
    elif consumed or explicit_override:
        pending = False
    else:
        pending = bool(previous.get(PENDING_NEW_MONEY_AMOUNT))
    return {
        "intent": parsed.intent,
        "action_code": action_code,
        "primary_action": primary_action,
        "why_now": why_now,
        "symbols": list(symbols),
        "amount": amount,
        "currency": currency,
        "canonical_answer": canonical_answer,
        PENDING_NEW_MONEY_AMOUNT: pending,
    }


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
    conversation_state: Optional[Mapping[str, Any]] = None,
    fund_snapshots: Optional[Mapping[str, Any]] = None,
    security_master: Any = None,
    identity_service: Any = None,
    hybrid_policy: Optional[HybridExposureAllocationPolicy] = None,
    enable_hybrid_exposure_allocation: Optional[bool] = None,
    security_decisions: Sequence[PortfolioSecurityDecision] = (),
    portfolio_security_client: Any = None,
    user_id: Optional[str] = None,
    turkiye_fund_contexts: Sequence[Any] = (),
) -> NabiAdviserContext:
    prior = dict(conversation_state or {})
    parsed = parse_adviser_question(question, prior)
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
    compare_symbols = parsed.compare_symbols or (
        parsed.inherited_symbols
        if parsed.intent in {INTENT_WHY_RECOMMENDATION, INTENT_OPPORTUNITY_COMPARE}
        and _text(prior.get("intent")) == INTENT_OPPORTUNITY_COMPARE
        else ()
    )
    focus_symbol = parsed.focus_symbol
    focus_item = None
    research = None
    fit = None
    authority_status = None
    comparison_answer = None
    comparison_rows: Tuple[dict[str, Any], ...] = ()
    if parsed.intent == INTENT_OPPORTUNITY_COMPARE or (
        parsed.intent == INTENT_WHY_RECOMMENDATION
        and _text(prior.get("intent")) == INTENT_OPPORTUNITY_COMPARE
        and compare_symbols
    ):
        (
            comparison_answer,
            comparison_rows,
            focus_item,
            research,
            fit,
            authority_status,
        ) = _compose_comparison(
            compare_symbols[:4],
            candidates=candidates,
            snapshots=snapshots,
            theses=theses,
            allocation=allocation,
            portfolio_view=portfolio_view,
            decisions=resolve_adviser_security_decisions(
                compare_symbols[:4],
                provided=security_decisions,
                client=portfolio_security_client,
                user_id=user_id,
            ),
        )
    elif focus_symbol:
        _, focus_item, research, fit, authority = _evaluate_symbol(
            focus_symbol,
            candidates=candidates,
            snapshots=snapshots,
            theses=theses,
            allocation=allocation,
            portfolio_view=portfolio_view,
        )
        authority_status = authority.status

    new_money: dict[str, Any]
    if parsed.intent == INTENT_NEW_MONEY_SCENARIO or (
        parsed.intent == INTENT_WHY_RECOMMENDATION
        and _text(prior.get("intent")) == INTENT_NEW_MONEY_SCENARIO
        and (parsed.scenario_amount or prior.get("amount"))
    ):
        amount = parsed.scenario_amount or (
            str(prior.get("amount"))
            if parsed.intent == INTENT_WHY_RECOMMENDATION
            else None
        )
        currency = parsed.scenario_currency or prior.get("currency") or "TRY"
        if not amount:
            new_money = {"status": AMOUNT_REQUIRED, "copy": AMOUNT_CLARIFICATION}
        elif portfolio_view is None:
            new_money = {"status": UNKNOWN, "copy": INSUFFICIENT_DATA}
        else:
            conversion = None
            fx_schedule = getattr(goal_dashboard, "fx_schedule", None)
            as_of = getattr(goal_dashboard, "as_of_date", None)
            if fx_schedule is not None:
                year = getattr(as_of, "year", None)
                rate = fx_schedule.usdtry_for_year(year) if year is not None else None
                conversion = planning_conversion(
                    rate,
                    contribution_currency=str(currency),
                )
            resolved_hybrid = resolve_hybrid_allocation_policy(
                enable_hybrid_exposure_allocation,
                policy=hybrid_policy,
            )
            gate_decisions = resolve_adviser_security_decisions(
                _collect_new_money_universe_symbols(
                    parsed, rec, view, candidates, portfolio_view
                ),
                provided=security_decisions,
                client=portfolio_security_client,
                user_id=user_id,
            )
            scenario_plan = allocate_new_money(
                available_amount=Decimal(str(amount)),
                amount_currency=str(currency),
                portfolio_view=portfolio_view,
                policy=policy,
                candidates=candidates,
                conversion=conversion,
                assets=assets,
                positions=positions,
                fund_snapshots=fund_snapshots,
                security_master=security_master,
                identity_service=identity_service,
                hybrid_policy=resolved_hybrid,
                security_decisions=gate_decisions,
            )
            new_money = _allocation_dict(scenario_plan)
    else:
        new_money = (
            {"status": AMOUNT_REQUIRED, "copy": AMOUNT_CLARIFICATION}
            if parsed.intent == INTENT_NEW_MONEY_SCENARIO
            else _allocation_dict(None)
        )

    weights = holding_weights(portfolio_view)
    actionable = sum(1 for row in candidates if is_actionable_opportunity(row))
    goal = _goal_dict(goal_dashboard)
    economic_exposure = _economic_exposure_context(
        portfolio_view=portfolio_view,
        policy=policy,
        new_money=new_money,
        fund_snapshots=fund_snapshots,
        security_master=security_master,
        identity_service=identity_service,
        assets=assets,
        positions=positions,
        candidates=candidates,
        hybrid_policy=resolve_hybrid_allocation_policy(
            enable_hybrid_exposure_allocation,
            policy=hybrid_policy,
        ),
    )
    resolved_decisions = resolve_adviser_security_decisions(
        _collect_adviser_symbols(parsed, rec, view, allocation, new_money),
        provided=security_decisions,
        client=portfolio_security_client,
        user_id=user_id,
    )
    decisions_by_symbol = _index_security_decisions(resolved_decisions)
    rec_dict = _apply_8e_security_authority(
        _recommendation_dict(rec, view), rec, decisions_by_symbol
    )
    authoritative_symbols = tuple(
        normalize_symbol(item.symbol) for item in security_decisions
    )
    if portfolio_security_client is not None:
        authoritative_symbols = tuple(item.symbol for item in resolved_decisions)
    blockers = _new_money_eight_e_conflicts(
        allocation=allocation,
        new_money=new_money,
        decisions_by_symbol=decisions_by_symbol,
        authoritative_symbols=authoritative_symbols,
    )
    if blockers:
        new_money = dict(new_money)
        new_money["blockers"] = list(
            dict.fromkeys([*(new_money.get("blockers") or []), *blockers])
        )
        new_money["limitations"] = list(
            dict.fromkeys([*(new_money.get("limitations") or []), *blockers])
        )
    focus_8e = (
        decisions_by_symbol.get(normalize_symbol(parsed.focus_symbol))
        if parsed.focus_symbol
        else None
    )
    turkiye_answer, turkiye_facts = _turkiye_fund_adviser_overlay(
        parsed,
        portfolio_view=portfolio_view,
        client=portfolio_security_client,
        turkiye_fund_contexts=turkiye_fund_contexts,
        new_money=new_money,
    )
    scanner_answer, scanner_facts = _turkiye_fund_scanner_adviser_overlay(parsed)
    if turkiye_answer is None and scanner_answer:
        turkiye_answer = scanner_answer
    canonical = _compose_canonical_answer(
        parsed,
        rec=rec,
        rec_dict=rec_dict,
        view=view,
        focus=focus_item,
        comparison_answer=comparison_answer,
        goal=goal,
        new_money=new_money,
        weights=weights,
        actionable_count=actionable,
        participation_status=(
            (focus_8e.participation_status if focus_8e is not None else None)
            or authority_status
            or (focus_item.participation_status if focus_item else None)
        ),
        prior=prior,
        security_decisions=resolved_decisions,
        blockers=blockers,
        turkiye_fund_answer=turkiye_answer,
    )
    limitations = list(rec.limitations)
    limitations.extend(blockers)
    if research is not None and research.missing_evidence:
        limitations.extend(research.missing_evidence)
    evidence = rec.evidence_refs
    if focus_item is not None:
        evidence = tuple(dict.fromkeys((*evidence, *focus_item.reason_codes)))
    if focus_8e is not None:
        evidence = tuple(dict.fromkeys((*evidence, *focus_8e.reason_codes)))
    return NabiAdviserContext(
        question=parsed.question,
        intent=parsed.intent,
        focus_symbol=parsed.focus_symbol,
        current_recommendation=rec_dict,
        wealth_context={
            "dashboard_primary": view.dashboard_primary,
            "wealth_action": view.wealth_action,
            **({"turkiye_fund": turkiye_facts} if turkiye_facts else {}),
            **({"turkiye_fund_scanner": scanner_facts} if scanner_facts else {}),
        },
        goal_context=goal,
        new_money_context=new_money,
        economic_exposure_context=economic_exposure,
        candidate_decision=_decision_dict(focus_item, focus_8e),
        participation_status=(
            (focus_8e.participation_status if focus_8e is not None else None)
            or authority_status
            or (focus_item.participation_status if focus_item else None)
        ),
        research_intelligence=(
            {
                "research_state": research.research_state,
                "research_completeness": research.research_completeness,
                "valuation_classification": research.valuation_classification,
                "investable": research.investable,
                "missing_evidence": list(research.missing_evidence),
            }
            if research is not None
            else None
        ),
        portfolio_fit=(
            {"fit": fit.fit, "reason": fit.reason, "reason_codes": list(fit.reason_codes)}
            if fit is not None
            else None
        ),
        opportunity_comparison=comparison_rows,
        reason_codes=tuple(dict.fromkeys((*view.audit.reason_codes, *blockers))),
        evidence_refs=evidence,
        limitations=tuple(dict.fromkeys(limitations)),
        canonical_answer=canonical,
        prior_context=prior or None,
        security_decisions=resolved_decisions,
        blockers=blockers,
    )
