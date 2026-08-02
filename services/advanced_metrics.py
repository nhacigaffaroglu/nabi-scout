from __future__ import annotations
from typing import Any, Dict, Optional

def num(value: Any) -> Optional[float]:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None

def div(a, b):
    return None if a is None or b in (None, 0) else a / b

def calculate(candidate: Dict[str, Any]) -> Dict[str, Optional[float]]:
    market_cap = num(candidate.get("market_cap"))
    net_debt = num(candidate.get("net_debt"))
    revenue = num(candidate.get("revenue"))
    operating_margin = num(candidate.get("operating_margin"))
    free_cash_flow = num(candidate.get("free_cash_flow"))
    pe = num(candidate.get("pe_ratio"))
    eps_cagr = num(candidate.get("eps_cagr_3y"))

    operating_income = (
        revenue * operating_margin / 100
        if revenue is not None and operating_margin is not None
        else None
    )
    enterprise_value = (
        market_cap + (net_debt or 0)
        if market_cap is not None else None
    )
    ev_to_ebit = div(enterprise_value, operating_income)
    price_to_fcf = div(market_cap, free_cash_flow)

    peg = None
    if pe is not None and eps_cagr is not None and eps_cagr > 0:
        peg = pe / eps_cagr

    return {
        "operating_income_estimated": operating_income,
        "enterprise_value": enterprise_value,
        "ev_to_ebit": ev_to_ebit,
        "price_to_fcf": price_to_fcf,
        "peg_ratio_calculated": peg,
        "owner_earnings": free_cash_flow,
    }
