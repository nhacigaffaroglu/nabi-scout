from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from services.fund_decision_readiness import (
    REASON_FUND_INTELLIGENCE_MISSING,
    evaluate_fund_eight_e_readiness,
    evaluate_fund_new_money_readiness,
)
from services.fund_holdings_change import detect_holdings_changes, holding_snapshot_identity
from services.fund_lookthrough_summary import build_fund_lookthrough_summary
from services.fund_portfolio_overlap import build_fund_portfolio_overlap
from services.fund_product_contract import (
    PILOT_FUND_SYMBOLS,
    READINESS_NEEDS_MORE_DATA,
    READINESS_NOT_APPLICABLE,
    READINESS_READY_NOW,
    REGION_INTERNATIONAL_EX_US,
)
from services.official_fund_holdings_client import parse_official_holdings_csv
from services.official_sp_funds_product import (
    OfficialSpFundsProductProvider,
    TefasFundProductProvider,
    assert_provider_surface,
    fund_intelligence_readiness,
    mandate_from_official_facts,
    parse_official_product_html,
    parse_purification_html,
    parse_sharia_evidence_html,
)
from services.portfolio_economic_exposure import (
    ExposureEvidenceSource,
    classify_instrument_exposure,
)
from services.portfolio_security_decision_contract import (
    DECISION_INSUFFICIENT_DATA,
    REASON_UNSUPPORTED_INSTRUMENT,
)
from services.portfolio_security_decision_engine import (
    evaluate_portfolio_security_decision,
    supports_portfolio_decision,
)
from services.portfolio_security_decision_contract import PortfolioSecurityContext
from services.security_intelligence_contract import STATE_WATCH
from services.wealth_new_money_allocation import allocate_new_money
from tests.fixtures.sp_funds_official import (
    NAME_ONLY_HTML,
    PRODUCT_HTML,
    PURIFICATION_HTML,
    SPUS_PRODUCT_HTML,
)
from tests.test_official_fund_holdings import _csv, _row
from tests.test_portfolio_allocation_intelligence import _complete_usd_view
from tests.test_portfolio_economic_exposure import _equity, _etf


FOUNDATION = Path("services/official_sp_funds_product.py")
HOLDINGS = Path("services/official_fund_holdings_client.py")
EXPOSURE = Path("services/portfolio_economic_exposure.py")
BIST = Path("services/bist_refresh_contract.py")


def _provider() -> OfficialSpFundsProductProvider:
    return OfficialSpFundsProductProvider(
        product_html=PRODUCT_HTML,
        purification_html=PURIFICATION_HTML,
    )


def _holdings(symbol: str, rows: list[str]) -> object:
    return parse_official_holdings_csv(_csv(symbol, rows), fund_symbol=symbol)


class IdentityAndFactsTests(unittest.TestCase):
    def test_identity_resolution_from_official_pages(self) -> None:
        provider = _provider()
        expected = {
            "SPUS": ("886364801", "NYSE", "USD"),
            "SPSK": ("886364702", "NYSE", "USD"),
            "SPRE": ("886364769", "NYSE", "USD"),
            "SPWO": ("84612A200", "NYSE", "USD"),
        }
        for symbol, (cusip, exchange, currency) in expected.items():
            identity = provider.identity(symbol)
            self.assertEqual(identity.symbol, symbol)
            self.assertEqual(identity.instrument_type, "ETF")
            self.assertEqual(identity.issuer_family, "SP Funds")
            self.assertEqual(identity.cusip, cusip)
            self.assertEqual(identity.exchange, exchange)
            self.assertEqual(identity.currency, currency)
            self.assertTrue(identity.official_name)

    def test_spwo_keeps_caller_symbol_when_table_ticker_mismatches(self) -> None:
        facts = parse_official_product_html(PRODUCT_HTML["SPWO"], symbol="SPWO")
        self.assertEqual(facts.symbol, "SPWO")
        self.assertIn("OFFICIAL_TABLE_TICKER_MISMATCH", facts.limitations)
        self.assertEqual(facts.cusip, "84612A200")


class HoldingsParseTests(unittest.TestCase):
    def test_parses_price_net_assets_and_international_cusip_only(self) -> None:
        parsed = parse_official_holdings_csv(
            _csv(
                "SPWO",
                [
                    _row("SPWO", "NESN", "Nestle", "40.00%", cusip="633517442"),
                    "08/28/2026,SPWO,,6771720,Samsung Electronics,1,12.5,12.5,60.00%,100,10,1",
                ],
            ),
            fund_symbol="SPWO",
        )
        by_id = {row.holding_identifier: row for row in parsed.holdings}
        self.assertEqual(by_id["NESN"].price, 1.0)
        self.assertEqual(by_id["NESN"].net_assets, 1.0)
        self.assertEqual(by_id["NESN"].shares_outstanding, 1.0)
        self.assertEqual(by_id["6771720"].ticker, "")
        self.assertEqual(by_id["6771720"].cusip_raw, "6771720")
        self.assertAlmostEqual(sum(row.weight_pct for row in parsed.holdings), 100.0)

    def test_snapshot_identity_and_change_detection(self) -> None:
        first = _holdings("SPUS", [_row("SPUS", "AAPL", "Apple", "60.00%"), _row("SPUS", "MSFT", "Microsoft", "40.00%")])
        second = _holdings(
            "SPUS",
            [
                "08/29/2026,SPUS,AAPL,037833100,Apple,1,1,1,55.00%,1,1,1",
                "08/29/2026,SPUS,AVGO,11135F101,Broadcom,1,1,1,45.00%,1,1,1",
            ],
        )
        self.assertEqual(
            holding_snapshot_identity(fund_symbol="SPUS", as_of=first.as_of, holding_identifier="AAPL"),
            ("SPUS", "2026-08-28", "AAPL"),
        )
        changes = detect_holdings_changes(first, second)
        self.assertTrue(changes.new_holdings_date)
        self.assertEqual(changes.added, ("AVGO",))
        self.assertEqual(changes.removed, ("MSFT",))
        self.assertEqual(changes.weight_changed, ("AAPL",))


class ExposureAndMandateTests(unittest.TestCase):
    def test_official_mandate_uses_canonical_layers(self) -> None:
        provider = _provider()
        expected = {
            "SPUS": ("equity", "US", None),
            "SPSK": ("sukuk", "GLOBAL", "SUKUK"),
            "SPRE": ("real_estate", "GLOBAL", "REIT"),
            "SPWO": ("equity", REGION_INTERNATIONAL_EX_US, None),
        }
        for symbol, (layer, region, vehicle) in expected.items():
            mandate = provider.mandate(symbol)
            self.assertEqual(mandate.primary_layer, layer)
            self.assertEqual(mandate.region, region)
            self.assertEqual(mandate.vehicle, vehicle)
            view = classify_instrument_exposure(_etf(symbol), fund_mandates={symbol: mandate})
            self.assertTrue(view.evidence_complete)
            self.assertEqual(view.economic_exposures[0].exposure_bucket, layer)
            self.assertEqual(
                view.economic_exposures[0].evidence_source,
                ExposureEvidenceSource.OFFICIAL_FUND_MANDATE,
            )
            self.assertNotIn("EXPOSURE_CLASSIFICATION_INCOMPLETE", view.limitations)

    def test_no_symbol_shortcut_in_holdings_or_mandate_source(self) -> None:
        for path in (FOUNDATION, HOLDINGS):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn('if symbol == "SPSK"', source)
            self.assertNotIn('if fund == "SPRE"', source)


class ShariaAndPurificationTests(unittest.TestCase):
    def test_official_sharia_evidence_does_not_invent_uygun(self) -> None:
        for symbol in PILOT_FUND_SYMBOLS:
            evidence = parse_sharia_evidence_html(PRODUCT_HTML[symbol], symbol=symbol)
            self.assertTrue(evidence.official_mandate_present)
            self.assertTrue(evidence.official_certificate_listed)
            self.assertEqual(evidence.methodology, "AAOIFI")
            self.assertIsNone(evidence.participation_status)
            self.assertIn("NO_INVENTED_UYGUN", evidence.limitations)

    def test_name_only_is_not_compliance(self) -> None:
        evidence = parse_sharia_evidence_html(NAME_ONLY_HTML, symbol="SPUS")
        self.assertFalse(evidence.official_mandate_present)
        self.assertFalse(evidence.official_certificate_listed)
        self.assertEqual(evidence.eligibility_ready, READINESS_NEEDS_MORE_DATA)
        self.assertIsNone(evidence.participation_status)

    def test_purification_separated_and_spsk_not_required(self) -> None:
        parsed = parse_purification_html(PURIFICATION_HTML)
        self.assertTrue(parsed["SPUS"].purification_required)
        self.assertEqual(parsed["SPUS"].latest_factor_pct, 1.81)
        self.assertEqual(parsed["SPUS"].factor_period, "Q1 2026")
        self.assertFalse(parsed["SPSK"].purification_required)
        self.assertIsNone(parsed["SPSK"].latest_factor_pct)
        self.assertTrue(parsed["SPRE"].purification_required)
        self.assertTrue(parsed["SPWO"].purification_required)


class LookthroughAndOverlapTests(unittest.TestCase):
    def test_lookthrough_weights_and_unknown_without_guessed_sector(self) -> None:
        file = parse_official_holdings_csv(
            _csv(
                "SPUS",
                [
                    _row("SPUS", "AAPL", "Apple", "50.00%"),
                    _row("SPUS", "Cash&Other", "Cash & Other", "5.00%", cusip="Cash&Other"),
                    "08/28/2026,SPUS,MSFT,594918104,Microsoft,1,1,1,45.00%,1,1,1",
                ],
            ),
            fund_symbol="SPUS",
        )
        summary = build_fund_lookthrough_summary(file, known_nabi_symbols=("AAPL",))
        self.assertEqual(summary.top_holding.holding_identifier, "AAPL")
        self.assertEqual(summary.top_holding_weight_pct, 50.0)
        self.assertEqual(summary.top10_weight_pct, 100.0)
        self.assertEqual(summary.cash_other_weight_pct, 5.0)
        self.assertEqual(summary.unknown_weight_pct, 0.0)
        self.assertEqual(summary.sector_allocation, ())
        self.assertIn("SECTOR_UNKNOWN", summary.limitation)
        self.assertEqual(summary.known_nabi_overlap, ("AAPL",))

    def test_direct_plus_indirect_overlap(self) -> None:
        spus = _holdings(
            "SPUS",
            [_row("SPUS", "AAPL", "Apple", "70.00%"), _row("SPUS", "AVGO", "Broadcom", "30.00%")],
        )
        view = build_fund_portfolio_overlap(
            [
                {"symbol": "AAPL", "weight_pct": 10.0, "asset_class": "equity"},
                {"symbol": "AVGO", "weight_pct": 5.0, "asset_class": "equity"},
                {"symbol": "SPUS", "weight_pct": 20.0, "asset_class": "etf"},
            ],
            {"SPUS": spus},
        )
        rows = {row.underlying_symbol: row for row in view.rows}
        self.assertAlmostEqual(rows["AAPL"].direct_weight_pct, 10.0)
        self.assertAlmostEqual(rows["AAPL"].lookthrough_weight_pct, 14.0)
        self.assertAlmostEqual(rows["AAPL"].combined_weight_pct, 24.0)
        self.assertIn("AAPL", view.direct_symbols)
        self.assertIn("AAPL", view.indirect_symbols)


class ReadinessAndSafetyTests(unittest.TestCase):
    def test_fund_intelligence_readiness_has_no_invented_score(self) -> None:
        provider = _provider()
        facts = provider.facts("SPSK")
        report = fund_intelligence_readiness(
            facts=facts,
            mandate=provider.mandate("SPSK"),
            sharia=provider.sharia_evidence("SPSK"),
            purification=provider.purification_evidence("SPSK"),
            lookthrough_unknown_pct=0.0,
            official_performance_present=True,
        )
        self.assertFalse(report.invented_score)
        by_dim = {item.dimension: item.state for item in report.dimensions}
        self.assertEqual(by_dim["duration_yield_credit"], READINESS_NEEDS_MORE_DATA)
        self.assertEqual(by_dim["real_estate_risk"], READINESS_NOT_APPLICABLE)
        self.assertIn(by_dim["participation_mandate"], {READINESS_READY_NOW, READINESS_NEEDS_MORE_DATA})

    def test_etf_8e_fail_closed_and_equity_isolation(self) -> None:
        fund = evaluate_fund_eight_e_readiness(
            symbol="SPUS",
            fund_intelligence_ready=False,
            participation_acceptable=False,
            economic_exposure_available=True,
        )
        self.assertEqual(fund["decision"], DECISION_INSUFFICIENT_DATA)
        self.assertFalse(fund["exposure_increase_allowed"])
        self.assertIn(REASON_FUND_INTELLIGENCE_MISSING, fund["blocking_reasons"])
        self.assertIn(REASON_UNSUPPORTED_INSTRUMENT, fund["blocking_reasons"])
        self.assertFalse(supports_portfolio_decision(instrument_type="ETF", market="US", symbol="SPUS"))
        equity = evaluate_portfolio_security_decision(
            PortfolioSecurityContext(
                symbol="AAPL",
                participation_status="Uygun",
                research_allowed=True,
                si_state=STATE_WATCH,
                si_score=53.3,
                is_holding=True,
                instrument_type="EQUITY",
                market="US",
            )
        )
        self.assertNotEqual(equity.decision, DECISION_INSUFFICIENT_DATA)
        self.assertFalse(supports_portfolio_decision(symbol="CRM", instrument_type="ETF"))
        self.assertTrue(supports_portfolio_decision(symbol="CRM", instrument_type="EQUITY", market="US"))

    def test_new_money_fail_closed_and_hybrid_off(self) -> None:
        provider = _provider()
        mandates = {symbol: provider.mandate(symbol) for symbol in PILOT_FUND_SYMBOLS}
        readiness = evaluate_fund_new_money_readiness(
            mandate=mandates["SPUS"],
            hybrid_off=True,
            exposure_complete=True,
        )
        self.assertEqual(readiness["economic_layer"], "equity")
        self.assertTrue(readiness["hybrid_off_preserved"])
        self.assertFalse(readiness["allocates_money"])
        view = _complete_usd_view()
        plan = allocate_new_money(
            available_amount=Decimal("1000"),
            amount_currency="USD",
            portfolio_view=view,
            fund_mandates=mandates,
            enable_hybrid_exposure_allocation=False,
        )
        self.assertEqual(plan.recommendations, ())
        self.assertFalse(any("HYBRID ON" in item for item in plan.limitations))

    def test_tefas_provider_shares_surface_without_implementation(self) -> None:
        tefas = TefasFundProductProvider()
        self.assertEqual(
            assert_provider_surface(tefas),
            assert_provider_surface(_provider()),
        )
        self.assertFalse(tefas.supports("SPUS"))
        with self.assertRaises(NotImplementedError):
            tefas.facts("TVF")

    def test_no_production_writes_or_paid_api(self) -> None:
        for path in (FOUNDATION, HOLDINGS, EXPOSURE, Path("services/fund_decision_readiness.py")):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("FMPClient", source)
            self.assertNotIn("DATABASE_URL", source)
        self.assertTrue(BIST.is_file())
        bist = BIST.read_text(encoding="utf-8")
        self.assertIn("ASELS", bist)

    def test_name_only_mandate_fails(self) -> None:
        facts = parse_official_product_html(NAME_ONLY_HTML, symbol="SPUS")
        with self.assertRaises(ValueError):
            mandate_from_official_facts(facts)


if __name__ == "__main__":
    unittest.main()
