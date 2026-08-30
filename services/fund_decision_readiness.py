"""8E and New Money readiness for funds. Fail-closed. No allocation."""

from __future__ import annotations

from typing import Optional

from services.fund_intelligence_engine import (
    evaluate_fund_intelligence,
    evaluate_official_fund_intelligence,
)
from services.fund_product_contract import (
    READINESS_NEEDS_MORE_DATA,
    READINESS_READY_NOW,
    FundIntelligenceEvaluation,
    OfficialFundMandate,
)
from services.official_sp_funds_product import default_official_sp_funds_provider
from services.hybrid_exposure_allocation_policy import HybridPortfolioMode
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)
from services.portfolio_security_decision_contract import (
    DECISION_INSUFFICIENT_DATA,
    REASON_ECONOMIC_EXPOSURE_UNAVAILABLE,
    REASON_FUND_INTELLIGENCE_MISSING,
    REASON_PARTICIPATION_NOT_UYGUN,
    PortfolioSecurityContext,
    PortfolioSecurityDecision,
)
from services.portfolio_security_decision_engine import (
    evaluate_portfolio_security_decision,
)
from services.security_master_contract import INSTRUMENT_ETF

REASON_FUND_PARTICIPATION_NOT_ACCEPTABLE = "FUND_PARTICIPATION_NOT_ACCEPTABLE"


def fund_intelligence_to_context(
    view: FundIntelligenceEvaluation,
    *,
    is_holding: bool = False,
    portfolio_weight: Optional[float] = None,
    economic_exposure_available: bool = False,
    layer_current_weight: Optional[float] = None,
    layer_target_weight: Optional[float] = None,
    market: str = "US",
    adverse_participation: bool = False,
) -> PortfolioSecurityContext:
    """Map Fund Intelligence onto the generic 8E intelligence boundary."""
    generic = view.generic_intelligence()
    if adverse_participation or view.participation.status == "ADVERSE":
        participation = PARTICIPATION_STATUS_UYGUN_DEGIL
    elif view.participation.eligible:
        participation = PARTICIPATION_STATUS_UYGUN
    else:
        participation = None
    exposure = (
        HybridPortfolioMode.STRICT.value
        if economic_exposure_available
        else HybridPortfolioMode.UNAVAILABLE.value
    )
    return PortfolioSecurityContext(
        symbol=view.symbol,
        participation_status=participation,
        research_allowed=True if view.participation.eligible else False,
        si_state=generic["si_state"],
        si_score=generic["si_score"],
        si_confidence=generic["si_confidence"],
        si_data_quality=generic["si_data_quality"],
        si_as_of=generic["si_as_of"],
        is_holding=is_holding,
        portfolio_weight=portfolio_weight,
        layer_current_weight=layer_current_weight,
        layer_target_weight=layer_target_weight,
        economic_exposure_status=exposure,
        instrument_type=INSTRUMENT_ETF,
        market=market,
    )


def evaluate_fund_portfolio_decision(
    view: FundIntelligenceEvaluation,
    *,
    is_holding: bool = False,
    portfolio_weight: Optional[float] = None,
    economic_exposure_available: bool = False,
    layer_current_weight: Optional[float] = None,
    layer_target_weight: Optional[float] = None,
    market: str = "US",
    adverse_participation: bool = False,
) -> PortfolioSecurityDecision:
    return evaluate_portfolio_security_decision(
        fund_intelligence_to_context(
            view,
            is_holding=is_holding,
            portfolio_weight=portfolio_weight,
            economic_exposure_available=economic_exposure_available,
            layer_current_weight=layer_current_weight,
            layer_target_weight=layer_target_weight,
            market=market,
            adverse_participation=adverse_participation,
        )
    )


def evaluate_official_fund_decision(
    symbol: str,
    *,
    is_holding: bool = False,
    portfolio_weight: Optional[float] = None,
    economic_exposure_available: bool = False,
    provider: Optional[object] = None,
) -> PortfolioSecurityDecision:
    """In-process official evidence only. No holdings fetch. Fail closed."""
    fund = str(symbol or "").strip().upper()
    try:
        resolved = provider or default_official_sp_funds_provider()
        if not resolved.supports(fund):
            return _blocked_fund_decision(
                fund,
                fund_intelligence_ready=False,
                participation_acceptable=False,
                economic_exposure_available=economic_exposure_available,
            )
        view = evaluate_official_fund_intelligence(fund, provider=resolved)
        return evaluate_fund_portfolio_decision(
            view,
            is_holding=is_holding,
            portfolio_weight=portfolio_weight,
            economic_exposure_available=economic_exposure_available,
        )
    except Exception:
        return _blocked_fund_decision(
            fund,
            fund_intelligence_ready=False,
            participation_acceptable=False,
            economic_exposure_available=economic_exposure_available,
        )


def _blocked_fund_decision(
    symbol: str,
    *,
    fund_intelligence_ready: bool,
    participation_acceptable: bool,
    economic_exposure_available: bool,
) -> PortfolioSecurityDecision:
    payload = evaluate_fund_eight_e_readiness(
        symbol=symbol,
        fund_intelligence_ready=fund_intelligence_ready,
        participation_acceptable=participation_acceptable,
        economic_exposure_available=economic_exposure_available,
    )
    reasons = tuple(payload["blocking_reasons"])
    return PortfolioSecurityDecision(
        symbol=str(payload["symbol"]),
        decision=str(payload["decision"]),
        confidence="LOW",
        exposure_increase_allowed=False,
        participation_status=None,
        research_allowed=None,
        security_intelligence_state=None,
        primary_reasons=reasons[:3],
        blocking_reasons=reasons,
        reason_codes=reasons,
    )


def evaluate_fund_eight_e_readiness(
    *,
    symbol: str,
    fund_intelligence_ready: bool,
    participation_acceptable: bool,
    economic_exposure_available: bool,
) -> dict[str, object]:
    """Funds stay fail-closed until Fund Intelligence + Participation are sufficient."""
    fund = str(symbol or "").strip().upper()
    reasons: list[str] = []
    if not fund_intelligence_ready:
        reasons.append(REASON_FUND_INTELLIGENCE_MISSING)
    if not participation_acceptable:
        reasons.append(REASON_FUND_PARTICIPATION_NOT_ACCEPTABLE)
        reasons.append(REASON_PARTICIPATION_NOT_UYGUN)
    if not economic_exposure_available:
        reasons.append(REASON_ECONOMIC_EXPOSURE_UNAVAILABLE)
    return {
        "symbol": fund,
        "decision": DECISION_INSUFFICIENT_DATA,
        "exposure_increase_allowed": False,
        "blocking_reasons": tuple(dict.fromkeys(reasons)),
        "enabled": False,
    }


def new_money_layer_from_mandate(mandate: Optional[OfficialFundMandate]) -> Optional[str]:
    if mandate is None:
        return None
    return mandate.primary_layer


def evaluate_fund_new_money_readiness(
    *,
    mandate: Optional[OfficialFundMandate],
    hybrid_off: bool,
    exposure_complete: bool,
) -> dict[str, object]:
    layer = new_money_layer_from_mandate(mandate)
    return {
        "economic_layer": layer,
        "hybrid_off_preserved": bool(hybrid_off),
        "exposure_complete": bool(exposure_complete),
        "allocates_money": False,
        "forced_deployment": False,
        "readiness": READINESS_READY_NOW if layer and exposure_complete else READINESS_NEEDS_MORE_DATA,
        "limitation": "" if exposure_complete else "EXPOSURE_CLASSIFICATION_INCOMPLETE",
    }
