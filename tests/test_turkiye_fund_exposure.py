from __future__ import annotations

import unittest
from pathlib import Path

from services.fund_decision_readiness import evaluate_official_fund_decision
from services.fund_intelligence_engine import evaluate_official_fund_intelligence
from services.fund_product_contract import (
    LAYER_CASH_LIKE,
    PILOT_FUND_SYMBOLS,
    PILOT_TEFAS_FUND_CODES,
    REGION_GLOBAL,
    REGION_INTERNATIONAL_EX_US,
    REGION_TR,
    REGION_US,
    OfficialFundMandate,
)
from services.hybrid_exposure_allocation_policy import HybridExposureAllocationPolicy
from services.official_kap_pdr import asset_group_weights, explicit_subgroup_weights
from services.official_sp_funds_product import default_official_sp_funds_provider
from services.official_tefas_product import default_tefas_fund_provider
from services.official_turkiye_fund_exposure import classify_official_turkiye_fund_exposure
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.portfolio_allocation_intelligence import ECONOMIC_EXPOSURE_KEYS
from services.portfolio_economic_exposure import classify_instrument_exposure
from services.portfolio_security_decision_contract import (
    DECISION_WATCH,
    REASON_ECONOMIC_EXPOSURE_UNAVAILABLE,
)
from services.wealth_asset_classification import CASH_SYMBOL
from services.wealth_contract import ASSET_CLASS_CASH, ASSET_CLASS_FUND
from services.wealth_new_money_allocation import allocate_new_money
from tests.test_portfolio_allocation_intelligence import _row

EXPOSURE = Path("services/official_turkiye_fund_exposure.py")
TEFAS = Path("services/official_tefas_product.py")
READINESS = Path("services/fund_decision_readiness.py")
NEW_MONEY = Path("services/wealth_new_money_allocation.py")
BIST = Path("services/bist_refresh_contract.py")
US_SI = Path("services/security_intelligence_engine.py")
HYBRID = Path("services/hybrid_exposure_allocation_policy.py")

FROZEN = {
    "AIS": (70.39, "WATCH"),
    "ZPE": (66.32, "WATCH"),
    "IAT": (60.49, "NEUTRAL"),
}


def _fund_row(symbol: str):
    return _row(
        symbol=symbol,
        price_available=True,
        market_value=100.0,
        currency="TRY",
        weight_pct=10.0,
        asset_class=ASSET_CLASS_FUND,
    )


class TurkiyeFundExposureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = default_tefas_fund_provider()

    def test_ais_official_cash_like_not_portfolio_cash(self) -> None:
        row = self.provider.economic_classification("AIS")
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row.instrument, "FUND")
        self.assertEqual(row.primary_exposure, LAYER_CASH_LIKE)
        self.assertNotEqual(row.primary_exposure, "cash")
        self.assertEqual(row.geography, REGION_TR)
        self.assertEqual(row.confidence, "MEDIUM")
        self.assertIn("official_kap_mandate", row.evidence_basis)
        self.assertIn("official_kap_pdr", row.evidence_basis)
        self.assertEqual(row.as_of, "2026-07")
        self.assertTrue(row.ready)
        self.assertIn("NOT_PORTFOLIO_CASH", row.limitations)
        lookthrough = dict(row.lookthrough_weights)
        self.assertAlmostEqual(lookthrough["REPO"], 59.19, places=2)
        self.assertAlmostEqual(lookthrough["PARTICIPATION_ACCOUNT"], 24.79, places=2)
        self.assertAlmostEqual(lookthrough["LEASE_CERTIFICATE"], 16.47, places=2)
        self.assertNotEqual(row.symbol, CASH_SYMBOL)
        self.assertNotEqual(row.instrument, ASSET_CLASS_CASH)
        self.assertNotIn(LAYER_CASH_LIKE, ECONOMIC_EXPOSURE_KEYS)
        mandate = self.provider.mandate("AIS")
        mapped = classify_instrument_exposure(_fund_row("AIS"), fund_mandates={"AIS": mandate})
        self.assertEqual(mapped.economic_exposures[0].exposure_bucket, LAYER_CASH_LIKE)
        self.assertNotEqual(mapped.economic_exposures[0].exposure_bucket, "cash")

    def test_zpe_primary_equity_preserves_lookthrough(self) -> None:
        row = self.provider.economic_classification("ZPE")
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row.primary_exposure, "equity")
        self.assertEqual(row.geography, REGION_TR)
        lookthrough = dict(row.lookthrough_weights)
        self.assertAlmostEqual(lookthrough["EQUITY"], 77.8599, places=4)
        self.assertAlmostEqual(lookthrough["FUND"], 14.4118, places=4)
        self.assertAlmostEqual(lookthrough["PARTICIPATION_ACCOUNT"], 3.5529, places=4)
        self.assertAlmostEqual(lookthrough["REPO"], 4.1754, places=4)
        self.assertLess(lookthrough["EQUITY"], 100.0)
        self.assertIn("PRIMARY_DISTINCT_FROM_LOOKTHROUGH", row.limitations)

    def test_iat_primary_sukuk_preserves_public_private(self) -> None:
        row = self.provider.economic_classification("IAT")
        pdr = self.provider.pdr_holdings("IAT")
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row.primary_exposure, "sukuk")
        self.assertEqual(row.geography, REGION_TR)
        lookthrough = dict(row.lookthrough_weights)
        self.assertAlmostEqual(lookthrough["LEASE_CERTIFICATE"], 98.96, places=2)
        subgroups = dict(row.subgroup_weights)
        self.assertAlmostEqual(subgroups["Kamu Kesimi"], explicit_subgroup_weights(pdr, "Kamu Kesimi"))
        self.assertAlmostEqual(subgroups["Özel Sektör"], explicit_subgroup_weights(pdr, "Özel Sektör"))
        self.assertAlmostEqual(subgroups["Kamu Kesimi"], 36.83, places=2)
        self.assertAlmostEqual(subgroups["Özel Sektör"], 62.13, places=2)

    def test_primary_vs_lookthrough_and_no_name_inference(self) -> None:
        source = EXPOSURE.read_text(encoding="utf-8")
        self.assertNotIn("katılım", source.lower())
        self.assertNotIn('if mandate.symbol == "AIS"', source)
        self.assertNotIn('if mandate.symbol == "ZPE"', source)
        self.assertNotIn('if mandate.symbol == "IAT"', source)
        for code in PILOT_TEFAS_FUND_CODES:
            row = self.provider.economic_classification(code)
            pdr = self.provider.pdr_holdings(code)
            self.assertEqual(dict(row.lookthrough_weights), asset_group_weights(pdr))
            self.assertNotEqual(dict(row.lookthrough_weights), {row.primary_exposure: 100.0})

    def test_missing_mandate_or_pdr_fails_closed(self) -> None:
        mandate = self.provider.mandate("AIS")
        self.assertIsNone(classify_official_turkiye_fund_exposure(None, self.provider.pdr_holdings("AIS")))
        self.assertIsNone(classify_official_turkiye_fund_exposure(mandate, None))
        broken = OfficialFundMandate(
            symbol="AIS",
            primary_layer="not_a_layer",
            region=REGION_TR,
            vehicle=mandate.vehicle,
            confidence="LOW",
            source=mandate.source,
            source_url=mandate.source_url,
            evidence_excerpt="x",
        )
        self.assertIsNone(classify_official_turkiye_fund_exposure(broken, self.provider.pdr_holdings("AIS")))

    def test_default_eight_e_uses_official_exposure(self) -> None:
        for code, (score, state) in FROZEN.items():
            decision = evaluate_official_fund_decision(code)
            self.assertEqual(decision.decision, DECISION_WATCH)
            self.assertFalse(decision.exposure_increase_allowed)
            self.assertNotIn(REASON_ECONOMIC_EXPOSURE_UNAVAILABLE, decision.blocking_reasons)
            self.assertEqual(decision.participation_status, PARTICIPATION_STATUS_UYGUN)
            self.assertTrue(decision.research_allowed)
            self.assertEqual(decision.security_intelligence_state, state)
            self.assertEqual(decision.security_intelligence_score, score)

    def test_fi_and_participation_freeze(self) -> None:
        for code, (score, state) in FROZEN.items():
            view = evaluate_official_fund_intelligence(code)
            self.assertEqual(view.score, score)
            self.assertEqual(view.state, state)
            self.assertTrue(view.participation.eligible)
            self.assertEqual(self.provider.sharia_evidence(code).participation_status, PARTICIPATION_STATUS_UYGUN)

    def test_sp_funds_exposure_regression(self) -> None:
        sp = default_official_sp_funds_provider()
        self.assertEqual(sp.mandate("SPUS").primary_layer, "equity")
        self.assertEqual(sp.mandate("SPUS").region, REGION_US)
        self.assertEqual(sp.mandate("SPSK").primary_layer, "sukuk")
        self.assertEqual(sp.mandate("SPSK").region, REGION_GLOBAL)
        self.assertEqual(sp.mandate("SPRE").primary_layer, "real_estate")
        self.assertEqual(sp.mandate("SPRE").region, REGION_GLOBAL)
        self.assertEqual(sp.mandate("SPWO").primary_layer, "equity")
        self.assertEqual(sp.mandate("SPWO").region, REGION_INTERNATIONAL_EX_US)
        self.assertEqual(evaluate_official_fund_intelligence("SPUS").score, 71.41)
        self.assertEqual(evaluate_official_fund_intelligence("SPSK").score, 65.87)
        self.assertEqual(evaluate_official_fund_intelligence("SPRE").score, 47.57)
        self.assertEqual(evaluate_official_fund_intelligence("SPWO").score, 52.79)
        self.assertFalse(hasattr(sp, "economic_classification") and sp.supports("AIS"))

    def test_isolation_and_hybrid_off(self) -> None:
        self.assertFalse(HybridExposureAllocationPolicy().enabled)
        self.assertIn("enable_hybrid_exposure_allocation: bool = False", HYBRID.read_text(encoding="utf-8"))
        self.assertNotIn("allocate_new_money", EXPOSURE.read_text(encoding="utf-8"))
        self.assertNotIn("allocate_new_money", TEFAS.read_text(encoding="utf-8"))
        self.assertNotIn("AIS", NEW_MONEY.read_text(encoding="utf-8"))
        self.assertTrue(callable(allocate_new_money))
        self.assertTrue(BIST.is_file())
        self.assertIn("ASELS", BIST.read_text(encoding="utf-8"))
        self.assertNotIn("AIS", US_SI.read_text(encoding="utf-8"))
        for symbol in PILOT_FUND_SYMBOLS:
            self.assertFalse(self.provider.supports(symbol))
        self.assertNotIn("FMPClient", EXPOSURE.read_text(encoding="utf-8"))
        self.assertIn("8E consumes provider classification", READINESS.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
