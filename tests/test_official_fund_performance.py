from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path

from services.fund_decision_readiness import evaluate_official_fund_decision
from services.fund_intelligence_engine import evaluate_official_fund_intelligence
from services.fund_product_contract import (
    DIM_MOMENTUM_EVAL,
    DIM_PERFORMANCE_EVAL,
    DIM_RISK_EVAL,
    DIM_STATUS_MISSING,
    DIM_STATUS_READY,
    DIM_TRACKING_EVAL,
    DIM_YIELD,
    PERFORMANCE_BASIS_MARKET_PRICE,
    PERFORMANCE_BASIS_NAV,
    TRACKING_CONCEPT_DIFFERENCE,
    OfficialFundPerformance,
)
from services.official_fund_nport import parse_official_nport_xml, nport_identity
from services.official_fund_nport_evidence import NPORT_XML
from services.official_fund_performance import (
    parse_official_performance_html,
    parse_official_sec_yield_html,
)
from services.official_sp_funds_product import default_official_sp_funds_provider
from services.portfolio_security_decision_contract import (
    DECISION_INSUFFICIENT_DATA,
    REASON_FUND_INTELLIGENCE_MISSING,
)
from services.portfolio_security_decision_engine import evaluate_portfolio_security_decision
from services.security_intelligence_contract import STATE_INSUFFICIENT_DATA, STATE_WATCH
from services.wealth_new_money_allocation import allocate_new_money
from tests.test_fund_mandate_new_money import _ana_view
from tests.test_portfolio_security_decision import _healthy
from tests.test_wealth_new_money_allocation import _exposure_policy, _fx
from services.portfolio_security_decision_contract import PortfolioSecurityContext


ENGINE = Path("services/fund_intelligence_engine.py")
PARSER = Path("services/official_fund_performance.py")
NPORT = Path("services/official_fund_nport.py")
WRITE_TOKENS = (".insert(", ".upsert(", ".delete(", "post_transaction")
THIRD_PARTY = ("yahoo", "fmp", "alphavantage", "yfinance")


PREMIUM_ONLY = """
| Ticker | SPUS |
| Premium/Discount Percentage | 12.50% |
| NAV | $50.00 |
"""


class OfficialPerformanceParseTests(unittest.TestCase):
    def test_nav_vs_market_and_latest_date(self) -> None:
        provider = default_official_sp_funds_provider()
        nav = provider.performance("SPUS")
        mkt = provider.market_performance("SPUS")
        self.assertIsNotNone(nav)
        self.assertIsNotNone(mkt)
        assert nav is not None and mkt is not None
        self.assertEqual(nav.basis, PERFORMANCE_BASIS_NAV)
        self.assertEqual(mkt.basis, PERFORMANCE_BASIS_MARKET_PRICE)
        self.assertEqual(nav.as_of, "2026-07-31")
        self.assertEqual(nav.return_1m, -2.02)
        self.assertEqual(nav.return_3m, 4.94)
        self.assertEqual(nav.return_6m, 9.81)
        self.assertEqual(nav.return_ytd, 10.73)
        self.assertEqual(nav.return_1y, 23.42)
        self.assertEqual(nav.return_3y, 20.20)
        self.assertEqual(nav.return_5y, 14.55)
        self.assertEqual(nav.since_inception_cumulative, 200.50)
        self.assertEqual(nav.since_inception_annualized, 18.08)
        self.assertIsNone(nav.drawdown)
        self.assertNotEqual(nav.return_1m, mkt.return_1m)
        self.assertEqual(nav.performance_lead(), (23.42, "return_1y"))
        self.assertEqual(nav.momentum_lead(), (4.94, "return_3m"))

    def test_does_not_convert_annualized_to_cumulative(self) -> None:
        nav = default_official_sp_funds_provider().performance("SPUS")
        assert nav is not None
        self.assertNotEqual(nav.since_inception_annualized, nav.since_inception_cumulative)
        self.assertEqual(nav.performance_lead()[1], "return_1y")

    def test_benchmark_match_and_tracking_difference(self) -> None:
        nav = default_official_sp_funds_provider().performance("SPUS")
        assert nav is not None
        self.assertIn("Shariah Industry Exclusions", nav.benchmark_name or "")
        self.assertEqual(nav.benchmark_ticker, "SPSIEUT")
        self.assertEqual(nav.benchmark_return_1y, 23.16)
        self.assertEqual(nav.tracking_concept, TRACKING_CONCEPT_DIFFERENCE)
        self.assertEqual(nav.tracking_horizon, "1Y")
        self.assertEqual(nav.tracking_difference, 0.26)
        self.assertNotIn("tracking_error", (nav.tracking_concept or "").lower())
        self.assertNotEqual(nav.benchmark_ticker, "SPTR2")

    def test_spsk_does_not_use_bloomberg_secondary(self) -> None:
        nav = default_official_sp_funds_provider().performance("SPSK")
        assert nav is not None
        self.assertEqual(nav.as_of, "2026-05-31")
        self.assertIn("Dow Jones Sukuk", nav.benchmark_name or "")
        self.assertNotIn("Bloomberg", nav.benchmark_name or "")
        self.assertEqual(nav.tracking_difference, round(4.28 - 5.07, 4))

    def test_ticker_row_identity(self) -> None:
        html = default_official_sp_funds_provider()._product_html["SPUS"]
        rows = parse_official_performance_html(html, symbol="SPSK")
        self.assertEqual(rows, {})

    def test_premium_discount_is_not_nav_history_or_drawdown(self) -> None:
        rows = parse_official_performance_html(PREMIUM_ONLY, symbol="SPUS")
        self.assertEqual(rows, {})
        view = evaluate_official_fund_intelligence("SPUS")
        self.assertEqual(view.evidence_map()[DIM_RISK_EVAL], DIM_STATUS_MISSING)
        self.assertIsNone(view.dimension(DIM_RISK_EVAL).score if view.dimension(DIM_RISK_EVAL) else None)


class OfficialYieldTests(unittest.TestCase):
    def test_spsk_sec_yield_is_not_return(self) -> None:
        provider = default_official_sp_funds_provider()
        yld = provider.sec_yield("SPSK")
        nav = provider.performance("SPSK")
        assert yld is not None and nav is not None
        self.assertEqual(yld.sec_yield_30d, 4.41)
        self.assertEqual(yld.as_of, "2026-03-31")
        self.assertEqual(yld.basis, "SEC_30_DAY_YIELD")
        self.assertNotEqual(yld.sec_yield_30d, nav.return_1y)
        view = evaluate_official_fund_intelligence("SPSK")
        self.assertEqual(view.evidence_map()[DIM_YIELD], DIM_STATUS_READY)
        self.assertNotEqual(view.dimension(DIM_YIELD).score, nav.return_1y)


class NportTests(unittest.TestCase):
    def test_pilot_identities(self) -> None:
        self.assertEqual(nport_identity("SPUS").series_id, "S000067283")
        self.assertEqual(nport_identity("SPSK").class_id, "C000216394")
        self.assertEqual(nport_identity("SPRE").cik, "0001742912")
        self.assertEqual(nport_identity("SPWO").cik, "0001989916")
        self.assertIsNone(nport_identity("HLAL"))

    def test_period_and_identity_match(self) -> None:
        spus = parse_official_nport_xml(NPORT_XML["SPUS"], symbol="SPUS", accession="0002000324-26-003242")
        assert spus is not None
        self.assertEqual(spus.period_of_report, "2026-05-31")
        self.assertEqual(spus.net_assets, 2723971002.59)
        self.assertIsNone(spus.nav_per_share)
        self.assertIn("NPORT_NOT_DAILY_NAV_SERIES", spus.limitations)
        self.assertIn("NPORT_NAV_NOT_DIRECTLY_REPORTED", spus.limitations)
        mismatch = parse_official_nport_xml(NPORT_XML["SPUS"], symbol="SPSK")
        self.assertIsNone(mismatch)

    def test_derived_nav_only_when_units_official(self) -> None:
        xml = NPORT_XML["SPUS"].replace(
            "<netAssets>2723971002.59</netAssets>",
            "<netAssets>2723971002.59</netAssets><unitsOutstanding>51950000</unitsOutstanding>",
        )
        snapshot = parse_official_nport_xml(xml, symbol="SPUS")
        assert snapshot is not None
        self.assertEqual(snapshot.nav_method, "NET_ASSETS_DIV_UNITS_OUTSTANDING")
        self.assertAlmostEqual(snapshot.nav_per_share or 0.0, 2723971002.59 / 51950000, places=3)


class FundIntelligenceTransitionTests(unittest.TestCase):
    def test_performance_momentum_tracking_ready_risk_missing(self) -> None:
        for symbol in ("SPUS", "SPSK", "SPRE", "SPWO"):
            view = evaluate_official_fund_intelligence(symbol)
            evidence = view.evidence_map()
            self.assertEqual(evidence[DIM_PERFORMANCE_EVAL], DIM_STATUS_READY, symbol)
            self.assertEqual(evidence[DIM_RISK_EVAL], DIM_STATUS_MISSING, symbol)
            if symbol != "SPSK":
                self.assertEqual(evidence[DIM_MOMENTUM_EVAL], DIM_STATUS_READY, symbol)
            if symbol == "SPSK":
                self.assertEqual(evidence[DIM_YIELD], DIM_STATUS_READY)
            if symbol in {"SPUS", "SPWO"}:
                self.assertEqual(evidence[DIM_TRACKING_EVAL], DIM_STATUS_READY)
            self.assertFalse(any("drawdown" in (row.facts_used or ()) for row in view.dimensions if row.name == DIM_RISK_EVAL))

    def test_no_fake_tracking_error_or_third_party(self) -> None:
        for path in (ENGINE, PARSER, NPORT):
            text = path.read_text(encoding="utf-8").lower()
            self.assertNotIn("tracking_error", text.replace("official_tracking_error", ""))
            for token in THIRD_PARTY:
                self.assertNotIn(token, text)
            for token in WRITE_TOKENS:
                self.assertNotIn(token, text)


class EightEAndNewMoneyTests(unittest.TestCase):
    def test_insufficient_still_fail_closed(self) -> None:
        blocked = evaluate_portfolio_security_decision(
            PortfolioSecurityContext(
                symbol="SPUS",
                instrument_type="ETF",
                market="US",
                is_holding=True,
                portfolio_weight=10.0,
                economic_exposure_status="STRICT",
            )
        )
        self.assertEqual(blocked.decision, DECISION_INSUFFICIENT_DATA)
        self.assertFalse(blocked.exposure_increase_allowed)
        self.assertIn(REASON_FUND_INTELLIGENCE_MISSING, blocked.blocking_reasons)

    def test_official_8e_does_not_increase_without_actionable_state(self) -> None:
        for symbol in ("SPUS", "SPSK", "SPRE", "SPWO"):
            view = evaluate_official_fund_intelligence(symbol)
            decision = evaluate_official_fund_decision(
                symbol,
                is_holding=True,
                portfolio_weight=10.0,
                economic_exposure_available=True,
            )
            if view.state == STATE_INSUFFICIENT_DATA:
                self.assertFalse(decision.exposure_increase_allowed, symbol)

    def test_mandate_only_new_money_still_zero_without_increase(self) -> None:
        plan = allocate_new_money(
            available_amount=Decimal("60000"),
            amount_currency="TRY",
            portfolio_view=_ana_view(),
            policy=_exposure_policy(equity=70, sukuk=15, real_estate=10, cash=5),
            conversion=_fx(),
            enable_hybrid_exposure_allocation=False,
        )
        self.assertFalse(plan.hybrid_allocation_active)
        self.assertFalse(any(row.symbol in {"SPUS", "SPSK", "SPRE", "SPWO"} for row in plan.recommendations))

    def test_us_and_bist_isolation(self) -> None:
        aapl = evaluate_portfolio_security_decision(_healthy(symbol="AAPL", instrument_type="EQUITY"))
        asels = evaluate_portfolio_security_decision(
            PortfolioSecurityContext(
                symbol="ASELS",
                participation_status="Uygun",
                research_allowed=True,
                si_state=STATE_WATCH,
                si_score=53.3,
                is_holding=True,
                instrument_type="EQUITY",
                market="BIST",
                economic_exposure_status="STRICT",
                portfolio_weight=8.0,
            )
        )
        self.assertNotEqual(aapl.decision, DECISION_INSUFFICIENT_DATA)
        self.assertEqual(asels.decision, "WATCH")


class EmptyPerformanceContractTests(unittest.TestCase):
    def test_blank_performance_has_no_history(self) -> None:
        blank = OfficialFundPerformance(symbol="SPUS")
        self.assertFalse(blank.has_return_history())
        self.assertFalse(blank.has_risk_history())
        self.assertIsNone(blank.performance_lead()[0])
