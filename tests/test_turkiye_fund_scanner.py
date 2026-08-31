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

    def test_broad_ui_funnel_controls(self) -> None:
        page = PAGE.read_text(encoding="utf-8")
        self.assertIn("coverage_funnel", page)
        self.assertIn("Yönetici", page)
        self.assertIn("REVIEW_REQUIRED", page)
        self.assertIn("review_reason_counts", page)
        self.assertNotIn("Buy this fund", page)


class TurkiyeFundBroadEvidenceTests(unittest.TestCase):
    def test_official_slug_from_title_not_fuzzy(self) -> None:
        from services.turkiye_fund_kap_slug import kap_official_slug

        self.assertEqual(
            kap_official_slug("AIS", "AK PORTFÖY PARA PİYASASI KATILIM FONU"),
            "ais-ak-portfoy-para-piyasasi-katilim-fonu",
        )
        self.assertEqual(
            kap_official_slug("IAT", "İŞ PORTFÖY KİRA SERTİFİKALARI KATILIM (TL) FONU"),
            "iat-is-portfoy-kira-sertifikalari-katilim-tl-fonu",
        )

    def test_java_wrapped_pdf_unwrap(self) -> None:
        from services.turkiye_fund_pdf_text import unwrap_kap_file_bytes

        pdf = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF"
        wrapped = b"\xac\xed\x00\x05ur\x00\x02[B" + b"xxxx" + pdf
        self.assertEqual(unwrap_kap_file_bytes(wrapped)[:8], b"%PDF-1.7")
        self.assertEqual(unwrap_kap_file_bytes(pdf)[:8], b"%PDF-1.7")

    def test_kap_rsc_identity_and_documents(self) -> None:
        from services.turkiye_fund_kap_rsc import parse_kap_bildirim_rsc, parse_kap_ozet_rsc

        ozet = (
            '"generalInfo":{"objId":"abc","fundType":"SYF","fundName":"BV PORTFÖY ALTIN KATILIM FONU",'
            '"mkkMemberOid":"m1","title":"BV PORTFÖY YÖNETİMİ A.Ş.","fundCode":"BAI","fundId":1},'
            '"fundDocuments":{"IZAHNAME":[{"fileOid":"oid-izah","disclosureIndex":1,"fileName":"izah.pdf",'
            '"extension":"pdf"}],"BILGI_FORMU":[{"fileOid":"oid-ybf","disclosureIndex":2,'
            '"fileName":"ybf.pdf","extension":"pdf"}]}'
        )
        parsed = parse_kap_ozet_rsc(ozet)
        self.assertEqual(parsed["fund_code"], "BAI")
        self.assertEqual(parsed["ybf_file_oid"], "oid-ybf")
        self.assertTrue(parsed["resolved"])
        nested = (
            ozet
            + '"children":"Fonun Bağlı Olduğu Şemsiye Fonun Türü"}],["$","div",null,{"children":["$","p",null,'
            '{"className":"x","children":"Katılım Şemsiye Fonu"}]}'
        )
        nested_parsed = parse_kap_ozet_rsc(nested)
        self.assertEqual(
            nested_parsed["ozet_fields"]["Fonun Bağlı Olduğu Şemsiye Fonun Türü"],
            "Katılım Şemsiye Fonu",
        )
        bildirim = parse_kap_bildirim_rsc(
            '{"attachments":[{"objId":"4028328d9f52dddd019fd289d7530906","fileName":"BAI_2026.07.pdf","fileExtension":"pdf"}]}'
        )
        self.assertEqual(bildirim["file_oid"], "4028328d9f52dddd019fd289d7530906")

    def test_retry_backoff_and_cache_reuse(self) -> None:
        from urllib.error import URLError

        from services.turkiye_fund_source_capture import OfficialCaptureSession, cache_identity, load_or_store

        attempts = {"n": 0}

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"ok": true}'

        def opener(request, timeout=0):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise URLError("temp")
            return _Resp()

        sleeps: list[float] = []
        session = OfficialCaptureSession(live=True, opener=opener, sleep=sleeps.append, min_gap_sec=0)
        payload = session.http_json("https://www.kap.org.tr/tr/api/disclosure/funds/byCriteria", {"x": 1})
        self.assertEqual(payload["ok"], True)
        self.assertEqual(attempts["n"], 3)
        self.assertEqual(session.stats.retry_count, 2)
        key = cache_identity(kind="broad_retry", key=str(uuid.uuid4()))
        first, hit1 = load_or_store(kind="broad_retry", key=key, fetcher=lambda: {"n": 1})
        second, hit2 = load_or_store(kind="broad_retry", key=key, fetcher=lambda: {"n": 9})
        self.assertFalse(hit1)
        self.assertTrue(hit2)
        self.assertEqual(first["n"], second["n"])

    def test_resumability_skips_unchanged_pack(self) -> None:
        from services.turkiye_fund_broad_capture import _pack_is_reusable
        from services.turkiye_fund_universe_contract import TEFAS_STATUS_ACTIVE, TurkiyeFundUniverseIdentity

        identity = TurkiyeFundUniverseIdentity(
            fund_code="BAI",
            fund_name="BV PORTFÖY ALTIN KATILIM FONU",
            isin=None,
            founder="BV PORTFÖY",
            tefas_status=TEFAS_STATUS_ACTIVE,
            kap_disclosure_index=1,
        )
        reusable = {
            "fund_code": "BAI",
            "identity_status": "RESOLVED",
            "documents": {"BILGI_FORMU": {"file_oid": "oid"}},
            "kap_disclosure_index": 1,
            "production_persist": False,
            "evidence_recovery_version": 8,
        }
        self.assertTrue(_pack_is_reusable(reusable, identity))
        frozen = {
            "fund_code": "AIS",
            "identity_status": "RESOLVED",
            "production_persist": False,
            "evidence_recovery_version": 8,
            "pilot_frozen": True,
            "review_reasons": [],
        }
        ais = TurkiyeFundUniverseIdentity(
            fund_code="AIS",
            fund_name="AK PORTFÖY KISA VADELİ KİRA SERTİFİKALARI KATILIM FONU",
            isin=None,
            founder="AK PORTFÖY",
            tefas_status=TEFAS_STATUS_ACTIVE,
        )
        self.assertTrue(_pack_is_reusable(frozen, ais))
        failed = {**reusable, "review_reasons": ["SOURCE_ERROR"]}
        self.assertFalse(_pack_is_reusable(failed, identity))

    def test_broad_universe_scanner_without_live_fetch(self) -> None:
        result = run_turkiye_fund_scanner(persist=False, sample_only=False, evidence_packs={})
        self.assertGreaterEqual(result.discovered_count, 200)
        self.assertGreaterEqual(result.active_count, 200)
        self.assertLess(result.active_count, result.discovered_count)
        by_code = {row.fund_code: row for row in result.rows}
        for code, (score, state) in FROZEN.items():
            self.assertEqual(by_code[code].fi_score, score)
            self.assertEqual(by_code[code].fi_state, state)
            self.assertEqual(by_code[code].scanner_status, SCANNER_READY)
        self.assertGreaterEqual(result.scanner_ready_count, 3)
        self.assertTrue(result.coverage_funnel.get("gates"))
        self.assertGreater(result.review_required_count, 0)
        self.assertTrue(result.review_reason_counts)
        self.assertEqual(result.eight_e_calls, 0)
        self.assertEqual(result.new_money_calls, 0)
        self.assertEqual(result.production_writes, ())
        self.assertFalse(result.persist)
        self.assertNotIn("allocate_new_money", SCANNER.read_text(encoding="utf-8"))

    def test_participation_hard_gate_not_loosened(self) -> None:
        from services.official_kap_fund import parse_kap_ybf_text
        from services.turkiye_fund_evidence_extract import extract_governance_excerpts, governance_uygun_tokens_present

        name_only = evaluate_turkiye_fund_participation(
            "BAI",
            name_only=True,
            official_name="BV PORTFÖY ALTIN KATILIM FONU",
        )
        self.assertEqual(name_only.participation_status, PARTICIPATION_STATUS_KONTROL_ET)
        captured = extract_governance_excerpts("Katılım Esasları ve faizsiz finans ilkeleri uygulanır.")
        self.assertTrue(captured)
        self.assertFalse(governance_uygun_tokens_present(captured))
        ybf = parse_kap_ybf_text("Fon portföyü altın ve kıymetli maden yatırım araçlarından oluşur. Fon sepeti değildir.")
        self.assertTrue(ybf["precious_metals_mandate"])
        self.assertFalse(ybf["mixed_mandate"])

    def test_no_forced_reconciliation_or_paid_api(self) -> None:
        from services.turkiye_fund_source_capture import PAID_HOST_BLOCKLIST, assert_official_host

        ais = try_load_captured_pdr_holdings("AIS")
        self.assertIsNotNone(ais)
        self.assertFalse(ais.weights.renormalized)
        with self.assertRaises(ValueError):
            assert_official_host("https://financialmodelingprep.com/x")
        self.assertIn("yahoo", PAID_HOST_BLOCKLIST)

    def test_mixed_and_real_estate_profiles_defined_before_scores(self) -> None:
        from services.fund_intelligence_engine import weights_for_profile
        from services.fund_product_contract import (
            MIXED_MULTI_ASSET_PARTICIPATION_FUND_WEIGHTS,
            PROFILE_MIXED_MULTI_ASSET_PARTICIPATION_FUND,
            PROFILE_REAL_ESTATE_PARTICIPATION_FUND,
            REAL_ESTATE_PARTICIPATION_FUND_WEIGHTS,
        )

        self.assertAlmostEqual(sum(MIXED_MULTI_ASSET_PARTICIPATION_FUND_WEIGHTS.values()), 1.0)
        self.assertAlmostEqual(sum(REAL_ESTATE_PARTICIPATION_FUND_WEIGHTS.values()), 1.0)
        self.assertEqual(
            weights_for_profile(PROFILE_MIXED_MULTI_ASSET_PARTICIPATION_FUND),
            dict(MIXED_MULTI_ASSET_PARTICIPATION_FUND_WEIGHTS),
        )
        self.assertEqual(
            weights_for_profile(PROFILE_REAL_ESTATE_PARTICIPATION_FUND),
            dict(REAL_ESTATE_PARTICIPATION_FUND_WEIGHTS),
        )

    def test_adviser_rank_is_not_a_buy(self) -> None:
        narrative = format_scanner_adviser_narrative(self._scanner_result())
        self.assertIn("canonical Fund Intelligence", narrative)
        self.assertNotIn("Buy this fund", narrative)

    def _scanner_result(self):
        return run_turkiye_fund_scanner(persist=False, sample_only=True)


class TurkiyeFund6OfficialRecoveryTests(unittest.TestCase):
    def test_kap_html_before_ocr(self) -> None:
        from services.turkiye_fund_text_recovery import LAYER_NOTIFICATION_HTML, recover_official_document_text

        ocr_calls = {"n": 0}

        class _Session:
            def http_get_text(self, url, **kwargs):
                return (
                    "<html><body>Bu fon, katılım fonu statüsündedir. "
                    "Danışma Komitesi kararları bağlayıcıdır.</body></html>"
                )

            def kap_rsc(self, url):
                return '{"attachments":[]}'

            def http_get_bytes(self, *args, **kwargs):
                raise AssertionError("file download should not run when HTML body exists")

        recovered = recover_official_document_text(
            _Session(),
            file_oid="oid",
            disclosure_index="1627340",
            document_type="YBF",
            ocr_fn=lambda _img: ocr_calls.__setitem__("n", ocr_calls["n"] + 1) or "x",
        )
        self.assertEqual(recovered["source_layer"], LAYER_NOTIFICATION_HTML)
        self.assertTrue(recovered["text_available"])
        self.assertEqual(ocr_calls["n"], 0)
        self.assertEqual(recovered["notification_id"], "1627340")

        title_only = recover_official_document_text(
            type(
                "S",
                (),
                {
                    "http_get_text": lambda self, url, **k: (
                        "<html><title>BV PORTFÖY ALTIN KATILIM FONU</title>"
                        "<body>Yatırımcı Bilgi Formu Kira Sertifikaları Katılım Fonu</body></html>"
                    ),
                    "kap_rsc": lambda self, url: "{}",
                    "http_get_bytes": lambda self, *a, **k: b"%PDF-1.4 empty",
                },
            )(),
            file_oid="oid",
            disclosure_index="1627340",
            document_type="YBF",
            ocr_fn=lambda _img: "should-not-count-title",
            allow_ocr=False,
        )
        self.assertNotEqual(title_only.get("source_layer"), LAYER_NOTIFICATION_HTML)
        self.assertFalse(title_only.get("text_available"))

    def test_spaced_ybf_layout_still_extracts_mandate_facts(self) -> None:
        from services.official_kap_fund import parse_kap_ybf_text
        from services.turkiye_fund_evidence_extract import extract_mandate_excerpts

        spaced = (
            "Bu    fon,    katılım     fonu     statüsündedir. "
            "Fon portföyünün              en              az              %80’i              "
            "devamlı              olarak              yerli              kira              "
            "olduğu günlerde saat 13:30 sertifikalarına (sukuk) yatırılacaktır."
        )
        facts = parse_kap_ybf_text(spaced)
        self.assertTrue(facts["katilim_fonu_status"])
        self.assertTrue(facts["min_80_kira_sertifikasi"])
        excerpts = extract_mandate_excerpts(spaced)
        self.assertTrue(any("katılım fonu statüsündedir" in item.casefold() for item in excerpts))

    def test_image_only_pdf_ocr_last_resort(self) -> None:
        from services.turkiye_fund_ocr import TEXT_ORIGIN_OCR, ocr_official_pdf
        from services.turkiye_fund_text_recovery import LAYER_NOTIFICATION_HTML, recover_official_document_text
        import services.turkiye_fund_ocr as ocr_mod
        import services.turkiye_fund_text_recovery as recovery_mod

        html_only = recover_official_document_text(
            type("S", (), {
                "http_get_text": lambda self, url, **k: "<html>Yatırımcı Bilgi Formu</html>",
                "kap_rsc": lambda self, url: "{}",
                "http_get_bytes": lambda self, *a, **k: b"%PDF-1.4 empty",
            })(),
            file_oid="oid",
            disclosure_index="1",
            document_type="YBF",
            ocr_fn=lambda _img: "should-not-run-on-wrapper-html-if-file-fails",
            allow_ocr=False,
        )
        self.assertNotEqual(html_only.get("source_layer"), LAYER_NOTIFICATION_HTML)

        original = ocr_mod.extract_pdf_images
        ocr_mod.extract_pdf_images = lambda payload, max_images=24: [b"fake-image"]
        recovery_mod.ocr_official_pdf = ocr_official_pdf
        try:
            text, origin = ocr_official_pdf(b"%PDF", ocr_fn=lambda _img: "Danışma Kurulu icazet belgesi")
        finally:
            ocr_mod.extract_pdf_images = original
        self.assertEqual(origin, TEXT_ORIGIN_OCR)
        self.assertIn("Danışma Kurulu", text or "")

    def test_document_version_not_mixed(self) -> None:
        from services.turkiye_fund_text_recovery import recover_official_document_text

        class _Session:
            def http_get_text(self, url, **kwargs):
                if "111" in url:
                    return (
                        "<html><body>Bu fon, katılım fonu statüsündedir v1. "
                        "Portföy yönetiminde katılım prensiplerine uygunluk esastır.</body></html>"
                    )
                return (
                    "<html><body>Bu fon, katılım fonu statüsündedir v2. "
                    "Danışma Komitesi kararları bağlayıcıdır.</body></html>"
                )

            def kap_rsc(self, url):
                return "{}"

            def http_get_bytes(self, *args, **kwargs):
                raise AssertionError("unused")

        first = recover_official_document_text(
            _Session(), file_oid="a", disclosure_index="111", document_type="YBF"
        )
        second = recover_official_document_text(
            _Session(), file_oid="b", disclosure_index="222", document_type="IZAHNAME"
        )
        self.assertNotEqual(first["notification_id"], second["notification_id"])
        self.assertNotEqual(first["text_hash"], second["text_hash"])
        self.assertIn("v1", first["text"])
        self.assertIn("v2", second["text"])

    def test_official_tefas_periyod_contract_and_no_fabricated_history(self) -> None:
        from services.turkiye_fund_tefas_history import (
            HISTORY_SOURCE_UNAVAILABLE,
            TEFAS_HISTORY_PERIOD_1Y,
            capture_tefas_history,
            normalize_tefas_history_rows,
            tefas_history_payload,
        )

        payload = tefas_history_payload("BAI", periyod=TEFAS_HISTORY_PERIOD_1Y)
        self.assertEqual(payload, {"fonKodu": "BAI", "dil": "TR", "periyod": 12})
        self.assertNotIn("baslangicTarihi", payload)
        rows = normalize_tefas_history_rows(
            [
                {"fonKodu": "BAI", "tarih": "2026-08-28", "fiyat": 1.0},
                {"fonKodu": "BAI", "tarih": "2026-08-31", "fiyat": 1.01},
            ],
            fund_code="BAI",
            source_as_of="2026-08-31",
            capture_time="2026-08-31T00:00:00+00:00",
        )
        self.assertEqual([row["tarih"] for row in rows], ["2026-08-28", "2026-08-31"])
        self.assertNotIn("2026-08-29", [row["tarih"] for row in rows])
        self.assertNotIn("2026-08-30", [row["tarih"] for row in rows])

        class _Session:
            stats = None
            tefas_warmed = False
            posts = []

            def http_get_text(self, url, **kwargs):
                self.tefas_warmed = True
                return "<html>tefas</html>"

            def http_json(self, url, payload, **kwargs):
                self.posts.append((url, dict(payload), dict(kwargs)))
                return {"errorMessage": "Sistem Hatası!!", "resultList": None}

        failed = capture_tefas_history(_Session(), "ZZZ", force=True)
        self.assertFalse(failed["available"])
        self.assertTrue(failed["error"])
        self.assertEqual(failed["rows"], [])

    def test_incremental_history_cache(self) -> None:
        from services.turkiye_fund_source_capture import load_or_store
        from services.turkiye_fund_tefas_history import rows_content_identity

        rows = [{"fonKodu": "QQQ", "tarih": "2026-08-31", "fiyat": 1.0, "source": "TEFAS"}]
        digest = rows_content_identity(rows)
        unique = f"QQQ-unit-test-cache-{uuid.uuid4()}"
        first, hit1 = load_or_store(
            kind="tefas_prices_period",
            key=unique,
            fetcher=lambda: {"available": True, "rows": rows, "latest_date": "2026-08-31", "content_identity": digest},
        )
        second, hit2 = load_or_store(
            kind="tefas_prices_period",
            key=unique,
            fetcher=lambda: {"available": True, "rows": [], "latest_date": "2099-01-01"},
        )
        self.assertFalse(hit1)
        self.assertTrue(hit2)
        self.assertEqual(first["latest_date"], second["latest_date"])

    def test_no_title_only_uygun_and_participation_freeze(self) -> None:
        name_only = evaluate_turkiye_fund_participation(
            "BAI",
            name_only=True,
            official_name="BV PORTFÖY ALTIN KATILIM FONU",
        )
        self.assertEqual(name_only.participation_status, PARTICIPATION_STATUS_KONTROL_ET)
        by_code = {row.fund_code: row for row in run_turkiye_fund_scanner(persist=False, sample_only=True).rows}
        for code, (score, state) in FROZEN.items():
            self.assertEqual(by_code[code].fi_score, score)
            self.assertEqual(by_code[code].fi_state, state)

    def test_zero_eight_e_new_money_paid_and_persist(self) -> None:
        result = run_turkiye_fund_scanner(persist=False, sample_only=False, evidence_packs={})
        self.assertEqual(result.eight_e_calls, 0)
        self.assertEqual(result.new_money_calls, 0)
        self.assertEqual(result.trades, 0)
        self.assertEqual(result.portfolio_writes, 0)
        self.assertEqual(result.production_writes, ())
        with self.assertRaises(ValueError):
            run_turkiye_fund_scanner(persist=True)
        capture = Path("services/turkiye_fund_broad_capture.py").read_text(encoding="utf-8")
        history = Path("services/turkiye_fund_tefas_history.py").read_text(encoding="utf-8")
        recovery = Path("services/turkiye_fund_text_recovery.py").read_text(encoding="utf-8")
        blob = capture + history + recovery
        self.assertNotIn("allocate_new_money", blob)
        self.assertNotIn("evaluate_official_fund_decision", blob)
        self.assertNotIn("financialmodelingprep", blob)
        self.assertIn("periyod", history)
        self.assertNotIn("baslangicTarihi", history)
        self.assertNotIn("baslangicTarihi", capture)

    def test_representative_sample_includes_multi_asset(self) -> None:
        from services.turkiye_fund_universe_discovery import DISCOVERY_MULTI_ASSET, select_representative_sample

        source = Path("services/turkiye_fund_universe_discovery.py").read_text(encoding="utf-8")
        self.assertIn("DISCOVERY_MULTI_ASSET", source)
        self.assertIn(DISCOVERY_MULTI_ASSET, source)


if __name__ == "__main__":
    unittest.main()
