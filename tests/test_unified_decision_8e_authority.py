from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from services.nabi_decision_contract import (
    ACTION_CONSIDER_NEW_POSITION,
    ACTION_CONSIDER_TOP_UP,
    ACTION_NO_ACTION,
    REASON_8E_AUTHORITY_MISSING,
    REASON_8E_DECISION_MISMATCH,
    REASON_8E_EXPOSURE_BLOCKED,
)
from services.nabi_decision_orchestrator import evaluate_candidate_investment
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.portfolio_security_decision_contract import PortfolioSecurityDecision
from services.wealth_new_money_allocation import (
    REASON_EXISTING_HOLDING_TOPUP,
    REASON_STRONG_CANDIDATE,
    AllocationPlan,
    AllocationRecommendation,
)


def candidate(symbol="CRM"):
    return {
        "symbol": symbol,
        "company_name": symbol,
        "decision": "GÜÇLÜ ADAY",
        "participation_status": PARTICIPATION_STATUS_UYGUN,
        "research_status": "TAMAMLANDI",
        "research_confidence_level": "YÜKSEK",
        "nabi_score": 90.0,
        "current_price": 100.0,
        "data_completeness": 90.0,
        "data_source": "scanner",
        "main_reason": "Canonical evidence",
        "thesis_strengths": ["Canonical evidence"],
        "growth_catalysts": "Observed",
        "critical_risk": "Known",
        "last_scanned_at": "2026-08-20T10:00:00+00:00",
    }


def rec(symbol, action):
    reason = (
        REASON_EXISTING_HOLDING_TOPUP
        if action == ACTION_CONSIDER_TOP_UP
        else REASON_STRONG_CANDIDATE
    )
    return AllocationRecommendation(
        symbol=symbol,
        existing_or_new=(
            "existing"
            if action == ACTION_CONSIDER_TOP_UP
            else "new"
        ),
        layer="equity",
        decision="GÜÇLÜ ADAY",
        price=Decimal("100"),
        price_currency="TRY",
        quantity=Decimal("1"),
        allocated_amount=Decimal("20000"),
        reason_code=reason,
        reason_text=reason,
    )


def plan(symbol, action):
    row = rec(symbol, action)
    return AllocationPlan(
        input_amount=Decimal("60000"),
        currency="TRY",
        recommendations=(row,),
        total_allocated=row.allocated_amount,
        residual_cash=Decimal("40000"),
        skipped=(),
    )


def psd(symbol, decision, *, increase):
    return PortfolioSecurityDecision(
        symbol=symbol,
        decision=decision,
        confidence="HIGH",
        exposure_increase_allowed=increase,
        participation_status=PARTICIPATION_STATUS_UYGUN,
        research_allowed=True,
        security_intelligence_state="ATTRACTIVE",
    )


def evaluate_at_8e_gate(*args, **kwargs):
    """Reach the deployment gate without testing timing again."""
    with patch(
        "services.nabi_decision_orchestrator.derive_timing_state",
        return_value="FAVORABLE",
    ):
        return evaluate_candidate_investment(*args, **kwargs)


def test_missing_8e_cannot_promote_candidate_to_consider():
    item = evaluate_at_8e_gate(
        candidate(),
        allocation=plan("CRM", ACTION_CONSIDER_NEW_POSITION),
    )
    assert item.final_action == ACTION_NO_ACTION
    assert REASON_8E_AUTHORITY_MISSING in item.reason_codes


def test_blocking_8e_cannot_be_overridden_by_allocation():
    item = evaluate_at_8e_gate(
        candidate(),
        allocation=plan("CRM", ACTION_CONSIDER_NEW_POSITION),
        security_decision=psd("CRM", "WATCH", increase=False),
    )
    assert item.final_action == ACTION_NO_ACTION
    assert REASON_8E_EXPOSURE_BLOCKED in item.reason_codes


def test_8e_and_allocation_must_agree_on_increase_action():
    item = evaluate_at_8e_gate(
        candidate(),
        allocation=plan("CRM", ACTION_CONSIDER_NEW_POSITION),
        security_decision=psd(
            "CRM",
            ACTION_CONSIDER_TOP_UP,
            increase=True,
        ),
    )
    assert item.final_action == ACTION_NO_ACTION
    assert REASON_8E_DECISION_MISMATCH in item.reason_codes


def test_matching_8e_and_allocation_can_emit_consider():
    item = evaluate_at_8e_gate(
        candidate(),
        allocation=plan("CRM", ACTION_CONSIDER_NEW_POSITION),
        security_decision=psd(
            "CRM",
            ACTION_CONSIDER_NEW_POSITION,
            increase=True,
        ),
    )
    assert item.final_action == ACTION_CONSIDER_NEW_POSITION


def test_firsatlar_resolves_8e_before_v3():
    source = Path("pages/5_Firsatlar.py").read_text(encoding="utf-8")
    resolve_at = source.index(
        "security_decisions = resolve_adviser_security_decisions("
    )
    v3_at = source.index("decision_v3 = build_nabi_decision_v3(")
    assert resolve_at < v3_at
    assert "security_decisions=security_decisions" in source


def test_adviser_resolves_8e_before_v3():
    source = Path("services/nabi_adviser_context.py").read_text(
        encoding="utf-8"
    )
    resolve_at = source.index(
        "v3_security_decisions = resolve_adviser_security_decisions("
    )
    v3_at = source.index("view = build_nabi_decision_v3(")
    assert resolve_at < v3_at
    assert "security_decisions=v3_security_decisions" in source
