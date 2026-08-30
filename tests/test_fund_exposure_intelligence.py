from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path

from services.fund_decision_readiness import evaluate_official_fund_decision
from services.fund_intelligence_engine import evaluate_official_fund_intelligence
from services.fund_product_contract import (
    DIM_COUNTRY_CONCENTRATION,
    DIM_CURRENCY_DENOMINATION,
    DIM_CURRENCY_EXPOSURE,
    DIM_DEVELOPED_EMERGING,
    DIM_REAL_ESTATE_CONCENTRATION,
    DIM_RISK_EVAL,
    DIM_STATUS_MISSING,
    DIM_STATUS_NOT_APPLICABLE,
    DIM_STATUS_READY,
    EQUITY_ETF_WEIGHTS,
    MIN_READY_SCORED_DIMENSIONS,
    MIN_READY_WEIGHT_COVERAGE,
    REIT_ETF_WEIGHTS,
)
from services.official_fund_nport import parse_official_nport_exposure
from services.official_fund_nport_exposure_evidence import load_official_nport_exposure
from services.portfolio_security_decision_contract import PortfolioSecurityContext
from services.portfolio_security_decision_engine import evaluate_portfolio_security_decision
from services.security_intelligence_contract import STATE_WATCH
from services.wealth_new_money_allocation import allocate_new_money
from tests.test_fund_mandate_new_money import _ana_view
from tests.test_portfolio_security_decision import _healthy
from tests.test_wealth_new_money_allocation import _exposure_policy, _fx


ENGINE = Path("services/fund_intelligence_engine.py")
PARSER = Path("services/official_fund_nport.py")

SPRE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission>
  <genInfo>
    <seriesId>S000070461</seriesId>
    <classId>C000223966</classId>
    <repPdDate>2026-05-31</repPdDate>
  </genInfo>
  <invstOrSecs>
    <invstOrSec>
      <name>Welltower Inc</name>
      <pctVal>70</pctVal>
      <invCountry>US</invCountry>
      <curCd>USD</curCd>
      <assetCat>EC</assetCat>
    </invstOrSec>
    <invstOrSec>
      <name>Goodman Group</name>
      <pctVal>25</pctVal>
      <invCountry>AU</invCountry>
      <currencyConditional curCd="AUD"/>
      <assetCat>EC</assetCat>
    </invstOrSec>
  </invstOrSecs>
</edgarSubmission>
"""

SPWO_XML = """<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission>
  <genInfo>
    <seriesId>S000083496</seriesId>
    <classId>C000247153</classId>
    <repPdDate>2026-04-30</repPdDate>
  </genInfo>
  <invstOrSecs>
    <invstOrSec>
      <name>Taiwan Semiconductor</name>
      <title>TSM</title>
      <cusip>874039100</cusip>
      <identifiers><isin value="US8740391003"/></identifiers>
      <pctVal>20</pctVal>
      <invCountry>TW</invCountry>
      <curCd>USD</curCd>
      <assetCat>EC</assetCat>
    </invstOrSec>
    <invstOrSec>
      <name>Samsung Electronics</name>
      <title>005930 KS</title>
      <pctVal>10</pctVal>
      <invCountry>KR</invCountry>
      <currencyConditional curCd="KRW"/>
      <assetCat>EC</assetCat>
    </invstOrSec>
  </invstOrSecs>
</edgarSubmission>
"""

NO_COUNTRY_XML = """<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission>
  <genInfo>
    <seriesId>S000083496</seriesId>
    <classId>C000247153</classId>
    <repPdDate>2026-04-30</repPdDate>
  </genInfo>
  <invstOrSecs>
    <invstOrSec>
      <name>Mystery Co</name>
      <title>FOO LN</title>
      <cusip>123456789</cusip>
      <identifiers><isin value="GB00B1234567"/></identifiers>
      <pctVal>100</pctVal>
      <curCd>GBP</curCd>
    </invstOrSec>
  </invstOrSecs>
</edgarSubmission>
"""


class OfficialExposureParseTests(unittest.TestCase):
    def test_spre_uses_invcountry_not_property_type(self) -> None:
        evidence = parse_official_nport_exposure(SPRE_XML, symbol="SPRE")
        assert evidence is not None
        self.assertEqual(evidence.country_count, 2)
        self.assertEqual(evidence.largest_country, "US")
        self.assertEqual(evidence.largest_country_weight, 70.0)
        self.assertEqual(evidence.known_country_weight, 95.0)
        self.assertEqual(evidence.unknown_country_weight, 5.0)
        self.assertEqual(evidence.residual_weight, 5.0)
        self.assertEqual(evidence.property_type_weights, ())
        self.assertEqual(evidence.developed_emerging_weights, ())
        self.assertEqual(evidence.currency_semantics, "NPORT_DENOMINATION")

    def test_spwo_country_and_denomination(self) -> None:
        evidence = parse_official_nport_exposure(SPWO_XML, symbol="SPWO")
        assert evidence is not None
        self.assertEqual(evidence.largest_country, "TW")
        self.assertIn(("USD", 20.0), evidence.currency_weights)
        self.assertIn(("KRW", 10.0), evidence.currency_weights)
        self.assertEqual(evidence.currency_semantics, "NPORT_DENOMINATION")

    def test_no_country_from_ticker_cusip_isin(self) -> None:
        evidence = parse_official_nport_exposure(NO_COUNTRY_XML, symbol="SPWO")
        assert evidence is not None
        self.assertEqual(evidence.country_count, 0)
        self.assertFalse(evidence.country_reliable)
        self.assertEqual(evidence.unknown_country_weight, 100.0)
        self.assertTrue(evidence.denomination_present)

    def test_no_silent_renormalize(self) -> None:
        evidence = parse_official_nport_exposure(SPRE_XML, symbol="SPRE")
        assert evidence is not None
        self.assertEqual(evidence.raw_weight_sum, 95.0)
        self.assertNotEqual(evidence.known_country_weight, 100.0)


class CapturedOfficialExposureTests(unittest.TestCase):
    def test_spre_and_spwo_official_files(self) -> None:
        spre = load_official_nport_exposure("SPRE")
        spwo = load_official_nport_exposure("SPWO")
        assert spre is not None and spwo is not None
        self.assertGreaterEqual(spre.country_count, 2)
        self.assertTrue(spre.country_reliable)
        self.assertEqual(spre.property_type_weights, ())
        self.assertTrue(spwo.country_reliable)
        self.assertGreater(spwo.country_count, 5)
        self.assertEqual(spwo.developed_emerging_weights, ())
        self.assertLess(spre.unknown_country_weight, 10.0)
        self.assertLess(spwo.unknown_country_weight, 10.0)


class FundIntelligenceExposureTests(unittest.TestCase):
    def test_spre_spwo_dims_and_firewalls(self) -> None:
        spre = evaluate_official_fund_intelligence("SPRE")
        spwo = evaluate_official_fund_intelligence("SPWO")
        self.assertEqual(spre.evidence_map()[DIM_COUNTRY_CONCENTRATION], DIM_STATUS_READY)
        self.assertEqual(spre.evidence_map()[DIM_REAL_ESTATE_CONCENTRATION], DIM_STATUS_MISSING)
        self.assertEqual(spre.evidence_map()[DIM_CURRENCY_EXPOSURE], DIM_STATUS_NOT_APPLICABLE)
        self.assertEqual(spre.evidence_map()[DIM_CURRENCY_DENOMINATION], DIM_STATUS_READY)
        self.assertEqual(spre.evidence_map()[DIM_DEVELOPED_EMERGING], DIM_STATUS_MISSING)
        self.assertEqual(spre.evidence_map()[DIM_RISK_EVAL], DIM_STATUS_MISSING)
        self.assertEqual(spwo.evidence_map()[DIM_COUNTRY_CONCENTRATION], DIM_STATUS_READY)
        self.assertEqual(spwo.evidence_map()[DIM_CURRENCY_EXPOSURE], DIM_STATUS_MISSING)
        self.assertEqual(spwo.evidence_map()[DIM_CURRENCY_DENOMINATION], DIM_STATUS_READY)
        self.assertEqual(spwo.evidence_map()[DIM_DEVELOPED_EMERGING], DIM_STATUS_MISSING)
        self.assertEqual(spwo.evidence_map()[DIM_RISK_EVAL], DIM_STATUS_MISSING)
        self.assertIn("nport_invCountry", spre.dimension(DIM_COUNTRY_CONCENTRATION).facts_used)
        self.assertIn("not_fx_exposure", spwo.dimension(DIM_CURRENCY_DENOMINATION).facts_used)

    def test_spus_spsk_regression_and_thresholds(self) -> None:
        spus = evaluate_official_fund_intelligence("SPUS")
        spsk = evaluate_official_fund_intelligence("SPSK")
        self.assertEqual(spus.state, "WATCH")
        self.assertEqual(spus.score, 71.41)
        self.assertEqual(spus.confidence, 0.8636)
        self.assertEqual(spsk.state, "WATCH")
        self.assertEqual(spsk.score, 65.87)
        self.assertEqual(spsk.confidence, 0.6667)
        self.assertEqual(MIN_READY_SCORED_DIMENSIONS, 4)
        self.assertEqual(MIN_READY_WEIGHT_COVERAGE, 0.55)
        self.assertEqual(REIT_ETF_WEIGHTS[DIM_REAL_ESTATE_CONCENTRATION], 0.15)
        self.assertEqual(EQUITY_ETF_WEIGHTS[DIM_COUNTRY_CONCENTRATION], 0.10)
        self.assertNotIn(DIM_CURRENCY_DENOMINATION, EQUITY_ETF_WEIGHTS)

    def test_purification_and_no_guessing(self) -> None:
        first = evaluate_official_fund_intelligence("SPRE")
        second = evaluate_official_fund_intelligence("SPRE")
        self.assertEqual(first.score, second.score)
        for path in (ENGINE, PARSER):
            text = path.read_text(encoding="utf-8").lower()
            self.assertNotIn("country = ticker", text)
            self.assertNotIn("isin[:2]", text)
            self.assertNotIn("prologis", text)
            self.assertNotIn("welltower", text)
            self.assertNotIn("developed_markets =", text)
            self.assertNotIn(".insert(", text)


class EightENewMoneyIsolationTests(unittest.TestCase):
    def test_8e_new_money_and_isolation(self) -> None:
        for symbol in ("SPUS", "SPSK", "SPRE", "SPWO"):
            view = evaluate_official_fund_intelligence(symbol)
            decision = evaluate_official_fund_decision(
                symbol, is_holding=True, portfolio_weight=15.0, economic_exposure_available=True
            )
            if view.state != "ATTRACTIVE":
                self.assertFalse(decision.exposure_increase_allowed, symbol)
        decisions = tuple(
            evaluate_official_fund_decision(
                symbol, is_holding=True, portfolio_weight=15.0, economic_exposure_available=True
            )
            for symbol in ("SPUS", "SPSK", "SPRE", "SPWO")
        )
        plan = allocate_new_money(
            available_amount=Decimal("60000"),
            amount_currency="TRY",
            portfolio_view=_ana_view(),
            policy=_exposure_policy(equity=70, sukuk=15, real_estate=10, cash=5),
            conversion=_fx(),
            enable_hybrid_exposure_allocation=False,
            security_decisions=decisions,
        )
        self.assertFalse(plan.hybrid_allocation_active)
        self.assertNotIn("EXPOSURE_CLASSIFICATION_INCOMPLETE", plan.limitations)
        aapl = evaluate_portfolio_security_decision(_healthy(symbol="AAPL", instrument_type="EQUITY"))
        asels = evaluate_portfolio_security_decision(
            PortfolioSecurityContext(
                symbol="ASELS",
                participation_status="Uygun",
                research_allowed=True,
                si_state=STATE_WATCH,
                is_holding=True,
                instrument_type="EQUITY",
                market="BIST",
                economic_exposure_status="STRICT",
                portfolio_weight=5.0,
            )
        )
        self.assertEqual(aapl.security_intelligence_state, "ATTRACTIVE")
        self.assertEqual(asels.decision, "WATCH")
