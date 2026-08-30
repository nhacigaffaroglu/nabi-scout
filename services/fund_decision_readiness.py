"""8E and New Money readiness for funds. Fail-closed. No allocation."""

from __future__ import annotations

from typing import Optional

from services.fund_product_contract import (
    READINESS_NEEDS_MORE_DATA,
    READINESS_READY_NOW,
    OfficialFundMandate,
)
from services.portfolio_security_decision_contract import (
    DECISION_INSUFFICIENT_DATA,
    REASON_ECONOMIC_EXPOSURE_UNAVAILABLE,
    REASON_PARTICIPATION_NOT_UYGUN,
    REASON_UNSUPPORTED_INSTRUMENT,
)
REASON_FUND_INTELLIGENCE_MISSING = "FUND_INTELLIGENCE_MISSING"
REASON_FUND_PARTICIPATION_NOT_ACCEPTABLE = "FUND_PARTICIPATION_NOT_ACCEPTABLE"


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
    reasons.append(REASON_UNSUPPORTED_INSTRUMENT)
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
