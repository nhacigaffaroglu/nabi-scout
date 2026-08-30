from __future__ import annotations

import unittest
from pathlib import Path

from services.fund_decision_readiness import (
    TURKIYE_FUND_8E_INSTRUMENT,
    TURKIYE_FUND_8E_MARKET,
    evaluate_fund_portfolio_decision,
    evaluate_official_fund_decision,
    fund_intelligence_to_context,
)
from services.fund_intelligence_engine import evaluate_official_fund_intelligence
from services.fund_product_contract import PILOT_FUND_SYMBOLS, PILOT_TEFAS_FUND_CODES
from services.official_tefas_product import default_tefas_fund_provider
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.portfolio_security_decision_contract import (
    DECISION_INSUFFICIENT_DATA,
    DECISION_WATCH,
    REASON_ECONOMIC_EXPOSURE_UNAVAILABLE,
    REASON_SI_NOT_ATTRACTIVE,
    REASON_SI_WATCH,
)
from services.wealth_new_money_allocation import allocate_new_money

TEFAS = Path("services/official_tefas_product.py")
READINESS = Path("services/fund_decision_readiness.py")
EIGHT_E = Path("services/portfolio_security_decision_engine.py")
NEW_MONEY = Path("services/wealth_new_money_allocation.py")
BIST = Path("services/bist_refresh_contract.py")
US_SI = Path("services/security_intelligence_engine.py")
PARTICIPATION = Path("services/official_turkiye_fund_participation.py")

FROZEN_FI = {
    "AIS": (70.39, "WATCH"),
    "ZPE": (66.32, "WATCH"),
    "IAT": (60.49, "NEUTRAL"),
}


class TurkiyeFundEightETests(unittest.TestCase):
    def test_default_fail_closed_without_economic_exposure(self) -> None:
        for code in PILOT_TEFAS_FUND_CODES:
            decision = evaluate_official_fund_decision(code)
            self.assertEqual(decision.decision, DECISION_INSUFFICIENT_DATA)
            self.assertFalse(decision.exposure_increase_allowed)
            self.assertIn(REASON_ECONOMIC_EXPOSURE_UNAVAILABLE, decision.blocking_reasons)
            self.assertNotIn("TURKIYE_FUND_8E_NOT_STARTED", decision.reason_codes)
            self.assertEqual(decision.participation_status, PARTICIPATION_STATUS_UYGUN)
            self.assertTrue(decision.research_allowed)

    def test_watch_and_neutral_do_not_increase(self) -> None:
        expected_reason = {
            "AIS": REASON_SI_WATCH,
            "ZPE": REASON_SI_WATCH,
            "IAT": REASON_SI_NOT_ATTRACTIVE,
        }
        for code, (score, state) in FROZEN_FI.items():
            decision = evaluate_official_fund_decision(
                code,
                is_holding=True,
                portfolio_weight=5.0,
                economic_exposure_available=True,
            )
            self.assertEqual(decision.decision, DECISION_WATCH)
            self.assertFalse(decision.exposure_increase_allowed)
            self.assertEqual(decision.participation_status, PARTICIPATION_STATUS_UYGUN)
            self.assertTrue(decision.research_allowed)
            self.assertEqual(decision.security_intelligence_state, state)
            self.assertEqual(decision.security_intelligence_score, score)
            self.assertIn(expected_reason[code], decision.blocking_reasons)

    def test_context_is_turkish_fund_not_us_etf(self) -> None:
        view = evaluate_official_fund_intelligence("AIS")
        ctx = fund_intelligence_to_context(
            view,
            is_holding=True,
            portfolio_weight=5.0,
            economic_exposure_available=True,
        )
        self.assertEqual(ctx.market, TURKIYE_FUND_8E_MARKET)
        self.assertEqual(ctx.instrument_type, TURKIYE_FUND_8E_INSTRUMENT)
        self.assertEqual(ctx.participation_status, PARTICIPATION_STATUS_UYGUN)
        self.assertTrue(ctx.research_allowed)
        zpe = fund_intelligence_to_context(evaluate_official_fund_intelligence("ZPE"))
        self.assertEqual(zpe.market, TURKIYE_FUND_8E_MARKET)
        self.assertEqual(zpe.instrument_type, TURKIYE_FUND_8E_INSTRUMENT)

    def test_tefas_provider_path_is_used(self) -> None:
        provider = default_tefas_fund_provider()
        for code in PILOT_TEFAS_FUND_CODES:
            via_default = evaluate_official_fund_decision(
                code,
                is_holding=True,
                portfolio_weight=5.0,
                economic_exposure_available=True,
            )
            via_provider = evaluate_official_fund_decision(
                code,
                is_holding=True,
                portfolio_weight=5.0,
                economic_exposure_available=True,
                provider=provider,
            )
            self.assertEqual(via_default.decision, via_provider.decision)
            self.assertEqual(via_default.security_intelligence_score, via_provider.security_intelligence_score)
            self.assertTrue(provider.supports(code))

    def test_fi_scores_remain_frozen(self) -> None:
        for code, (score, state) in FROZEN_FI.items():
            view = evaluate_official_fund_intelligence(code)
            self.assertEqual(view.score, score)
            self.assertEqual(view.state, state)
            self.assertTrue(view.participation.eligible)
            mapped = evaluate_fund_portfolio_decision(
                view,
                is_holding=True,
                portfolio_weight=5.0,
                economic_exposure_available=True,
            )
            self.assertEqual(mapped.security_intelligence_score, score)
            self.assertEqual(mapped.security_intelligence_state, state)

    def test_no_snapshot_or_new_money_wiring(self) -> None:
        source = READINESS.read_text(encoding="utf-8")
        self.assertNotIn("allocate_new_money", source)
        self.assertNotIn("supabase", source.lower())
        self.assertNotIn("DATABASE_URL", source)
        self.assertNotIn("evaluate_official_fund_decision", TEFAS.read_text(encoding="utf-8"))
        self.assertNotIn("allocate_new_money", TEFAS.read_text(encoding="utf-8"))
        self.assertNotIn("AIS", NEW_MONEY.read_text(encoding="utf-8"))
        self.assertTrue(callable(allocate_new_money))

    def test_sp_funds_bist_us_isolation(self) -> None:
        self.assertEqual(evaluate_official_fund_intelligence("SPUS").score, 71.41)
        self.assertEqual(evaluate_official_fund_intelligence("SPSK").score, 65.87)
        self.assertEqual(evaluate_official_fund_intelligence("SPRE").score, 47.57)
        self.assertEqual(evaluate_official_fund_intelligence("SPWO").score, 52.79)
        sp_ctx = fund_intelligence_to_context(evaluate_official_fund_intelligence("SPUS"))
        self.assertEqual(sp_ctx.market, "US")
        self.assertEqual(sp_ctx.instrument_type, "ETF")
        provider = default_tefas_fund_provider()
        for symbol in PILOT_FUND_SYMBOLS:
            self.assertFalse(provider.supports(symbol))
        self.assertTrue(BIST.is_file())
        self.assertIn("ASELS", BIST.read_text(encoding="utf-8"))
        self.assertNotIn("AIS", US_SI.read_text(encoding="utf-8"))
        self.assertNotIn("evaluate_official_fund_intelligence", EIGHT_E.read_text(encoding="utf-8"))
        self.assertNotIn("evaluate_official_fund_decision", PARTICIPATION.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
