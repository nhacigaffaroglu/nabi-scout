from __future__ import annotations

import json
import unittest
from pathlib import Path

from services.kap_financial_bridge import (
    KapIdentityError,
    participation_inputs_from_kap,
    participation_inputs_from_kap_period,
)
from services.kap_financial_normalization import map_account_code
from services.kap_public_bridge import ingest_public_kap_financials
from services.kap_public_parser import parse_public_kap_html
from services.participation_financial_readiness import (
    AMBIGUOUS,
    CASH_COMPONENT_RULES,
    DEBT_COMPONENT_RULES,
    EXISTING_IFRS_AR_TAGS,
    EXISTING_US_GAAP_AR_TAGS,
    EXCLUDED_BY_EXISTING_METHOD,
    INCLUDED_BY_EXISTING_METHOD,
    NOT_RELEVANT,
    STATUS_DATA_MISSING,
    STATUS_METHODOLOGY_UNRESOLVED,
    STATUS_PERIOD_INCOMPATIBLE,
    STATUS_VALUE_AVAILABLE,
    audit_existing_methodology,
    build_participation_financial_readiness,
    classify_observed_concepts,
    derive_average_market_cap_24m,
    derive_market_cap,
)
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.portfolio_security_decision_contract import (
    DECISION_INSUFFICIENT_DATA,
    PortfolioSecurityContext,
    REASON_ECONOMIC_EXPOSURE_UNAVAILABLE,
    REASON_UNSUPPORTED_INSTRUMENT,
)
from services.portfolio_security_decision_engine import evaluate_portfolio_security_decision
from services.security_intelligence_contract import STATE_ATTRACTIVE
from services.security_master_contract import INSTRUMENT_EQUITY
from tests.fixtures.kap_participation_gap_pilot import (
    FIXTURE_DISCLAIMER,
    fy_with_receivables_html,
    ytd_receivable_html,
)
from tests.fixtures.kap_public_pilot import compact_public_html, fy_public_html


ENGINE = Path("services/portfolio_security_decision_engine.py")
BRIDGE = Path("services/kap_financial_bridge.py")
READY = Path("services/participation_financial_readiness.py")
REGISTRY = Path("config/participation_methodologies/registry.json")
SEC_CLIENT = Path("services/sec_financial_client.py")
SEC_RESOLVER = Path("services/participation_sec_input_resolver.py")
BIZ_1F = Path("services/kap_public_business_parser.py")


def _doc(html: str, *, symbol: str = "ASELS", disclosure_id: str = "1643141"):
    return parse_public_kap_html(html, symbol=symbol, disclosure_id=disclosure_id)


def _bundle(html: str, *, symbol: str = "ASELS"):
    return ingest_public_kap_financials(_doc(html, symbol=symbol), symbol=symbol)


class MethodologyAuditTests(unittest.TestCase):
    def test_existing_methodology_audit_assertions(self) -> None:
        registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
        self.assertEqual(registry["default_equity_methodology_id"], "msci_islamic_index_series")
        msci = next(
            item
            for item in registry["methodologies"]
            if item["methodology_id"] == "msci_islamic_index_series" and item.get("active")
        )
        by_id = {rule["rule_id"]: rule for rule in msci["rules"]}
        self.assertEqual(by_id["msci.receivables_and_cash_to_total_assets"]["numerator"], "accounts_receivable_plus_cash")
        self.assertEqual(by_id["msci.receivables_and_cash_to_total_assets"]["denominator"], "total_assets")
        self.assertEqual(by_id["msci.cash_and_interest_bearing_to_total_assets"]["numerator"], "cash_and_interest_bearing_securities")
        self.assertEqual(by_id["msci.non_permissible_revenue"]["numerator"], "non_permissible_revenue")
        self.assertEqual(by_id["msci.non_permissible_revenue"]["threshold_pct"], 5.0)
        self.assertNotIn("interest_bearing_debt", {rule["numerator"] for rule in msci["rules"]})
        self.assertIn("CurrentTradeReceivables", SEC_CLIENT.read_text(encoding="utf-8"))
        self.assertIn("AccountsReceivableNetCurrent", SEC_RESOLVER.read_text(encoding="utf-8"))
        self.assertIn("test_no_total_debt_to_interest_bearing_debt_substitution", Path("tests/test_participation_sec_input_resolver.py").read_text(encoding="utf-8"))
        audits = {item.field: item for item in audit_existing_methodology()}
        self.assertTrue(audits["accounts_receivable"].methodology_explicit)
        self.assertTrue(audits["accounts_receivable"].bist_implementable)
        self.assertFalse(audits["interest_bearing_debt"].bist_implementable)
        self.assertFalse(audits["non_permissible_revenue"].bist_implementable)
        self.assertEqual(EXISTING_IFRS_AR_TAGS[0], "CurrentTradeReceivables")
        self.assertEqual(EXISTING_US_GAAP_AR_TAGS[0], "AccountsReceivableNetCurrent")


class ReceivableMappingTests(unittest.TestCase):
    def test_trade_receivable_mapping_current_only(self) -> None:
        self.assertEqual(
            map_account_code("ifrs-full_CurrentTradeReceivables"),
            ("accounts_receivable", "POINT_IN_TIME"),
        )
        self.assertIsNone(map_account_code("ifrs-full_NoncurrentTradeReceivables"))
        self.assertIsNone(map_account_code("kap-fr_CurrentTradeReceivablesDueFromUnrelatedParties"))

    def test_receivable_component_provenance(self) -> None:
        bundle = _bundle(ytd_receivable_html())
        ytd, _ = participation_inputs_from_kap_period(bundle, "YTD")
        self.assertEqual(ytd.accounts_receivable, 47_167_326_000.0)
        self.assertNotEqual(ytd.accounts_receivable, 47_167_326_000.0 + 82_608_746_000.0)
        provenance = dict(ytd.field_provenance)
        self.assertIn("accounts_receivable", provenance)
        self.assertEqual(provenance["accounts_receivable"].source_fields, ("IFRS-FULL_CURRENTTRADERECEIVABLES",))
        self.assertEqual(provenance["accounts_receivable"].period, "YTD")
        fy, missing = participation_inputs_from_kap(bundle)
        self.assertIsNone(fy.accounts_receivable)
        self.assertTrue(any(item.endswith("accounts_receivable") for item in missing))


class DebtAndCashInventoryTests(unittest.TestCase):
    def test_debt_component_inventory(self) -> None:
        observed = (
            "ifrs-full_LongtermBorrowings",
            "kap-fr_CurrentPortionOfNoncurrentBorrowings",
            "kap-fr_PaymentsOfLeaseLiabilitiesClassifiedAsFinancingActivities",
            "ifrs-full_ProceedsFromBorrowingsClassifiedAsFinancingActivities",
        )
        items = {item.concept: item for item in classify_observed_concepts(observed, DEBT_COMPONENT_RULES)}
        self.assertEqual(items["ifrs-full_LongtermBorrowings"].classification, AMBIGUOUS)
        self.assertEqual(items["kap-fr_CurrentPortionOfNoncurrentBorrowings"].classification, AMBIGUOUS)
        self.assertEqual(
            items["kap-fr_PaymentsOfLeaseLiabilitiesClassifiedAsFinancingActivities"].classification,
            NOT_RELEVANT,
        )
        self.assertNotEqual(
            items["ifrs-full_LongtermBorrowings"].classification,
            INCLUDED_BY_EXISTING_METHOD,
        )
        self.assertNotIn(EXCLUDED_BY_EXISTING_METHOD, {item.classification for item in items.values()})

    def test_ambiguous_debt_fail_closed(self) -> None:
        bundle = _bundle(ytd_receivable_html())
        ytd, missing = participation_inputs_from_kap_period(bundle, "YTD")
        self.assertIsNone(ytd.interest_bearing_debt)
        self.assertTrue(any("interest_bearing_debt" in item for item in missing))
        self.assertIsNone(ytd.total_debt)

    def test_cash_component_inventory(self) -> None:
        observed = (
            "ifrs-full_CashAndCashEquivalents",
            "ifrs-full_CurrentFinancialAssetsAtFairValueThroughProfitOrLoss",
            "kap-fr_OtherCurrentFinancialInvestments",
            "ifrs-full_CurrentDerivativeFinancialAssets",
        )
        items = {item.concept: item for item in classify_observed_concepts(observed, CASH_COMPONENT_RULES)}
        self.assertEqual(items["ifrs-full_CashAndCashEquivalents"].classification, INCLUDED_BY_EXISTING_METHOD)
        self.assertEqual(
            items["ifrs-full_CurrentFinancialAssetsAtFairValueThroughProfitOrLoss"].classification,
            AMBIGUOUS,
        )
        self.assertEqual(items["kap-fr_OtherCurrentFinancialInvestments"].classification, AMBIGUOUS)
        self.assertEqual(items["ifrs-full_CurrentDerivativeFinancialAssets"].classification, NOT_RELEVANT)

    def test_ambiguous_securities_fail_closed(self) -> None:
        bundle = _bundle(ytd_receivable_html())
        ytd, missing = participation_inputs_from_kap_period(bundle, "YTD")
        self.assertIsNotNone(ytd.cash)
        self.assertIsNone(ytd.cash_and_interest_bearing_securities)
        self.assertTrue(any("cash_and_interest_bearing_securities" in item for item in missing))


class UnsupportedFieldTests(unittest.TestCase):
    def test_npr_remains_null_when_unsupported(self) -> None:
        bundle = _bundle(ytd_receivable_html())
        ytd, missing = participation_inputs_from_kap_period(bundle, "YTD")
        self.assertIsNone(ytd.non_permissible_revenue)
        self.assertTrue(any("non_permissible_revenue" in item for item in missing))
        source = READY.read_text(encoding="utf-8")
        self.assertIn("SEC 10-K", source)
        self.assertNotIn("evaluate_business_activity", source)

    def test_market_cap_derivation_requirements(self) -> None:
        self.assertIsNone(derive_market_cap(price=10.0, shares_outstanding=100.0))
        self.assertIsNone(
            derive_market_cap(
                price=10.0,
                shares_outstanding=None,
                price_source="bist_public_price",
                shares_source="",
            )
        )
        self.assertEqual(
            derive_market_cap(
                price=10.0,
                shares_outstanding=100.0,
                price_source="bist_public_price",
                shares_source="kap_share_count",
            ),
            1_000.0,
        )

    def test_24m_market_cap_fail_closed(self) -> None:
        self.assertIsNone(
            derive_average_market_cap_24m(
                monthly_prices=[10.0] * 24,
                shares_outstanding=100.0,
            )
        )
        self.assertIsNone(derive_average_market_cap_24m())


class PeriodAndReadinessTests(unittest.TestCase):
    def test_period_compatibility(self) -> None:
        ytd_bundle = _bundle(ytd_receivable_html())
        fy, _ = participation_inputs_from_kap(ytd_bundle)
        ytd, _ = participation_inputs_from_kap_period(ytd_bundle, "YTD")
        self.assertIsNone(fy.accounts_receivable)
        self.assertIsNone(fy.total_revenue)
        self.assertEqual(ytd.accounts_receivable, 47_167_326_000.0)
        self.assertEqual(ytd.total_revenue, 88_494_252_000.0)
        fy_bundle = _bundle(fy_with_receivables_html())
        fy_only, _ = participation_inputs_from_kap(fy_bundle)
        self.assertEqual(fy_only.accounts_receivable, 40_000_000_000.0)
        self.assertEqual(fy_only.total_revenue, 120_000_000_000.0)
        mixed_ready = build_participation_financial_readiness(ytd_bundle)
        self.assertEqual(mixed_ready.period, "YTD")
        self.assertNotEqual(mixed_ready.field_status["accounts_receivable"], STATUS_PERIOD_INCOMPATIBLE)

    def test_financial_readiness(self) -> None:
        bundle = _bundle(ytd_receivable_html())
        doc = _doc(ytd_receivable_html())
        ready = build_participation_financial_readiness(bundle, document=doc)
        self.assertEqual(ready.field_status["accounts_receivable"], STATUS_VALUE_AVAILABLE)
        self.assertEqual(ready.field_status["interest_bearing_debt"], STATUS_METHODOLOGY_UNRESOLVED)
        self.assertEqual(ready.field_status["cash_and_interest_bearing_securities"], STATUS_METHODOLOGY_UNRESOLVED)
        self.assertEqual(ready.field_status["non_permissible_revenue"], STATUS_METHODOLOGY_UNRESOLVED)
        self.assertEqual(ready.field_status["market_capitalization"], STATUS_DATA_MISSING)
        self.assertEqual(ready.field_status["average_market_cap_24m"], STATUS_DATA_MISSING)
        self.assertFalse(ready.financial_screen_ready)
        self.assertIn("accounts_receivable", ready.available_fields)
        self.assertEqual(ready.limitation, "READINESS_ONLY_NO_PARTICIPATION_VERDICT")
        payload = ready.to_dict()
        self.assertNotIn("Uygun", str(payload))
        self.assertFalse(payload["financial_screen_ready"])


class IsolationAndSafetyTests(unittest.TestCase):
    def test_us_isolation(self) -> None:
        with self.assertRaises(KapIdentityError):
            _bundle(ytd_receivable_html(), symbol="AAPL")
        with self.assertRaises(KapIdentityError):
            _bundle(ytd_receivable_html(), symbol="CRM")
        from services.participation_sec_input_resolver import build_participation_inputs_from_sec

        us = build_participation_inputs_from_sec(
            "AAPL",
            {
                "accounts_receivable": 15_000_000.0,
                "cash": 10.0,
                "total_assets": 100.0,
                "revenue": 50.0,
                "financial_currency": "USD",
                "financial_period_end": "2025-09-27",
                "accounts_receivable_tags": "AccountsReceivableNetCurrent",
            },
        )
        self.assertEqual(us.inputs.accounts_receivable, 15_000_000.0)
        self.assertEqual(us.source, "SEC")

    def test_no_participation_verdict_persistence(self) -> None:
        source = READY.read_text(encoding="utf-8") + BRIDGE.read_text(encoding="utf-8")
        self.assertNotIn("evaluate_financial_rules", READY.read_text(encoding="utf-8"))
        self.assertNotIn("ParticipationAssessmentRepository", source)
        self.assertNotIn("Uygun", READY.read_text(encoding="utf-8"))
        from tests.fixtures.kap_public_business_pilot import tuprs_official_notes

        self.assertIn("Rafinaj", tuprs_official_notes())
        self.assertNotIn("weapons_defense", BIZ_1F.read_text(encoding="utf-8"))

    def test_8e_unchanged(self) -> None:
        for symbol in ("ASELS", "BIMAS", "TUPRS"):
            result = evaluate_portfolio_security_decision(
                PortfolioSecurityContext(
                    symbol=symbol,
                    participation_status=PARTICIPATION_STATUS_UYGUN,
                    research_allowed=True,
                    si_state=STATE_ATTRACTIVE,
                    instrument_type=INSTRUMENT_EQUITY,
                    market="TR",
                )
            )
            self.assertEqual(result.decision, DECISION_INSUFFICIENT_DATA)
            self.assertNotIn(REASON_UNSUPPORTED_INSTRUMENT, result.blocking_reasons)
            self.assertIn(REASON_ECONOMIC_EXPOSURE_UNAVAILABLE, result.blocking_reasons)
        self.assertIn("supports_portfolio_decision", ENGINE.read_text(encoding="utf-8"))
        self.assertNotIn("if symbol in BIST_PORTFOLIO_SYMBOLS", ENGINE.read_text(encoding="utf-8"))
        self.assertIn("TEST-ONLY", FIXTURE_DISCLAIMER)
        self.assertIn("ifrs-full_CurrentTradeReceivables", compact_public_html(current_receivables="1"))
        self.assertNotIn("ifrs-full_CurrentTradeReceivables", fy_public_html())


if __name__ == "__main__":
    unittest.main()
