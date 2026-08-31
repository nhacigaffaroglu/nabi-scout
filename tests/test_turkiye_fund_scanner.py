from __future__ import annotations

import unittest
import uuid
from datetime import date
from pathlib import Path

from services.fund_intelligence_engine import evaluate_official_fund_intelligence, weights_for_profile
from services.fund_product_contract import (
    ASSET_GROUP_CASH,
    ASSET_GROUP_PRECIOUS_METALS,
    LAYER_CASH_LIKE,
    LAYER_PRECIOUS_METALS,
    MANDATE_UNRESOLVED,
    OfficialFundMandate,
    PILOT_TEFAS_FUND_CODES,
    PRECIOUS_METALS_PARTICIPATION_FUND_WEIGHTS,
    PROFILE_PRECIOUS_METALS_PARTICIPATION,
    PROFILE_PRECIOUS_METALS_PARTICIPATION_FUND,
    REGION_TR,
)
from services.official_kap_fund import official_profile_from_kap, parse_kap_ybf_text
from services.official_kap_pdr import discover_latest_pdr, normalize_pdr_asset_group
from services.official_kap_pdr_evidence import try_load_captured_pdr_holdings
from services.official_tefas_performance import (
    annualized_volatility_pct,
    maximum_drawdown,
    performance_from_tefas_series,
    weekend_zero_return_injected,
)
from services.official_tefas_product import default_tefas_fund_provider, mandate_from_kap
from services.official_turkiye_fund_exposure import classify_official_turkiye_fund_exposure
from services.official_turkiye_fund_participation import (
    evaluate_turkiye_fund_participation,
    mandate_from_name_only,
    mandate_from_umbrella_only,
)
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)
from services.turkiye_fund_pdr_window import (
    current_month_pdr_missing_is_not_stale,
    latest_applicable_pdr_period,
    pdr_publication_window_opens,
    pdr_row_is_applicable,
)
from services.turkiye_fund_scanner import run_turkiye_fund_scanner
from services.turkiye_fund_scanner_adviser import (
    format_scanner_adviser_narrative,
    is_turkiye_fund_scanner_question,
    scanner_adviser_facts,
)
from services.turkiye_fund_source_capture import assert_official_host, cache_identity, load_or_store
from services.turkiye_fund_universe_contract import (
    SCANNER_BLOCKED,
    SCANNER_READY,
    SCANNER_REVIEW_REQUIRED,
    TEFAS_STATUS_ACTIVE,
    TEFAS_STATUS_INACTIVE,
)
from services.turkiye_fund_universe_discovery import (
    discover_turkiye_participation_universe,
    official_title_has_katilim,
    select_representative_sample,
)
from services.wealth_asset_classification import CASH_SYMBOL

FROZEN = {
    "AIS": (70.39, "WATCH"),
    "ZPE": (66.32, "WATCH"),
    "IAT": (60.49, "NEUTRAL"),
}
SCANNER = Path("services/turkiye_fund_scanner.py")
DISCOVERY = Path("services/turkiye_fund_universe_discovery.py")
CAPTURE = Path("services/turkiye_fund_source_capture.py")
ADVISER = Path("services/turkiye_fund_scanner_adviser.py")
PAGE = Path("pages/13_Turkiye_Fon_Tarama.py")


def _row(**fields):
    payload = {
        "fundCode": "ZZZ",
        "kapTitle": "ÖRNEK PORTFÖY KATILIM FONU",
        "year": 2026,
        "period": 7,
        "publishDate": "06.08.2026 09:16:20",
        "disclosureIndex": 1,
        "subject": "Portföy Dağılım Raporu",
        "disclosureClass": "DG",
    }
    payload.update(fields)
    return payload


class TurkiyeFundScannerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = run_turkiye_fund_scanner(persist=False, sample_only=True)

    def test_automatic_universe_discovery_without_allowlist(self) -> None:
        source = DISCOVERY.read_text(encoding="utf-8")
        self.assertNotIn("PILOT_TEFAS_FUND_CODES", source)
        self.assertGreaterEqual(self.result.discovered_count, 200)
        codes = {row.fund_code for row in self.result.identities}
        self.assertTrue({"AIS", "ZPE", "IAT"}.issubset(codes))
        self.assertGreater(len(codes), 3)
        self.assertEqual(len(codes), self.result.discovered_count)

    def test_identity_dedupe_by_fund_code(self) -> None:
        rows = [
            _row(fundCode="AIS", disclosureIndex=1, period=6),
            _row(fundCode="AIS", disclosureIndex=2, period=7),
            _row(fundCode="ais", disclosureIndex=3, period=7),
        ]
        found = discover_turkiye_participation_universe(rows)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].fund_code, "AIS")
        self.assertEqual(found[0].pdr_period, 7)

    def test_name_katilim_is_discovery_not_uygun(self) -> None:
        self.assertTrue(official_title_has_katilim("AK PORTFÖY PARA PİYASASI KATILIM FONU"))
        self.assertEqual(mandate_from_name_only("Katılım Fonu"), MANDATE_UNRESOLVED)
        self.assertEqual(
            evaluate_turkiye_fund_participation("XYZ", name_only=True, official_name="Katılım Fonu").participation_status,
            PARTICIPATION_STATUS_KONTROL_ET,
        )
        self.assertEqual(
            evaluate_turkiye_fund_participation("XYZ", umbrella_only=True, umbrella_type="Katılım Şemsiye Fonu").participation_status,
            PARTICIPATION_STATUS_KONTROL_ET,
        )
        _ = mandate_from_umbrella_only

    def test_active_inactive_separation(self) -> None:
        by_code = {row.fund_code: row for row in self.result.identities}
        self.assertEqual(by_code["AIS"].tefas_status, TEFAS_STATUS_ACTIVE)
        self.assertEqual(by_code["APGLD"].tefas_status, TEFAS_STATUS_INACTIVE)
        self.assertGreater(self.result.active_count, 100)
        self.assertLess(self.result.active_count, self.result.discovered_count)
        blocked = [row for row in self.result.rows if row.scanner_status == SCANNER_BLOCKED]
        self.assertTrue(blocked)

    def test_pdr_publication_window(self) -> None:
        as_of = date(2026, 8, 31)
        self.assertEqual(latest_applicable_pdr_period(as_of), (2026, 7))
        self.assertEqual(pdr_publication_window_opens(2026, 8), date(2026, 9, 1))
        self.assertTrue(current_month_pdr_missing_is_not_stale(as_of, has_current_month_pdr=False))
        july = _row(year=2026, period=7, publishDate="06.08.2026 09:16:20")
        august = _row(year=2026, period=8, publishDate="01.09.2026 09:00:00")
        future = _row(year=2026, period=7, publishDate="01.09.2026 09:00:00")
        self.assertTrue(pdr_row_is_applicable(july, as_of))
        self.assertFalse(pdr_row_is_applicable(august, as_of))
        self.assertFalse(pdr_row_is_applicable(future, as_of))
        discovery = discover_latest_pdr([july, august], "ZZZ", as_of=as_of)
        self.assertEqual(discovery.period, 7)

    def test_source_date_firewall_and_official_hosts(self) -> None:
        assert_official_host("https://www.tefas.gov.tr/api/funds/fonBilgiGetir")
        assert_official_host("https://www.kap.org.tr/tr/api/disclosure/funds/byCriteria")
        with self.assertRaises(ValueError):
            assert_official_host("https://financialmodelingprep.com/api")
        with self.assertRaises(ValueError):
            assert_official_host("https://yahoo.com/fund")
        identity = cache_identity(kind="tefas_snapshot", key="AIS-unit-test", published_at=str(uuid.uuid4()))
        first, hit1 = load_or_store(kind="test_scanner", key=identity, fetcher=lambda: {"n": 1})
        second, hit2 = load_or_store(kind="test_scanner", key=identity, fetcher=lambda: {"n": 2})
        self.assertFalse(hit1)
        self.assertTrue(hit2)
        self.assertEqual(first["n"], second["n"])

    def test_participation_gate_and_review_queue(self) -> None:
        by_code = {row.fund_code: row for row in self.result.rows}
        for code in PILOT_TEFAS_FUND_CODES:
            self.assertEqual(by_code[code].participation, PARTICIPATION_STATUS_UYGUN)
            self.assertTrue(by_code[code].research_allowed)
            self.assertEqual(by_code[code].scanner_status, SCANNER_READY)
        kontrol = [row for row in self.result.review_queue if row.participation == PARTICIPATION_STATUS_KONTROL_ET]
        self.assertTrue(kontrol)
        self.assertTrue(all(row.scanner_status != SCANNER_READY for row in kontrol))
        adverse = evaluate_turkiye_fund_participation(
            "AIS",
            forced_contradiction=("ADVERSE_OFFICIAL_HOLDING",),
        )
        self.assertEqual(adverse.participation_status, PARTICIPATION_STATUS_UYGUN_DEGIL)
        self.assertFalse(adverse.research_allowed)

    def test_generalized_pdr_and_reconciliation_fail_closed(self) -> None:
        missing = try_load_captured_pdr_holdings("APGLD")
        self.assertIsNone(missing)
        self.assertEqual(normalize_pdr_asset_group("Kıymetli Madenler"), ASSET_GROUP_PRECIOUS_METALS)
        ais = try_load_captured_pdr_holdings("AIS")
        self.assertIsNotNone(ais)
        self.assertFalse(ais.weights.renormalized)

    def test_economic_exposure_and_cash_firewalls(self) -> None:
        provider = default_tefas_fund_provider()
        ais = provider.economic_classification("AIS")
        self.assertEqual(ais.primary_exposure, LAYER_CASH_LIKE)
        self.assertNotEqual(ais.primary_exposure, "cash")
        self.assertIn("NOT_PORTFOLIO_CASH", ais.limitations)
        self.assertNotEqual(ais.symbol, CASH_SYMBOL)
        pdr = try_load_captured_pdr_holdings("AIS")
        self.assertIsNotNone(pdr)
        gold_mandate = OfficialFundMandate(
            symbol="BAI",
            primary_layer=LAYER_PRECIOUS_METALS,
            region=REGION_TR,
            vehicle=PROFILE_PRECIOUS_METALS_PARTICIPATION_FUND,
            confidence="HIGH",
            source="kap_fund",
            source_url="https://www.kap.org.tr",
            evidence_excerpt="altın yatırım portföy",
        )
        gold_mandate.validate()
        self.assertIsNone(classify_official_turkiye_fund_exposure(gold_mandate, None))
        self.assertNotEqual(LAYER_PRECIOUS_METALS, LAYER_CASH_LIKE)
        self.assertNotEqual(LAYER_PRECIOUS_METALS, "cash")
        self.assertNotEqual(ASSET_GROUP_PRECIOUS_METALS, ASSET_GROUP_CASH)
        ybf = parse_kap_ybf_text("Fon portföyü altın ve kıymetli maden yatırım araçlarından oluşur.")
        self.assertTrue(ybf["precious_metals_mandate"])
        self.assertEqual(
            official_profile_from_kap(umbrella_type="Katılım", ybf={"precious_metals_mandate": True}),
            PROFILE_PRECIOUS_METALS_PARTICIPATION,
        )
        routed = mandate_from_kap(
            type("Kap", (), {
                "official_profile": PROFILE_PRECIOUS_METALS_PARTICIPATION,
                "fund_code": "BAI",
                "strategy_text": "altın yatırım portföy",
                "official_name": "BV PORTFÖY ALTIN KATILIM FONU",
                "source": "kap_fund",
                "source_url": "https://www.kap.org.tr",
                "limitations": (),
            })()
        )
        self.assertEqual(routed.primary_layer, LAYER_PRECIOUS_METALS)
        self.assertNotEqual(routed.primary_layer, LAYER_CASH_LIKE)
        self.assertNotEqual(routed.primary_layer, "cash")

    def test_fi_profile_routing_and_performance(self) -> None:
        self.assertAlmostEqual(sum(PRECIOUS_METALS_PARTICIPATION_FUND_WEIGHTS.values()), 1.0)
        self.assertEqual(
            weights_for_profile(PROFILE_PRECIOUS_METALS_PARTICIPATION_FUND),
            dict(PRECIOUS_METALS_PARTICIPATION_FUND_WEIGHTS),
        )
        profiles = {row.fi_profile for row in self.result.rows if row.fi_profile}
        self.assertIn("LIQUIDITY_PARTICIPATION_FUND", profiles)
        self.assertIn("EQUITY_PARTICIPATION_FUND", profiles)
        self.assertIn("SUKUK_PARTICIPATION_FUND", profiles)
        provider = default_tefas_fund_provider()
        series = provider.price_history("AIS", period_months=12)
        self.assertFalse(weekend_zero_return_injected(series.observations))
        perf = performance_from_tefas_series(series, official_risk_value=provider.official_risk_value("AIS"))
        self.assertIsNotNone(perf.return_1y)
        self.assertIsNotNone(annualized_volatility_pct(series.observations))
        drawdown, _peak, _trough = maximum_drawdown(series.observations)
        self.assertIsNotNone(drawdown)
        self.assertNotEqual(str(perf.drawdown), provider.official_risk_value("AIS"))

    def test_category_peer_ranking_no_hidden_score(self) -> None:
        source = SCANNER.read_text(encoding="utf-8")
        self.assertIn("evaluate_official_fund_intelligence", source)
        self.assertNotIn("hidden_score", source)
        self.assertNotIn("allocate_new_money", source)
        self.assertNotIn("evaluate_portfolio_security_decision", source)
        by_code = {row.fund_code: row for row in self.result.rows}
        for code, (score, state) in FROZEN.items():
            view = evaluate_official_fund_intelligence(code)
            self.assertEqual(by_code[code].fi_score, view.score)
            self.assertEqual(by_code[code].fi_score, score)
            self.assertEqual(by_code[code].fi_state, state)
            self.assertEqual(by_code[code].category, view.fund_type_profile and {
                "LIQUIDITY_PARTICIPATION_FUND": LAYER_CASH_LIKE,
                "EQUITY_PARTICIPATION_FUND": "equity",
                "SUKUK_PARTICIPATION_FUND": "sukuk",
            }.get(view.fund_type_profile))
        categories = set(self.result.ranked_by_category)
        self.assertGreaterEqual(len(categories), 3)
        for category, rows in self.result.ranked_by_category.items():
            scores = [row.fi_score for row in rows]
            self.assertEqual(scores, sorted(scores, reverse=True))
            self.assertTrue(all(row.category == category for row in rows))
            self.assertTrue(all(row.scanner_status == SCANNER_READY for row in rows))
        shortlist = self.result.overall_shortlist
        self.assertTrue(shortlist)
        self.assertEqual(shortlist[0].peer_view, "OVERALL_RESEARCH")

    def test_representative_sample_and_no_portfolio_decision(self) -> None:
        sample = self.result.sample_codes
        self.assertGreater(len(sample), 3)
        discovered = {row.fund_code for row in self.result.identities}
        self.assertTrue(set(sample).issubset(discovered))
        include = select_representative_sample(self.result.identities, include_if_discovered=("AIS", "ZPE", "IAT"))
        self.assertTrue({"AIS", "ZPE", "IAT"}.issubset(include))
        with self.assertRaises(ValueError):
            run_turkiye_fund_scanner(persist=True)
        self.assertEqual(self.result.eight_e_calls, 0)
        self.assertEqual(self.result.new_money_calls, 0)
        self.assertEqual(self.result.trades, 0)
        self.assertEqual(self.result.portfolio_writes, 0)
        self.assertEqual(self.result.production_writes, ())
        self.assertFalse(self.result.persist)
        capture = CAPTURE.read_text(encoding="utf-8")
        self.assertIn("PAID_HOST_BLOCKLIST", capture)
        for path in (SCANNER, DISCOVERY, ADVISER, PAGE):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("allocate_new_money", text)
            self.assertNotIn("add_holding", text)
        self.assertNotIn("yahoo.com", SCANNER.read_text(encoding="utf-8").casefold())

    def test_adviser_research_only_boundary(self) -> None:
        self.assertTrue(is_turkiye_fund_scanner_question("TEFAS katılım fon tarama adayları nedir?"))
        narrative = format_scanner_adviser_narrative(self.result)
        facts = scanner_adviser_facts(self.result)
        self.assertIn("araştırma", narrative.casefold())
        self.assertIn("not a buy", narrative.casefold())
        self.assertTrue(facts["not_a_buy"])
        self.assertTrue(facts["not_eight_e"])
        self.assertTrue(facts["not_new_money"])
        page = PAGE.read_text(encoding="utf-8")
        self.assertIn("SCANNER_NOT_A_BUY", page)
        self.assertIn("Satın alma", page)
        self.assertNotIn('st.button("Satın', page)
        self.assertNotIn("buy button", page.casefold())

    def test_no_eight_e_inside_scanner(self) -> None:
        text = SCANNER.read_text(encoding="utf-8")
        self.assertNotIn("fund_decision_readiness", text)
        self.assertNotIn("portfolio_security_decision_engine", text)
        self.assertNotIn("wealth_new_money_allocation", text)
        self.assertNotIn("PILOT_TEFAS_FUND_CODES", text)


if __name__ == "__main__":
    unittest.main()
