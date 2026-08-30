from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path

from services.fund_decision_readiness import evaluate_official_fund_decision
from services.fund_intelligence_engine import evaluate_official_fund_intelligence
from services.fund_lookthrough_summary import (
    UNKNOWN_WEIGHT_MISSING_PCT,
    build_fund_lookthrough_summary,
    build_holdings_intelligence_evidence,
    official_issuer_field_present,
    official_issuer_value,
)
from services.fund_portfolio_overlap import build_fund_portfolio_overlap
from services.fund_product_contract import (
    DIM_CONCENTRATION_EVAL,
    DIM_COUNTRY_CONCENTRATION,
    DIM_CURRENCY_EXPOSURE,
    DIM_DIVERSIFICATION_EVAL,
    DIM_ISSUER_CONCENTRATION,
    DIM_REAL_ESTATE_CONCENTRATION,
    DIM_RISK_EVAL,
    DIM_STATUS_MISSING,
    DIM_STATUS_READY,
)
from services.official_fund_holdings_client import parse_official_holdings_csv
from services.official_fund_holdings_evidence import (
    default_official_holdings_files,
    load_official_holdings_file,
)
from services.official_sp_funds_product import default_official_sp_funds_provider
from services.portfolio_security_decision_contract import (
    DECISION_INSUFFICIENT_DATA,
    PortfolioSecurityContext,
)
from services.portfolio_security_decision_engine import evaluate_portfolio_security_decision
from services.security_intelligence_contract import STATE_WATCH
from services.wealth_new_money_allocation import allocate_new_money
from tests.test_fund_mandate_new_money import _ana_view
from tests.test_official_fund_holdings import _csv, _row
from tests.test_portfolio_security_decision import _healthy
from tests.test_wealth_new_money_allocation import _exposure_policy, _fx


SUMMARY = Path("services/fund_lookthrough_summary.py")
ENGINE = Path("services/fund_intelligence_engine.py")
WRITE_TOKENS = (".insert(", ".upsert(", ".delete(", "post_transaction")
GUESS_TOKENS = (
    "split(security_name",
    "issuer = name",
    "country = ticker",
    "currency = cusip",
)


class HoldingsEvidenceTests(unittest.TestCase):
    def test_official_counts_weights_and_top_metrics(self) -> None:
        files = default_official_holdings_files()
        expected = {
            "SPUS": (220, 100.03),
            "SPSK": (171, 100.07),
            "SPRE": (30, 99.98),
            "SPWO": (383, 99.93),
        }
        for symbol, (count, weight_sum) in expected.items():
            evidence = build_holdings_intelligence_evidence(files[symbol])
            self.assertEqual(evidence.holding_count, count)
            self.assertEqual(evidence.raw_weight_sum, weight_sum)
            self.assertTrue(evidence.weight_reconciled)
            self.assertEqual(evidence.unknown_weight, 0.0)
            self.assertGreater(evidence.largest_holding_weight or 0.0, 0)
            self.assertGreater(evidence.top_5_weight, 0)
            self.assertGreater(evidence.top_10_weight, evidence.top_5_weight)
            self.assertIsNotNone(evidence.hhi)
            self.assertIsNotNone(evidence.effective_number_of_holdings)
            self.assertLess(evidence.effective_number_of_holdings or 0.0, float(count))

    def test_unknown_weight_marks_dimensions_missing(self) -> None:
        from services.fund_product_contract import FundLookthroughSummary, LookthroughHolding

        summary = FundLookthroughSummary(
            fund_symbol="SPUS",
            as_of="2026-08-28",
            holdings_count=2,
            top_holding=LookthroughHolding("AAPL", "Apple", 60.0, True, False),
            top_holding_weight_pct=60.0,
            top10_weight_pct=100.0,
            single_name_concentration_pct=60.0,
            cash_other_weight_pct=0.0,
            unknown_weight_pct=40.0,
            sector_allocation=(),
            country_allocation=(),
            known_nabi_overlap=("AAPL",),
            limitation="SECTOR_UNKNOWN",
        )
        self.assertGreater(summary.unknown_weight_pct, UNKNOWN_WEIGHT_MISSING_PCT)
        view = evaluate_official_fund_intelligence("SPUS", lookthrough=summary)
        self.assertEqual(view.evidence_map()[DIM_DIVERSIFICATION_EVAL], DIM_STATUS_MISSING)
        self.assertEqual(view.evidence_map()[DIM_CONCENTRATION_EVAL], DIM_STATUS_MISSING)

    def test_diversification_uses_effective_holdings_not_name(self) -> None:
        concentrated = parse_official_holdings_csv(
            _csv(
                "SPUS",
                [_row("SPUS", f"T{i}", f"Name {i}", "0.10%" if i else "80.00%") for i in range(200)],
            ),
            fund_symbol="SPUS",
        )
        evidence = build_holdings_intelligence_evidence(concentrated)
        self.assertEqual(evidence.holding_count, 200)
        self.assertLess(evidence.effective_number_of_holdings or 99, 8)
        view = evaluate_official_fund_intelligence(
            "SPUS",
            lookthrough=build_fund_lookthrough_summary(concentrated),
        )
        score = view.dimension(DIM_DIVERSIFICATION_EVAL).score
        self.assertIsNotNone(score)
        self.assertLess(score, 40)


class IssuerCountryCurrencyFirewallTests(unittest.TestCase):
    def test_spsk_issuer_missing_without_official_field(self) -> None:
        file = load_official_holdings_file("SPSK")
        self.assertFalse(official_issuer_field_present(file))
        self.assertTrue(all(official_issuer_value(row) is None for row in file.holdings))
        csv_only = evaluate_official_fund_intelligence("SPSK", use_official_fixed_income=False)
        self.assertEqual(csv_only.evidence_map()[DIM_ISSUER_CONCENTRATION], DIM_STATUS_MISSING)

    def test_no_issuer_name_guessing(self) -> None:
        parsed = parse_official_holdings_csv(
            _csv(
                "SPSK",
                [
                    _row("SPSK", "BT6MTT4", "KSA Sukuk Ltd 4.274%", "50.00%", cusip="BT6MTT4"),
                    _row("SPSK", "BNC3KG3", "KSA Sukuk Ltd 4.511%", "50.00%", cusip="BNC3KG3"),
                ],
            ),
            fund_symbol="SPSK",
        )
        self.assertFalse(official_issuer_field_present(parsed))
        view = evaluate_official_fund_intelligence(
            "SPSK",
            lookthrough=build_fund_lookthrough_summary(parsed),
            use_official_fixed_income=False,
        )
        self.assertEqual(view.evidence_map()[DIM_ISSUER_CONCENTRATION], DIM_STATUS_MISSING)

    def test_spwo_does_not_guess_country_or_currency(self) -> None:
        view = evaluate_official_fund_intelligence("SPWO")
        self.assertEqual(view.evidence_map()[DIM_COUNTRY_CONCENTRATION], DIM_STATUS_READY)
        self.assertEqual(view.dimension(DIM_COUNTRY_CONCENTRATION).facts_used, ("nport_invCountry",))
        self.assertEqual(view.evidence_map()[DIM_CURRENCY_EXPOSURE], DIM_STATUS_MISSING)
        self.assertEqual(view.evidence_map()[DIM_DIVERSIFICATION_EVAL], DIM_STATUS_READY)
        self.assertEqual(view.evidence_map()[DIM_CONCENTRATION_EVAL], DIM_STATUS_READY)
        limitation = build_fund_lookthrough_summary(load_official_holdings_file("SPWO")).limitation
        self.assertIn("COUNTRY_UNKNOWN", limitation)
        self.assertIn("SECTOR_UNKNOWN", limitation)

    def test_spre_real_estate_stays_missing(self) -> None:
        view = evaluate_official_fund_intelligence("SPRE")
        self.assertEqual(view.evidence_map()[DIM_CONCENTRATION_EVAL], DIM_STATUS_READY)
        reit = view.dimension(DIM_REAL_ESTATE_CONCENTRATION)
        self.assertEqual(reit.status, DIM_STATUS_MISSING)
        self.assertIn("SECURITY_LEVEL_USES_CONCENTRATION", reit.reason_codes)


class IntelligenceTransitionTests(unittest.TestCase):
    def test_official_dimensions_and_risk_firewall(self) -> None:
        for symbol in ("SPUS", "SPSK", "SPRE", "SPWO"):
            view = evaluate_official_fund_intelligence(symbol)
            evidence = view.evidence_map()
            self.assertEqual(evidence[DIM_DIVERSIFICATION_EVAL], DIM_STATUS_READY, symbol)
            self.assertEqual(evidence[DIM_CONCENTRATION_EVAL], DIM_STATUS_READY, symbol)
            self.assertEqual(evidence[DIM_RISK_EVAL], DIM_STATUS_MISSING, symbol)
            self.assertNotIn("drawdown", " ".join(view.provenance))

    def test_purification_isolation(self) -> None:
        provider = default_official_sp_funds_provider()
        first = evaluate_official_fund_intelligence("SPUS")
        mutated = provider.purification_evidence("SPUS")
        second = evaluate_official_fund_intelligence("SPUS")
        self.assertEqual(first.score, second.score)
        self.assertEqual(first.state, second.state)
        self.assertEqual(first.purification_factor_pct, mutated.latest_factor_pct)


class EightENewMoneyOverlapTests(unittest.TestCase):
    def test_8e_and_new_money_fail_closed_when_insufficient(self) -> None:
        for symbol in ("SPUS", "SPSK", "SPRE", "SPWO"):
            view = evaluate_official_fund_intelligence(symbol)
            decision = evaluate_official_fund_decision(
                symbol, is_holding=True, portfolio_weight=15.0, economic_exposure_available=True
            )
            if view.state == "INSUFFICIENT_DATA":
                self.assertEqual(decision.decision, DECISION_INSUFFICIENT_DATA)
                self.assertFalse(decision.exposure_increase_allowed)
        missing = evaluate_portfolio_security_decision(
            PortfolioSecurityContext(
                symbol="SPSK",
                instrument_type="ETF",
                market="US",
                is_holding=True,
                portfolio_weight=10.0,
                economic_exposure_status="STRICT",
            )
        )
        self.assertFalse(missing.exposure_increase_allowed)

    def test_ana_hybrid_off_and_overlap(self) -> None:
        holdings = default_official_holdings_files()
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
        overlap = build_fund_portfolio_overlap(
            [
                {"symbol": "AAPL", "weight_pct": 8, "asset_class": "equity"},
                {"symbol": "AVGO", "weight_pct": 0, "asset_class": "equity"},
                {"symbol": "CRM", "weight_pct": 8, "asset_class": "equity"},
                {"symbol": "SPUS", "weight_pct": 25, "asset_class": "etf"},
            ],
            holdings,
        )
        by_symbol = {row.underlying_symbol: row for row in overlap.rows}
        self.assertGreater(by_symbol["AAPL"].direct_weight_pct, 0)
        self.assertGreater(by_symbol["AAPL"].lookthrough_weight_pct, 0)
        self.assertGreater(by_symbol["AVGO"].lookthrough_weight_pct, 0)
        self.assertGreater(by_symbol["CRM"].lookthrough_weight_pct, 0)
        self.assertGreater(by_symbol["CRM"].direct_weight_pct, 0)

    def test_us_bist_isolation_and_no_writes(self) -> None:
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
        for path in (SUMMARY, ENGINE):
            text = path.read_text(encoding="utf-8").lower()
            for token in WRITE_TOKENS:
                self.assertNotIn(token, text)
            for token in GUESS_TOKENS:
                self.assertNotIn(token, text)
