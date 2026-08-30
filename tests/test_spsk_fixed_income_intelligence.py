from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path

from services.fund_decision_readiness import evaluate_official_fund_decision
from services.fund_intelligence_engine import evaluate_official_fund_intelligence
from services.fund_product_contract import (
    DIM_CREDIT_QUALITY,
    DIM_CREDIT_RISK,
    DIM_DURATION,
    DIM_ISSUER_CONCENTRATION,
    DIM_RATE_RISK,
    DIM_RISK_EVAL,
    DIM_STATUS_MISSING,
    DIM_STATUS_READY,
    MIN_READY_SCORED_DIMENSIONS,
    MIN_READY_WEIGHT_COVERAGE,
    SUKUK_ETF_WEIGHTS,
)
from services.official_fund_nport import parse_official_nport_fixed_income
from services.official_fund_nport_fixed_income_evidence import (
    SPSK_ACCESSION,
    load_spsk_nport_fixed_income,
)
from services.portfolio_security_decision_engine import evaluate_portfolio_security_decision
from services.portfolio_security_decision_contract import PortfolioSecurityContext
from services.security_intelligence_contract import STATE_WATCH
from services.wealth_new_money_allocation import allocate_new_money
from tests.test_fund_mandate_new_money import _ana_view
from tests.test_portfolio_security_decision import _healthy
from tests.test_wealth_new_money_allocation import _exposure_policy, _fx


ENGINE = Path("services/fund_intelligence_engine.py")
PARSER = Path("services/official_fund_nport.py")
CONTRACT = Path("services/fund_product_contract.py")

MINIMAL_NPORT = """<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission>
  <headerData><accessionNumber>0002000324-26-003239</accessionNumber></headerData>
  <genInfo>
    <seriesId>S000067282</seriesId>
    <classId>C000216394</classId>
    <repPdDate>2026-05-31</repPdDate>
    <repPdEnd>2026-11-30</repPdEnd>
  </genInfo>
  <fundInfo>
    <netAssets>1000000</netAssets>
    <intrstRtRiskdv01 period3Mon="1" period1Yr="-2" period5Yr="-3" period10Yr="-4" period30Yr="-5"/>
    <intrstRtRiskdv100 period3Mon="10" period1Yr="-20" period5Yr="-30" period10Yr="-40" period30Yr="-50"/>
    <creditSprdRiskInvstGrade period3Mon="0" period1Yr="-1" period5Yr="-2" period10Yr="-3" period30Yr="-4"/>
    <creditSprdRiskNonInvstGrade period3Mon="0" period1Yr="0" period5Yr="-1" period10Yr="-1" period30Yr="0"/>
  </fundInfo>
  <invstOrSecs>
    <invstOrSec>
      <name>KSA Sukuk Ltd</name>
      <title>KSA Sukuk Ltd 4.274%</title>
      <pctVal>40</pctVal>
      <curCd>USD</curCd>
      <debtSec><maturityDt>2029-01-19</maturityDt></debtSec>
    </invstOrSec>
    <invstOrSec>
      <name>KSA Ijarah Sukuk Ltd</name>
      <title>KSA Ijarah Sukuk Ltd 4.875%</title>
      <pctVal>35</pctVal>
      <curCd>USD</curCd>
      <debtSec><maturityDt>2035-09-09</maturityDt></debtSec>
    </invstOrSec>
    <invstOrSec>
      <name>KSA Sukuk Ltd</name>
      <title>KSA Sukuk Ltd 4.511%</title>
      <pctVal>25</pctVal>
      <curCd>USD</curCd>
      <debtSec><maturityDt>2028-10-25</maturityDt></debtSec>
    </invstOrSec>
  </invstOrSecs>
</edgarSubmission>
"""

MISSING_FIELDS_NPORT = """<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission>
  <genInfo>
    <seriesId>S000067282</seriesId>
    <classId>C000216394</classId>
    <repPdDate>2026-05-31</repPdDate>
  </genInfo>
  <fundInfo><netAssets>1000000</netAssets></fundInfo>
  <invstOrSecs>
    <invstOrSec>
      <name>N/A</name>
      <title>Unknown Sukuk</title>
      <pctVal>100</pctVal>
    </invstOrSec>
  </invstOrSecs>
</edgarSubmission>
"""


class OfficialNportFixedIncomeParseTests(unittest.TestCase):
    def test_dv01_dv100_and_spread_are_not_duration_or_rating(self) -> None:
        evidence = parse_official_nport_fixed_income(MINIMAL_NPORT, symbol="SPSK")
        assert evidence is not None
        self.assertTrue(evidence.rate_risk_present)
        self.assertTrue(evidence.credit_spread_present)
        self.assertIsNone(evidence.duration)
        self.assertIsNone(evidence.credit_quality)
        self.assertIn("DV01_IS_NOT_DURATION", evidence.limitations)
        self.assertIn("CREDIT_SPREAD_IS_NOT_RATING", evidence.limitations)
        self.assertEqual(len(evidence.interest_rate_risk_dv01), 5)
        self.assertEqual(len(evidence.interest_rate_risk_dv100), 5)

    def test_maturity_weighting_excludes_residual(self) -> None:
        evidence = parse_official_nport_fixed_income(MINIMAL_NPORT, symbol="SPSK")
        assert evidence is not None
        self.assertEqual(evidence.dated_weight_pct, 100.0)
        self.assertEqual(evidence.residual_weight_pct, 0.0)
        self.assertIsNotNone(evidence.weighted_average_maturity_years)
        self.assertGreater(evidence.weighted_average_maturity_years or 0.0, 2.0)
        self.assertIn("WAM_EXCLUDES_RESIDUAL_AND_UNDATED", evidence.limitations)

    def test_issuer_grouping_uses_official_name_not_title(self) -> None:
        evidence = parse_official_nport_fixed_income(MINIMAL_NPORT, symbol="SPSK")
        assert evidence is not None
        self.assertEqual(evidence.official_issuer_field, "nport_name")
        self.assertEqual(evidence.issuer_count, 2)
        self.assertEqual(evidence.largest_issuer_weight, 65.0)
        self.assertEqual(evidence.top10_issuer_weight, 100.0)
        names = {row.issuer_name for row in evidence.holdings}
        self.assertIn("KSA Sukuk Ltd", names)
        self.assertIn("KSA Ijarah Sukuk Ltd", names)

    def test_missing_fields_fail_closed(self) -> None:
        evidence = parse_official_nport_fixed_income(MISSING_FIELDS_NPORT, symbol="SPSK")
        assert evidence is not None
        self.assertFalse(evidence.rate_risk_present)
        self.assertFalse(evidence.issuer_reliable)
        self.assertIsNone(evidence.duration)
        self.assertIsNone(evidence.weighted_average_maturity_years)
        self.assertEqual(evidence.unknown_issuer_weight_pct, 100.0)

    def test_wrong_series_rejected(self) -> None:
        self.assertIsNone(parse_official_nport_fixed_income(MINIMAL_NPORT, symbol="SPUS"))


class OfficialSpskEvidenceTests(unittest.TestCase):
    def test_captured_official_spsk_nport(self) -> None:
        evidence = load_spsk_nport_fixed_income()
        assert evidence is not None
        self.assertEqual(evidence.fund_symbol, "SPSK")
        self.assertEqual(evidence.as_of, "2026-05-31")
        self.assertEqual(evidence.source_url.endswith(f"{SPSK_ACCESSION.replace('-', '')}/primary_doc.xml"), True)
        self.assertEqual(evidence.holding_count, 170)
        self.assertTrue(evidence.rate_risk_present)
        self.assertTrue(evidence.credit_spread_present)
        self.assertIsNone(evidence.duration)
        self.assertIsNone(evidence.credit_quality)
        self.assertTrue(evidence.issuer_reliable)
        self.assertGreater(evidence.largest_issuer_weight or 0.0, 10.0)
        self.assertGreater(evidence.top10_issuer_weight or 0.0, evidence.largest_issuer_weight or 0.0)
        ksa = sum(row.weight_pct for row in evidence.holdings if row.issuer_name == "KSA Sukuk Ltd")
        ijarah = sum(row.weight_pct for row in evidence.holdings if row.issuer_name == "KSA Ijarah Sukuk Ltd")
        self.assertGreater(ksa, 0)
        self.assertGreater(ijarah, 0)
        self.assertNotEqual(round(ksa, 4), round(ijarah, 4))
        self.assertTrue(all(cur == "USD" for cur, _weight in evidence.currency_weights))


class FundIntelligenceWiringTests(unittest.TestCase):
    def test_spsk_supported_dims_and_firewalls(self) -> None:
        view = evaluate_official_fund_intelligence("SPSK")
        evidence = view.evidence_map()
        self.assertEqual(evidence[DIM_RATE_RISK], DIM_STATUS_READY)
        self.assertEqual(evidence[DIM_CREDIT_RISK], DIM_STATUS_READY)
        self.assertEqual(evidence[DIM_ISSUER_CONCENTRATION], DIM_STATUS_READY)
        self.assertEqual(evidence[DIM_DURATION], DIM_STATUS_MISSING)
        self.assertEqual(evidence[DIM_CREDIT_QUALITY], DIM_STATUS_MISSING)
        self.assertEqual(evidence[DIM_RISK_EVAL], DIM_STATUS_MISSING)
        self.assertIsNone(view.dimension(DIM_RATE_RISK).score)
        self.assertIsNone(view.dimension(DIM_DURATION).score)
        self.assertIn("nport_issuer_name", view.dimension(DIM_ISSUER_CONCENTRATION).facts_used)
        self.assertNotIn("drawdown", " ".join(view.provenance))

    def test_thresholds_and_weights_unchanged(self) -> None:
        self.assertEqual(MIN_READY_SCORED_DIMENSIONS, 4)
        self.assertEqual(MIN_READY_WEIGHT_COVERAGE, 0.55)
        self.assertEqual(SUKUK_ETF_WEIGHTS[DIM_DURATION], 0.15)
        self.assertEqual(SUKUK_ETF_WEIGHTS[DIM_CREDIT_QUALITY], 0.15)
        self.assertEqual(SUKUK_ETF_WEIGHTS[DIM_ISSUER_CONCENTRATION], 0.15)
        self.assertNotIn(DIM_RATE_RISK, SUKUK_ETF_WEIGHTS)
        self.assertNotIn(DIM_CREDIT_RISK, SUKUK_ETF_WEIGHTS)

    def test_no_guessing_tokens(self) -> None:
        for path in (ENGINE, PARSER, CONTRACT):
            text = path.read_text(encoding="utf-8").lower()
            self.assertNotIn("split(security_name", text)
            self.assertNotIn("issuer = name.split", text)
            self.assertNotIn(".insert(", text)
            self.assertNotIn("post_transaction", text)


class EightEAndIsolationTests(unittest.TestCase):
    def test_8e_and_new_money(self) -> None:
        view = evaluate_official_fund_intelligence("SPSK")
        decision = evaluate_official_fund_decision(
            "SPSK",
            is_holding=True,
            portfolio_weight=15.0,
            economic_exposure_available=True,
        )
        if view.state == "INSUFFICIENT_DATA":
            self.assertEqual(decision.decision, "INSUFFICIENT_DATA")
            self.assertFalse(decision.exposure_increase_allowed)
        elif view.state != "ATTRACTIVE":
            self.assertFalse(decision.exposure_increase_allowed)
        plan = allocate_new_money(
            available_amount=Decimal("60000"),
            amount_currency="TRY",
            portfolio_view=_ana_view(),
            policy=_exposure_policy(equity=70, sukuk=15, real_estate=10, cash=5),
            conversion=_fx(),
            enable_hybrid_exposure_allocation=False,
            security_decisions=(decision,),
        )
        self.assertFalse(plan.hybrid_allocation_active)
        self.assertNotIn("EXPOSURE_CLASSIFICATION_INCOMPLETE", plan.limitations)

    def test_equity_bist_isolation(self) -> None:
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
        self.assertEqual(evaluate_official_fund_intelligence("SPUS").fund_type_profile, "EQUITY_ETF")
