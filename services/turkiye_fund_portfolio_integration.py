"""End-to-end Turkish FUND/TR portfolio integration.

Reuses accepted snapshot reads, 2M-A Fund Report navigation, generic 8E,
and the existing New Money engine. Does not recompute Participation/FI,
call TEFAS/KAP/FMP, write production state, or map cash_like to CASH.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping, MutableMapping, Optional, Sequence

from services.fund_decision_readiness import TURKIYE_FUND_8E_INSTRUMENT, TURKIYE_FUND_8E_MARKET
from services.fund_product_contract import LAYER_CASH_LIKE, PILOT_TEFAS_FUND_CODES
from services.hybrid_exposure_allocation_policy import HybridExposureAllocationPolicy
from services.portfolio_economic_exposure import (
    EconomicExposure,
    EconomicExposureBucket,
    ExposureConfidence,
    ExposureEvidenceSource,
)
from services.portfolio_intelligence_helpers import iter_all_position_rows
from services.portfolio_security_context_builder import aggregate_holding
from services.portfolio_security_decision_contract import (
    DECISION_INSUFFICIENT_DATA,
    PortfolioSecurityDecision,
)
from services.turkiye_fund_navigation import (
    FUND_REPORT_PAGE,
    apply_turkiye_fund_report_handoff,
    is_turkiye_fund_nav_identity,
    list_turkiye_fund_nav_items,
)
from services.turkiye_fund_snapshot_reader import (
    SnapshotReadError,
    TurkiyeFundCanonicalRead,
    load_turkiye_fund_canonical_from_client,
    read_turkiye_fund_canonical,
)
from services.wealth_contract import ASSET_CLASS_CASH, ASSET_CLASS_FUND, normalize_symbol
from services.wealth_new_money_allocation import (
    REASON_EXPOSURE_INCREASE_NOT_ALLOWED,
    allocate_new_money,
)

PIPELINE_ENTRY_DECISION = "ADAY"
EXPLANATION_INCREASE_BLOCKED = "Yeni para artışına izin verilmiyor."
STRATEGIC_LAYER_EQUITY = "equity"
STRATEGIC_LAYER_SUKUK = "sukuk"
STRATEGIC_LAYER_CASH_LIKE = LAYER_CASH_LIKE
PORTFOLIO_CASH_LAYER = ASSET_CLASS_CASH


@dataclass(frozen=True)
class TurkiyeFundPortfolioContext:
    fund_code: str
    instrument: str
    market: str
    is_holding: bool
    market_value: Optional[float]
    portfolio_weight: Optional[float]
    participation_status: str
    research_allowed: bool
    fi_score: Optional[float]
    fi_state: str
    primary_exposure: Optional[str]
    geography: Optional[str]
    eight_e: str
    increase_allowed: bool
    block_reasons: tuple[str, ...]
    unavailable_reason: Optional[str] = None
    lookthrough_weights: tuple[tuple[Any, ...], ...] = ()
    decision: Optional[PortfolioSecurityDecision] = None


@dataclass(frozen=True)
class TurkiyeFundExplanation:
    fund_code: str
    participation_status: str
    fi_score: Optional[float]
    fi_state: str
    exposure: Optional[str]
    eight_e: str
    increase_allowed: bool
    allocation_try: Decimal
    block_reason: str
    summary_tr: str


@dataclass(frozen=True)
class TurkiyeNewMoneyUat:
    plan: Any
    turkish_allocated: Decimal
    other_allocated: Decimal
    total_allocated: Decimal
    residual_cash: Decimal
    by_fund: dict[str, Decimal]
    skip_reasons: dict[str, tuple[str, ...]]
    explanations: tuple[TurkiyeFundExplanation, ...]


def portfolio_intelligence_report_symbols(
    held_symbols: Sequence[str],
) -> tuple[str, ...]:
    held = [normalize_symbol(symbol) for symbol in held_symbols if normalize_symbol(symbol)]
    catalog = [item.fund_code for item in list_turkiye_fund_nav_items()]
    return tuple(sorted(dict.fromkeys([*held, *catalog])))


def apply_portfolio_intelligence_fund_handoff(
    session: MutableMapping[str, Any],
    query: MutableMapping[str, Any],
    symbol: str,
) -> Optional[str]:
    """Reuse 2M-A FUND/TR handoff. None means caller keeps the existing route."""
    if not is_turkiye_fund_nav_identity(symbol):
        return None
    apply_turkiye_fund_report_handoff(session, query, symbol)
    return FUND_REPORT_PAGE


def holding_facts(
    portfolio_view: Any,
    fund_code: str,
) -> tuple[bool, Optional[float], Optional[float]]:
    if portfolio_view is None:
        return False, None, None
    qty, value, weight, _market = aggregate_holding(
        iter_all_position_rows(portfolio_view),
        fund_code,
    )
    is_holding = qty is not None and float(qty) > 0
    return is_holding, value, weight


def context_from_canonical(
    read: TurkiyeFundCanonicalRead,
    *,
    is_holding: bool = False,
    market_value: Optional[float] = None,
    portfolio_weight: Optional[float] = None,
) -> TurkiyeFundPortfolioContext:
    exposure = read.fund_intelligence.exposure
    return TurkiyeFundPortfolioContext(
        fund_code=read.fund_code,
        instrument=TURKIYE_FUND_8E_INSTRUMENT,
        market=TURKIYE_FUND_8E_MARKET,
        is_holding=is_holding,
        market_value=market_value,
        portfolio_weight=portfolio_weight,
        participation_status=read.participation.status,
        research_allowed=bool(read.participation.research_allowed),
        fi_score=read.fund_intelligence.score,
        fi_state=read.fund_intelligence.state,
        primary_exposure=exposure.primary_exposure,
        geography=exposure.geography,
        eight_e=read.decision.decision,
        increase_allowed=bool(read.decision.exposure_increase_allowed),
        block_reasons=tuple(read.decision.blocking_reasons or read.decision.reason_codes or ()),
        lookthrough_weights=exposure.lookthrough_weights,
        decision=read.decision,
    )


def unavailable_context(fund_code: str, reason: str) -> TurkiyeFundPortfolioContext:
    code = normalize_symbol(fund_code)
    return TurkiyeFundPortfolioContext(
        fund_code=code,
        instrument=TURKIYE_FUND_8E_INSTRUMENT,
        market=TURKIYE_FUND_8E_MARKET,
        is_holding=False,
        market_value=None,
        portfolio_weight=None,
        participation_status="",
        research_allowed=False,
        fi_score=None,
        fi_state="",
        primary_exposure=None,
        geography=None,
        eight_e=DECISION_INSUFFICIENT_DATA,
        increase_allowed=False,
        block_reasons=(reason,),
        unavailable_reason=reason,
    )


def load_turkiye_fund_portfolio_contexts(
    *,
    participation_repo: Any,
    snapshot_repo: Any,
    portfolio_view: Any = None,
    fund_codes: Sequence[str] = PILOT_TEFAS_FUND_CODES,
) -> tuple[TurkiyeFundPortfolioContext, ...]:
    rows: list[TurkiyeFundPortfolioContext] = []
    for code in fund_codes:
        held, value, weight = holding_facts(portfolio_view, code)
        try:
            read = read_turkiye_fund_canonical(
                participation_repo=participation_repo,
                snapshot_repo=snapshot_repo,
                fund_code=code,
                is_holding=held,
                portfolio_weight=weight,
            )
        except SnapshotReadError as exc:
            rows.append(unavailable_context(code, exc.reason))
            continue
        rows.append(
            context_from_canonical(
                read,
                is_holding=held,
                market_value=value,
                portfolio_weight=weight,
            )
        )
    return tuple(rows)


def load_turkiye_fund_portfolio_contexts_from_client(
    client: Any,
    *,
    portfolio_view: Any = None,
    fund_codes: Sequence[str] = PILOT_TEFAS_FUND_CODES,
) -> tuple[TurkiyeFundPortfolioContext, ...]:
    rows: list[TurkiyeFundPortfolioContext] = []
    for code in fund_codes:
        held, value, weight = holding_facts(portfolio_view, code)
        try:
            read = load_turkiye_fund_canonical_from_client(
                client,
                code,
                is_holding=held,
                portfolio_weight=weight,
            )
        except SnapshotReadError as exc:
            rows.append(unavailable_context(code, exc.reason))
            continue
        rows.append(
            context_from_canonical(
                read,
                is_holding=held,
                market_value=value,
                portfolio_weight=weight,
            )
        )
    return tuple(rows)


def strategic_layer_for_exposure(primary_exposure: Optional[str]) -> Optional[str]:
    """Existing taxonomy only. cash_like stays cash_like and never becomes CASH."""
    layer = str(primary_exposure or "").strip().lower()
    if not layer:
        return None
    if layer in {PORTFOLIO_CASH_LAYER, "nakit"}:
        return None
    if layer == STRATEGIC_LAYER_CASH_LIKE:
        return STRATEGIC_LAYER_CASH_LIKE
    if layer == STRATEGIC_LAYER_EQUITY:
        return STRATEGIC_LAYER_EQUITY
    if layer == STRATEGIC_LAYER_SUKUK:
        return STRATEGIC_LAYER_SUKUK
    if layer in {item.value for item in EconomicExposureBucket}:
        return layer
    return None


def exposure_maps_to_portfolio_cash(primary_exposure: Optional[str]) -> bool:
    layer = str(primary_exposure or "").strip().lower()
    if layer == LAYER_CASH_LIKE:
        return False
    return layer == PORTFOLIO_CASH_LAYER


def ais_satisfies_portfolio_cash(context: TurkiyeFundPortfolioContext) -> bool:
    return False


def exposure_mapping_for_context(
    context: TurkiyeFundPortfolioContext,
) -> tuple[EconomicExposure, ...]:
    layer = strategic_layer_for_exposure(context.primary_exposure)
    if layer is None:
        return ()
    limitations = ("NOT_PORTFOLIO_CASH",) if layer == LAYER_CASH_LIKE else ()
    return (
        EconomicExposure(
            exposure_bucket=layer,
            weight_pct=100.0,
            evidence_source=ExposureEvidenceSource.CANONICAL_STATIC_MAPPING,
            confidence=ExposureConfidence.MEDIUM,
            limitations=limitations,
        ),
    )


def turkiye_exposure_mappings(
    contexts: Sequence[TurkiyeFundPortfolioContext],
) -> dict[str, tuple[EconomicExposure, ...]]:
    out: dict[str, tuple[EconomicExposure, ...]] = {}
    for context in contexts:
        mapping = exposure_mapping_for_context(context)
        if mapping:
            out[context.fund_code] = mapping
    return out


def turkiye_security_decisions(
    contexts: Sequence[TurkiyeFundPortfolioContext],
) -> tuple[PortfolioSecurityDecision, ...]:
    return tuple(context.decision for context in contexts if context.decision is not None)


def turkiye_new_money_candidates(
    contexts: Sequence[TurkiyeFundPortfolioContext],
    *,
    price_by_symbol: Optional[Mapping[str, Any]] = None,
    currency: str = "TRY",
) -> tuple[dict[str, Any], ...]:
    """Enter the generic candidate pipeline. 8E remains the increase gate."""
    prices = {normalize_symbol(key): value for key, value in (price_by_symbol or {}).items()}
    rows: list[dict[str, Any]] = []
    for context in contexts:
        if context.unavailable_reason or context.decision is None:
            continue
        price = prices.get(context.fund_code)
        if price is None:
            continue
        rows.append(
            {
                "symbol": context.fund_code,
                "decision": PIPELINE_ENTRY_DECISION,
                "current_price": price,
                "currency": currency,
                "market": context.market,
                "asset_type": ASSET_CLASS_FUND,
                "asset_class": ASSET_CLASS_FUND,
                "participation_status": context.participation_status,
                "research_allowed": context.research_allowed,
                "data_completeness": 100,
                "data_source": "canonical_snapshot",
            }
        )
    return tuple(rows)


def format_turkiye_fund_explanation(
    context: TurkiyeFundPortfolioContext,
    *,
    allocation_try: Decimal | int | str = 0,
) -> TurkiyeFundExplanation:
    allocated = Decimal(str(allocation_try or 0))
    if context.unavailable_reason:
        block = context.unavailable_reason
    elif not context.increase_allowed:
        block = REASON_EXPOSURE_INCREASE_NOT_ALLOWED
    else:
        block = ""
    increase_copy = (
        "Yeni para artışına izin veriliyor."
        if context.increase_allowed
        else EXPLANATION_INCREASE_BLOCKED
    )
    summary = (
        f"{context.fund_code}: Katılım {context.participation_status or '—'}. "
        f"FI {context.fi_score} {context.fi_state}. "
        f"8E {context.eight_e}. "
        f"{increase_copy} "
        f"Allocation {allocated} TRY."
    )
    if block:
        summary = f"{summary} {block}."
    return TurkiyeFundExplanation(
        fund_code=context.fund_code,
        participation_status=context.participation_status,
        fi_score=context.fi_score,
        fi_state=context.fi_state,
        exposure=context.primary_exposure,
        eight_e=context.eight_e,
        increase_allowed=context.increase_allowed,
        allocation_try=allocated,
        block_reason=block,
        summary_tr=summary,
    )


def format_canonical_new_money_caption(
    *,
    increase_allowed: bool,
    eight_e: str,
) -> str:
    if increase_allowed:
        return f"8E {eight_e}. Yeni para artışına izin veriliyor."
    return f"8E {eight_e}. {EXPLANATION_INCREASE_BLOCKED} Allocation 0 TRY."


def _turkish_skip_reasons(plan: Any) -> dict[str, tuple[str, ...]]:
    out: dict[str, list[str]] = {code: [] for code in PILOT_TEFAS_FUND_CODES}
    for skip in getattr(plan, "skipped", ()) or ():
        symbol = normalize_symbol(getattr(skip, "symbol", None))
        if symbol in out:
            out[symbol].append(str(getattr(skip, "reason_code", "") or ""))
    return {key: tuple(value) for key, value in out.items()}


def run_turkiye_new_money_uat(
    *,
    portfolio_view: Any,
    policy: Any,
    contexts: Sequence[TurkiyeFundPortfolioContext],
    available_amount: Decimal | int | str = Decimal("60000"),
    amount_currency: str = "TRY",
    extra_candidates: Sequence[Mapping[str, Any]] = (),
    extra_decisions: Sequence[PortfolioSecurityDecision] = (),
    price_by_symbol: Optional[Mapping[str, Any]] = None,
    conversion: Any = None,
    hybrid_policy: Optional[HybridExposureAllocationPolicy] = None,
    **kwargs: Any,
) -> TurkiyeNewMoneyUat:
    turkish_candidates = turkiye_new_money_candidates(
        contexts,
        price_by_symbol=price_by_symbol,
        currency=amount_currency,
    )
    candidates = [*extra_candidates, *turkish_candidates]
    decisions = [*extra_decisions, *turkiye_security_decisions(contexts)]
    plan = allocate_new_money(
        available_amount=available_amount,
        amount_currency=amount_currency,
        portfolio_view=portfolio_view,
        policy=policy,
        candidates=candidates,
        conversion=conversion,
        security_decisions=decisions,
        canonical_mappings=turkiye_exposure_mappings(contexts),
        hybrid_policy=hybrid_policy or HybridExposureAllocationPolicy(),
        enable_hybrid_exposure_allocation=False,
        **kwargs,
    )
    by_fund = {code: Decimal("0") for code in PILOT_TEFAS_FUND_CODES}
    other = Decimal("0")
    for rec in plan.recommendations:
        symbol = normalize_symbol(rec.symbol)
        amount = Decimal(str(rec.allocated_amount or 0))
        if symbol in by_fund:
            by_fund[symbol] += amount
        else:
            other += amount
    turkish_total = sum(by_fund.values(), Decimal("0"))
    explanations = tuple(
        format_turkiye_fund_explanation(context, allocation_try=by_fund.get(context.fund_code, 0))
        for context in contexts
    )
    return TurkiyeNewMoneyUat(
        plan=plan,
        turkish_allocated=turkish_total,
        other_allocated=other,
        total_allocated=Decimal(str(plan.total_allocated or 0)),
        residual_cash=Decimal(str(plan.residual_cash or 0)),
        by_fund=by_fund,
        skip_reasons=_turkish_skip_reasons(plan),
        explanations=explanations,
    )
