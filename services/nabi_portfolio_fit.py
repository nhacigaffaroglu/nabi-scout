"""Portfolio suitability for a recommendation candidate.

Company attractiveness stays in NABI Score / decision class.
This module answers only: is that company appropriate for THIS portfolio
with THIS contribution plan, using existing allocation and concentration rules.
No new thresholds. No FX math.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence, Tuple

from services.portfolio_intelligence_enrichment_contract import (
    CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT,
)
from services.wealth_new_money_allocation import (
    REASON_BELOW_MIN_TRADE,
    REASON_CANDIDATE,
    REASON_EXISTING_HOLDING_TOPUP,
    REASON_INSUFFICIENT_CASH,
    REASON_OVERWEIGHT_LAYER,
    REASON_STRONG_CANDIDATE,
    AllocationPlan,
)

FIT_GOOD = "GOOD_FIT"
FIT_NEUTRAL = "NEUTRAL_FIT"
FIT_POOR = "POOR_FIT"
FIT_UNKNOWN = "UNKNOWN"

FIT_REASON_UNDERWEIGHT_LAYER = "UNDERWEIGHT_LAYER"
FIT_REASON_EXISTING_POSITION_TOPUP = "EXISTING_POSITION_TOPUP"
FIT_REASON_NEW_DIVERSIFIER = "NEW_DIVERSIFIER"
FIT_REASON_CONCENTRATION_LIMIT = "CONCENTRATION_LIMIT"
FIT_REASON_OVERWEIGHT_LAYER = "OVERWEIGHT_LAYER"
FIT_REASON_INSUFFICIENT_BUDGET = "INSUFFICIENT_BUDGET"
FIT_REASON_MIN_TRADE_NOT_MET = "MIN_TRADE_NOT_MET"
FIT_REASON_WHOLE_SHARE_UNAFFORDABLE = "WHOLE_SHARE_UNAFFORDABLE"
FIT_REASON_NO_ALLOCATION_NEED = "NO_ALLOCATION_NEED"
FIT_REASON_INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"

AFFORDABLE = "AFFORDABLE"
UNAFFORDABLE = "UNAFFORDABLE"
AFFORDABILITY_UNKNOWN = "UNKNOWN"

_PROMOTE_CODES = frozenset(
    {REASON_EXISTING_HOLDING_TOPUP, REASON_STRONG_CANDIDATE, REASON_CANDIDATE}
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _symbol(row: Mapping[str, Any]) -> str:
    return _text(row.get("symbol")).upper()


def holding_weights(portfolio_view: Any) -> dict[str, float]:
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


def _market_value(row: Any) -> Optional[float]:
    value = getattr(row, "market_value", None)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class PortfolioFitAssessment:
    fit: str
    reason: str
    reason_codes: Tuple[str, ...]
    current_holding: bool
    current_weight_pct: Optional[float]
    post_allocation_weight_pct: Optional[float]
    affordability: str
    limitations: Tuple[str, ...]


def simulate_post_allocation_weight(
    symbol: str,
    *,
    portfolio_view: Any = None,
    allocation: Optional[AllocationPlan] = None,
) -> Tuple[Optional[float], Tuple[str, ...]]:
    """Read-only hypothetical weight after New Money quantity, same-currency only."""
    if portfolio_view is None or allocation is None:
        return None, ()
    rec = next(
        (
            item
            for item in allocation.recommendations
            if _text(item.symbol).upper() == symbol
        ),
        None,
    )
    if rec is None:
        return None, ()
    base = _text(getattr(portfolio_view, "base_currency", None)).upper()
    price_ccy = _text(rec.price_currency).upper()
    if not base or not price_ccy or base != price_ccy:
        return None, ("POST_WEIGHT_REQUIRES_SAME_CURRENCY",)
    total = getattr(portfolio_view, "priced_total_market_value", None)
    try:
        total_value = float(total)
    except (TypeError, ValueError):
        return None, ("INSUFFICIENT_EVIDENCE",)
    if total_value <= 0:
        return None, ("INSUFFICIENT_EVIDENCE",)
    current_mv = 0.0
    for row in getattr(portfolio_view, "priced_positions", None) or ():
        if _text(getattr(row, "symbol", None)).upper() != symbol:
            continue
        mv = _market_value(row)
        if mv is not None:
            current_mv += mv
    try:
        added = float(rec.quantity) * float(rec.price)
    except (TypeError, ValueError):
        return None, ("INSUFFICIENT_EVIDENCE",)
    if added <= 0:
        return None, ()
    post = (current_mv + added) / (total_value + added) * 100.0
    return post, ()


def assess_portfolio_fit(
    candidate: Optional[Mapping[str, Any]],
    *,
    portfolio_view: Any = None,
    allocation: Optional[AllocationPlan] = None,
) -> PortfolioFitAssessment:
    if candidate is None:
        return PortfolioFitAssessment(
            fit=FIT_UNKNOWN,
            reason="Değerlendirilecek fırsat yok.",
            reason_codes=(FIT_REASON_INSUFFICIENT_EVIDENCE,),
            current_holding=False,
            current_weight_pct=None,
            post_allocation_weight_pct=None,
            affordability=AFFORDABILITY_UNKNOWN,
            limitations=(),
        )
    symbol = _symbol(candidate)
    weights = holding_weights(portfolio_view)
    weight = weights.get(symbol)
    held = symbol in weights
    codes: list[str] = []
    limitations: list[str] = []
    affordability = AFFORDABILITY_UNKNOWN
    post_weight, post_limits = simulate_post_allocation_weight(
        symbol, portfolio_view=portfolio_view, allocation=allocation
    )
    limitations.extend(post_limits)

    skip = None
    if allocation is not None:
        skip = next(
            (
                item
                for item in allocation.skipped
                if _text(item.symbol).upper() == symbol
            ),
            None,
        )
    promoted = False
    promote_code = None
    if allocation is not None:
        rec = next(
            (
                item
                for item in allocation.recommendations
                if _text(item.symbol).upper() == symbol
                and item.reason_code in _PROMOTE_CODES
            ),
            None,
        )
        if rec is not None:
            promoted = True
            promote_code = rec.reason_code

    if skip is not None:
        if skip.reason_code == REASON_OVERWEIGHT_LAYER:
            codes.append(FIT_REASON_OVERWEIGHT_LAYER)
            return PortfolioFitAssessment(
                fit=FIT_POOR,
                reason=f"{symbol} açık katmanda fazla ağırlıkta; yeni ekleme uygun değil.",
                reason_codes=tuple(codes),
                current_holding=held,
                current_weight_pct=weight,
                post_allocation_weight_pct=post_weight,
                affordability=AFFORDABILITY_UNKNOWN,
                limitations=tuple(dict.fromkeys(limitations)),
            )
        if skip.reason_code == REASON_BELOW_MIN_TRADE:
            codes.append(FIT_REASON_MIN_TRADE_NOT_MET)
            affordability = UNAFFORDABLE
        elif skip.reason_code == REASON_INSUFFICIENT_CASH:
            codes.append(FIT_REASON_WHOLE_SHARE_UNAFFORDABLE)
            affordability = UNAFFORDABLE
        else:
            codes.append(FIT_REASON_INSUFFICIENT_BUDGET)
            affordability = UNAFFORDABLE

    if weight is not None and weight >= CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT:
        codes.append(FIT_REASON_CONCENTRATION_LIMIT)
        return PortfolioFitAssessment(
            fit=FIT_POOR,
            reason=(
                f"{symbol} mevcut ağırlık %{weight:.1f}; tekil yoğunluk eşiği "
                f"%{CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT:.0f}."
            ),
            reason_codes=tuple(dict.fromkeys(codes)),
            current_holding=held,
            current_weight_pct=weight,
            post_allocation_weight_pct=post_weight,
            affordability=affordability,
            limitations=tuple(dict.fromkeys(limitations)),
        )
    if (
        post_weight is not None
        and post_weight >= CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT
    ):
        codes.append(FIT_REASON_CONCENTRATION_LIMIT)
        return PortfolioFitAssessment(
            fit=FIT_POOR,
            reason=(
                f"{symbol} tahmini sonrası ağırlık %{post_weight:.1f}; "
                f"tekil yoğunluk eşiği %{CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT:.0f}."
            ),
            reason_codes=tuple(dict.fromkeys(codes)),
            current_holding=held,
            current_weight_pct=weight,
            post_allocation_weight_pct=post_weight,
            affordability=AFFORDABLE if affordability != UNAFFORDABLE else affordability,
            limitations=tuple(dict.fromkeys(limitations)),
        )

    if affordability == UNAFFORDABLE:
        reason = "Yeni para bu adayı mevcut katkı ve işlem eşiğiyle karşılayamıyor."
        return PortfolioFitAssessment(
            fit=FIT_POOR,
            reason=reason,
            reason_codes=tuple(dict.fromkeys(codes)),
            current_holding=held,
            current_weight_pct=weight,
            post_allocation_weight_pct=post_weight,
            affordability=UNAFFORDABLE,
            limitations=tuple(dict.fromkeys(limitations)),
        )

    if promoted:
        if promote_code == REASON_EXISTING_HOLDING_TOPUP:
            codes.append(FIT_REASON_EXISTING_POSITION_TOPUP)
            codes.append(FIT_REASON_UNDERWEIGHT_LAYER)
            reason = f"{symbol} mevcut pozisyon; açık katmanda tamamlanabilir."
        elif held:
            codes.append(FIT_REASON_EXISTING_POSITION_TOPUP)
            reason = f"{symbol} mevcut pozisyon; yeni para dağılımında uygun."
        else:
            codes.append(FIT_REASON_NEW_DIVERSIFIER)
            codes.append(FIT_REASON_UNDERWEIGHT_LAYER)
            reason = f"{symbol} yeni para dağılımında uygun aday."
        return PortfolioFitAssessment(
            fit=FIT_GOOD,
            reason=reason,
            reason_codes=tuple(dict.fromkeys(codes)),
            current_holding=held,
            current_weight_pct=weight,
            post_allocation_weight_pct=post_weight,
            affordability=AFFORDABLE,
            limitations=tuple(dict.fromkeys(limitations)),
        )

    if held and weight is not None:
        codes.append(FIT_REASON_NO_ALLOCATION_NEED)
        return PortfolioFitAssessment(
            fit=FIT_NEUTRAL,
            reason=f"{symbol} portföyde %{weight:.1f} ağırlıkta.",
            reason_codes=tuple(dict.fromkeys(codes)),
            current_holding=True,
            current_weight_pct=weight,
            post_allocation_weight_pct=post_weight,
            affordability=affordability,
            limitations=tuple(dict.fromkeys(limitations)),
        )
    if portfolio_view is None and allocation is None:
        return PortfolioFitAssessment(
            fit=FIT_UNKNOWN,
            reason="Portföy uyumu için dağılım kanıtı yok.",
            reason_codes=(FIT_REASON_INSUFFICIENT_EVIDENCE,),
            current_holding=False,
            current_weight_pct=None,
            post_allocation_weight_pct=None,
            affordability=AFFORDABILITY_UNKNOWN,
            limitations=(),
        )
    if not held:
        codes.append(FIT_REASON_NO_ALLOCATION_NEED)
        return PortfolioFitAssessment(
            fit=FIT_NEUTRAL,
            reason=f"{symbol} mevcut pozisyon değil; yoğunluk eşiği aşılmıyor.",
            reason_codes=tuple(dict.fromkeys(codes)),
            current_holding=False,
            current_weight_pct=weight,
            post_allocation_weight_pct=post_weight,
            affordability=affordability,
            limitations=tuple(dict.fromkeys(limitations)),
        )
    return PortfolioFitAssessment(
        fit=FIT_UNKNOWN,
        reason="Portföy uyumu belirsiz.",
        reason_codes=(FIT_REASON_INSUFFICIENT_EVIDENCE,),
        current_holding=held,
        current_weight_pct=weight,
        post_allocation_weight_pct=post_weight,
        affordability=AFFORDABILITY_UNKNOWN,
        limitations=tuple(dict.fromkeys(limitations)),
    )


def fit_label_tr(fit: str) -> str:
    return {
        FIT_GOOD: "İyi",
        FIT_NEUTRAL: "Nötr",
        FIT_POOR: "Zayıf",
        FIT_UNKNOWN: "Bilinmiyor",
    }.get(fit, fit)
