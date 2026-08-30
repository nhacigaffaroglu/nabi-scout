from __future__ import annotations

import unittest
from pathlib import Path

from services.hybrid_exposure_allocation_policy import (
    HybridPortfolioMode,
    resolve_hybrid_allocation_policy,
)
from services.nabi_decision_contract import INVESTMENT_ACTIONS
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)
from services.portfolio_intelligence_enrichment_contract import (
    CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT,
)
from services.portfolio_security_decision_contract import (
    DECISION_AVOID,
    DECISION_CONSIDER_NEW_POSITION,
    DECISION_CONSIDER_TOP_UP,
    DECISION_HOLD,
    DECISION_INSUFFICIENT_DATA,
    DECISION_REDUCE,
    DECISION_REVIEW,
    DECISION_WATCH,
    INCREASE_DECISIONS,
    PortfolioSecurityContext,
    REASON_CONCENTRATION_LIMIT,
    REASON_ECONOMIC_EXPOSURE_UNSAFE,
    REASON_ELIGIBLE_TO_INCREASE,
    REASON_LAYER_UNDERWEIGHT_NOT_AUTHORITY,
    REASON_LOOKTHROUGH_NOT_IN_SCOPE,
    REASON_MATERIAL_NEGATIVE_SIGNAL,
    REASON_PARTICIPATION_NOT_UYGUN,
    REASON_POSITIVE_SIGNAL_NOT_AUTHORITY,
    REASON_RESEARCH_NOT_ALLOWED,
    REASON_SI_INSUFFICIENT,
    REASON_SI_MISSING,
    REASON_SI_STALE,
    REASON_SIGNAL_CONFLICT,
    REASON_UNSUPPORTED_INSTRUMENT,
    REASON_YENI_NOT_ACTIVE_RESEARCH,
)
from services.portfolio_security_decision_engine import evaluate_portfolio_security_decision
from services.research_workflow_service import DEFAULT_RESEARCH_STATUS
from services.security_intelligence_contract import (
    STATE_ATTRACTIVE,
    STATE_INSUFFICIENT_DATA,
    STATE_WATCH,
)
from services.security_master_contract import INSTRUMENT_EQUITY, INSTRUMENT_ETF


ENGINE = Path("services/portfolio_security_decision_engine.py")
CONTRACT = Path("services/portfolio_security_decision_contract.py")


def _healthy(**overrides) -> PortfolioSecurityContext:
    payload = dict(
        symbol="CRM",
        participation_status=PARTICIPATION_STATUS_UYGUN,
        research_allowed=True,
        si_state=STATE_ATTRACTIVE,
        si_score=72.0,
        si_confidence=0.8,
        si_data_quality="STRONG",
        si_as_of="2026-08-29",
        is_holding=True,
        quantity=10.0,
        market_value=2500.0,
        portfolio_weight=5.0,
        concentration_ceiling=CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT,
        economic_exposure_status=HybridPortfolioMode.STRICT.value,
        instrument_type=INSTRUMENT_EQUITY,
        market="US",
        as_of="2026-08-29",
    )
    payload.update(overrides)
    return PortfolioSecurityContext(**payload)


class PortfolioSecurityDecisionMatrixTests(unittest.TestCase):
    def test_a_uygun_allowed_attractive_allows_increase(self) -> None:
        result = evaluate_portfolio_security_decision(_healthy())
        self.assertTrue(result.exposure_increase_allowed)
        self.assertEqual(result.decision, DECISION_CONSIDER_TOP_UP)
        self.assertIn(REASON_ELIGIBLE_TO_INCREASE, result.reason_codes)
        self.assertNotIn("BUY", result.decision)
        self.assertNotIn("SELL", result.decision)
        self.assertIsNone(result.to_dict().get("allocated_amount"))

    def test_a_active_research_non_holding_may_consider_new(self) -> None:
        result = evaluate_portfolio_security_decision(
            _healthy(is_holding=False, quantity=None, market_value=None, portfolio_weight=None, research_status="INCELEMEDE", candidate_exists=True)
        )
        self.assertTrue(result.exposure_increase_allowed)
        self.assertEqual(result.decision, DECISION_CONSIDER_NEW_POSITION)

    def test_b_kontrol_et_blocks_increase(self) -> None:
        result = evaluate_portfolio_security_decision(
            _healthy(participation_status=PARTICIPATION_STATUS_KONTROL_ET)
        )
        self.assertFalse(result.exposure_increase_allowed)
        self.assertEqual(result.decision, DECISION_REVIEW)
        self.assertIn(REASON_PARTICIPATION_NOT_UYGUN, result.blocking_reasons)

    def test_c_uygun_degil_blocks_increase(self) -> None:
        result = evaluate_portfolio_security_decision(
            _healthy(participation_status=PARTICIPATION_STATUS_UYGUN_DEGIL)
        )
        self.assertFalse(result.exposure_increase_allowed)
        self.assertEqual(result.decision, DECISION_HOLD)
        self.assertNotEqual(result.decision, "SELL")

    def test_d_research_allowed_false_blocks_increase(self) -> None:
        result = evaluate_portfolio_security_decision(_healthy(research_allowed=False))
        self.assertFalse(result.exposure_increase_allowed)
        self.assertIn(REASON_RESEARCH_NOT_ALLOWED, result.blocking_reasons)

    def test_e_research_allowed_missing_blocks_increase(self) -> None:
        result = evaluate_portfolio_security_decision(_healthy(research_allowed=None))
        self.assertFalse(result.exposure_increase_allowed)
        self.assertIn(REASON_RESEARCH_NOT_ALLOWED, result.blocking_reasons)
        self.assertIsNone(result.research_allowed)

    def test_f_concentration_breached_blocks_increase(self) -> None:
        result = evaluate_portfolio_security_decision(_healthy(portfolio_weight=21.0))
        self.assertFalse(result.exposure_increase_allowed)
        self.assertEqual(result.decision, DECISION_REDUCE)
        self.assertIn(REASON_CONCENTRATION_LIMIT, result.blocking_reasons)

    def test_g_economic_unsafe_blocks_increase(self) -> None:
        result = evaluate_portfolio_security_decision(
            _healthy(economic_exposure_status=HybridPortfolioMode.UNSAFE.value)
        )
        self.assertFalse(result.exposure_increase_allowed)
        self.assertIn(REASON_ECONOMIC_EXPOSURE_UNSAFE, result.blocking_reasons)

    def test_h_positive_signal_does_not_create_increase(self) -> None:
        result = evaluate_portfolio_security_decision(
            _healthy(si_state=STATE_WATCH, verified_material_positive=True)
        )
        self.assertFalse(result.exposure_increase_allowed)
        self.assertEqual(result.decision, DECISION_WATCH)
        self.assertIn(REASON_POSITIVE_SIGNAL_NOT_AUTHORITY, result.reason_codes)
        self.assertNotIn(result.decision, INCREASE_DECISIONS)

    def test_i_material_negative_escalates_review(self) -> None:
        result = evaluate_portfolio_security_decision(
            _healthy(verified_material_negative=True)
        )
        self.assertFalse(result.exposure_increase_allowed)
        self.assertEqual(result.decision, DECISION_REVIEW)
        self.assertIn(REASON_MATERIAL_NEGATIVE_SIGNAL, result.blocking_reasons)

    def test_j_signal_conflict_fail_closed(self) -> None:
        result = evaluate_portfolio_security_decision(_healthy(signal_conflict=True))
        self.assertFalse(result.exposure_increase_allowed)
        self.assertEqual(result.decision, DECISION_REVIEW)
        self.assertIn(REASON_SIGNAL_CONFLICT, result.blocking_reasons)

    def test_k_si_insufficient_no_positive_action(self) -> None:
        result = evaluate_portfolio_security_decision(
            _healthy(si_state=STATE_INSUFFICIENT_DATA)
        )
        self.assertFalse(result.exposure_increase_allowed)
        self.assertEqual(result.decision, DECISION_INSUFFICIENT_DATA)
        self.assertIn(REASON_SI_INSUFFICIENT, result.blocking_reasons)

    def test_l_missing_persisted_si_fail_closed(self) -> None:
        result = evaluate_portfolio_security_decision(_healthy(si_state=None))
        self.assertFalse(result.exposure_increase_allowed)
        self.assertEqual(result.decision, DECISION_INSUFFICIENT_DATA)
        self.assertIn(REASON_SI_MISSING, result.blocking_reasons)

    def test_fresh_attractive_si_preserves_increase(self) -> None:
        result = evaluate_portfolio_security_decision(_healthy(stale_inputs=()))
        self.assertTrue(result.exposure_increase_allowed)
        self.assertEqual(result.decision, DECISION_CONSIDER_TOP_UP)

    def test_stale_si_blocks_exposure_increase(self) -> None:
        result = evaluate_portfolio_security_decision(_healthy(stale_inputs=("si",)))
        self.assertFalse(result.exposure_increase_allowed)
        self.assertNotIn(result.decision, INCREASE_DECISIONS)
        self.assertEqual(result.decision, DECISION_REVIEW)
        self.assertIn(REASON_SI_STALE, result.blocking_reasons)

    def test_stale_attractive_cannot_consider(self) -> None:
        held = evaluate_portfolio_security_decision(
            _healthy(si_state=STATE_ATTRACTIVE, stale_inputs=("si",))
        )
        fresh_new = evaluate_portfolio_security_decision(
            _healthy(
                is_holding=False,
                quantity=None,
                market_value=None,
                portfolio_weight=None,
                research_status="INCELEMEDE",
                candidate_exists=True,
            )
        )
        stale_new = evaluate_portfolio_security_decision(
            _healthy(
                is_holding=False,
                quantity=None,
                market_value=None,
                portfolio_weight=None,
                research_status="INCELEMEDE",
                candidate_exists=True,
                stale_inputs=("si",),
            )
        )
        self.assertEqual(held.decision, DECISION_REVIEW)
        self.assertTrue(fresh_new.exposure_increase_allowed)
        self.assertEqual(fresh_new.decision, DECISION_CONSIDER_NEW_POSITION)
        self.assertFalse(stale_new.exposure_increase_allowed)
        self.assertEqual(stale_new.decision, DECISION_INSUFFICIENT_DATA)
        self.assertNotIn(stale_new.decision, INCREASE_DECISIONS)

    def test_m_holding_blocked_participation_is_not_sell(self) -> None:
        result = evaluate_portfolio_security_decision(
            _healthy(participation_status=PARTICIPATION_STATUS_UYGUN_DEGIL)
        )
        self.assertFalse(result.exposure_increase_allowed)
        self.assertEqual(result.decision, DECISION_HOLD)
        self.assertNotIn(result.decision, INCREASE_DECISIONS)
        self.assertNotEqual(result.decision, DECISION_REDUCE)
        self.assertNotEqual(result.decision, DECISION_AVOID)

    def test_n_yeni_candidate_lifecycle_unchanged(self) -> None:
        result = evaluate_portfolio_security_decision(
            _healthy(
                symbol="ADBE",
                is_holding=False,
                quantity=None,
                market_value=None,
                portfolio_weight=None,
                candidate_exists=True,
                research_status=DEFAULT_RESEARCH_STATUS,
            )
        )
        self.assertFalse(result.exposure_increase_allowed)
        self.assertEqual(result.research_status, "YENI")
        self.assertEqual(result.decision, DECISION_WATCH)
        self.assertIn(REASON_YENI_NOT_ACTIVE_RESEARCH, result.blocking_reasons)
        self.assertNotIn(result.decision, INCREASE_DECISIONS)

    def test_o_unsupported_etf_lookthrough_bist_equity_supported(self) -> None:
        etf = evaluate_portfolio_security_decision(
            _healthy(symbol="SPUS", instrument_type=INSTRUMENT_ETF)
        )
        bist = evaluate_portfolio_security_decision(
            _healthy(symbol="BIMAS", market="TR")
        )
        lookthrough = evaluate_portfolio_security_decision(
            _healthy(lookthrough_only=True)
        )
        self.assertFalse(etf.exposure_increase_allowed)
        self.assertEqual(etf.decision, DECISION_INSUFFICIENT_DATA)
        self.assertIn(REASON_UNSUPPORTED_INSTRUMENT, etf.blocking_reasons)
        self.assertTrue(bist.exposure_increase_allowed)
        self.assertEqual(bist.decision, DECISION_CONSIDER_TOP_UP)
        self.assertNotIn(REASON_UNSUPPORTED_INSTRUMENT, bist.blocking_reasons)
        self.assertFalse(lookthrough.exposure_increase_allowed)
        self.assertEqual(lookthrough.decision, DECISION_INSUFFICIENT_DATA)
        self.assertIn(REASON_LOOKTHROUGH_NOT_IN_SCOPE, lookthrough.blocking_reasons)

    def test_p_underweight_alone_does_not_create_increase(self) -> None:
        result = evaluate_portfolio_security_decision(
            _healthy(
                si_state=STATE_WATCH,
                target_layer="equity",
                layer_current_weight=10.0,
                layer_target_weight=40.0,
            )
        )
        self.assertFalse(result.exposure_increase_allowed)
        self.assertEqual(result.decision, DECISION_WATCH)
        self.assertIn(REASON_LAYER_UNDERWEIGHT_NOT_AUTHORITY, result.reason_codes)

    def test_q_attractive_does_not_bypass_participation(self) -> None:
        result = evaluate_portfolio_security_decision(
            _healthy(participation_status=PARTICIPATION_STATUS_KONTROL_ET)
        )
        self.assertFalse(result.exposure_increase_allowed)
        self.assertIn(REASON_PARTICIPATION_NOT_UYGUN, result.blocking_reasons)

    def test_r_uygun_alone_does_not_create_increase(self) -> None:
        result = evaluate_portfolio_security_decision(
            _healthy(si_state=None, si_score=None, si_confidence=None, si_data_quality=None)
        )
        self.assertFalse(result.exposure_increase_allowed)
        self.assertEqual(result.decision, DECISION_INSUFFICIENT_DATA)


class PortfolioSecurityDecisionParityTests(unittest.TestCase):
    def test_research_allowed_is_independent_of_si_state(self) -> None:
        result = evaluate_portfolio_security_decision(
            _healthy(research_allowed=False, si_state=STATE_ATTRACTIVE)
        )
        self.assertEqual(result.security_intelligence_state, STATE_ATTRACTIVE)
        self.assertFalse(result.research_allowed)
        self.assertFalse(result.exposure_increase_allowed)
        self.assertIn(REASON_RESEARCH_NOT_ALLOWED, result.blocking_reasons)

    def test_engine_does_not_use_facade_live_si(self) -> None:
        engine = ENGINE.read_text(encoding="utf-8")
        contract = CONTRACT.read_text(encoding="utf-8")
        for source in (engine, contract):
            self.assertNotIn("nabi_intelligence_facade", source)
            self.assertNotIn("get_investment_intelligence", source)
            self.assertNotIn("allow_sec_cache_replay", source)
            self.assertNotIn("evaluate_security_intelligence", source)
        self.assertIn("persisted", contract)
        self.assertIn("research_allowed", contract)
        self.assertIn("8E.4", contract)

    def test_vocabulary_reuses_v3_increase_names_without_buy_sell(self) -> None:
        self.assertIn(DECISION_CONSIDER_NEW_POSITION, INVESTMENT_ACTIONS)
        self.assertIn(DECISION_CONSIDER_TOP_UP, INVESTMENT_ACTIONS)
        self.assertNotIn("ADD", INCREASE_DECISIONS)
        self.assertNotIn("BUY", INCREASE_DECISIONS)
        self.assertNotIn("SELL", INCREASE_DECISIONS)

    def test_hybrid_remains_off(self) -> None:
        self.assertFalse(resolve_hybrid_allocation_policy().enabled)


if __name__ == "__main__":
    unittest.main()
