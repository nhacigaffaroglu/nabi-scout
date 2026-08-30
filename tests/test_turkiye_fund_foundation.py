from __future__ import annotations

import unittest
from pathlib import Path

from services.fund_intelligence_engine import evaluate_official_fund_intelligence
from services.fund_product_contract import (
    FUND_TYPE_MUTUAL,
    IDENTITY_RESOLVED,
    IDENTITY_UNRESOLVED,
    PILOT_FUND_SYMBOLS,
    PILOT_TEFAS_FUND_CODES,
    PROFILE_PARTICIPATION_EQUITY,
    PROFILE_SHORT_TERM_PARTICIPATION,
    PROFILE_SUKUK_LEASE_CERTIFICATE,
    PROVIDER_TEFAS,
    TEFAS_PRICE_FIELD,
    TEFAS_PRICE_SEMANTICS,
)
from services.official_kap_fund import (
    match_tefas_kap_identity,
    official_profile_from_kap,
    parse_kap_mandate,
    parse_kap_ozet_html,
    parse_kap_ybf_text,
)
from services.official_sp_funds_product import (
    TefasFundProductProvider,
    assert_provider_surface,
    default_official_sp_funds_provider,
)
from services.official_tefas import parse_tefas_price_history
from services.official_tefas_product import default_tefas_fund_provider
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN

TEFAS_SRC = Path("services/official_tefas_product.py")
KAP_SRC = Path("services/official_kap_fund.py")
BIST = Path("services/bist_refresh_contract.py")
FOUNDATION = Path("services/official_sp_funds_product.py")


class TurkiyeFundFoundationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = default_tefas_fund_provider()

    def test_tefas_provider_surface_and_pilots(self) -> None:
        self.assertEqual(self.provider.provider_id, PROVIDER_TEFAS)
        self.assertEqual(
            assert_provider_surface(self.provider),
            assert_provider_surface(default_official_sp_funds_provider()),
        )
        for code in PILOT_TEFAS_FUND_CODES:
            self.assertTrue(self.provider.supports(code))
        self.assertFalse(self.provider.supports("SPUS"))
        self.assertFalse(self.provider.supports("ASELS"))
        self.assertFalse(self.provider.supports("AAPL"))

    def test_identity_is_code_only(self) -> None:
        self.assertEqual(
            match_tefas_kap_identity(tefas_code="AIS", kap_code="AIS"),
            IDENTITY_RESOLVED,
        )
        self.assertEqual(
            match_tefas_kap_identity(
                tefas_code="AIS",
                kap_code="ZPE",
                tefas_name="AK PORTFÖY PARA PİYASASI KATILIM FONU",
                kap_name="AK PORTFÖY PARA PİYASASI KATILIM FONU",
            ),
            IDENTITY_UNRESOLVED,
        )
        self.assertEqual(
            match_tefas_kap_identity(tefas_code="", kap_code="AIS", tefas_name="same", kap_name="same"),
            IDENTITY_UNRESOLVED,
        )
        for code in PILOT_TEFAS_FUND_CODES:
            identity = self.provider.turkiye_identity(code)
            self.assertEqual(identity.fund_code, code)
            self.assertEqual(identity.identity_status, IDENTITY_RESOLVED)
            self.assertEqual(identity.currency, "TRY")
            self.assertTrue(identity.founder)

    def test_kap_ozet_and_ybf_parsing(self) -> None:
        html = (
            "<h3>Kurucunun Ünvanı</h3><div>AK PORTFÖY YÖNETİMİ A.Ş.</div>"
            "<h3>Fonun Bağlı Olduğu Şemsiye Fonun Türü</h3><div>Katılım</div>"
        )
        pairs = parse_kap_ozet_html(html)
        self.assertEqual(pairs["Kurucunun Ünvanı"], "AK PORTFÖY YÖNETİMİ A.Ş.")
        self.assertEqual(pairs["Fonun Bağlı Olduğu Şemsiye Fonun Türü"], "Katılım")
        ybf = parse_kap_ybf_text(
            "ISIN KODU: TRYAKBK00847\n"
            "Bu fon, katılım fonu statüsündedir.\n"
            "Fon katılma payı alım satımının yapılacağı para birimi TL’dir.\n"
            "vadesine en fazla 184 gün kalmış\n"
            "ağırlıklı ortalama vadesi 45 günü aşamaz\n"
            "Yönetim ücreti (yıllık)\n0,85\n"
        )
        self.assertEqual(ybf["isin"], "TRYAKBK00847")
        self.assertTrue(ybf["katilim_fonu_status"])
        self.assertEqual(ybf["currency"], "TRY")
        self.assertTrue(ybf["max_maturity_184"])

    def test_profile_from_official_mandate_not_name(self) -> None:
        self.assertIsNone(
            official_profile_from_kap(
                umbrella_type="Katılım",
                ybf={"max_maturity_184": False, "avg_maturity_45": False},
            )
        )
        self.assertEqual(
            official_profile_from_kap(
                umbrella_type="Serbest",
                ybf={"max_maturity_184": True, "avg_maturity_45": True},
            ),
            PROFILE_SHORT_TERM_PARTICIPATION,
        )
        ais = self.provider.kap_mandate("AIS")
        zpe = self.provider.kap_mandate("ZPE")
        iat = self.provider.kap_mandate("IAT")
        self.assertEqual(ais.official_profile, PROFILE_SHORT_TERM_PARTICIPATION)
        self.assertEqual(zpe.official_profile, PROFILE_PARTICIPATION_EQUITY)
        self.assertEqual(iat.official_profile, PROFILE_SUKUK_LEASE_CERTIFICATE)
        self.assertIn("184", ais.strategy_text or "")
        self.assertIn("BIST Katılım 100", zpe.strategy_text or "")
        self.assertIn("kira sertifikaları", iat.strategy_text or "")

    def test_basic_official_facts(self) -> None:
        facts = self.provider.facts("AIS")
        self.assertEqual(facts.fund_type, FUND_TYPE_MUTUAL)
        self.assertEqual(facts.nav, 0.108262)
        self.assertEqual(facts.net_assets, 14882213853.66)
        self.assertEqual(self.provider.investor_count("AIS"), 21763)
        self.assertEqual(self.provider.official_risk_value("AIS"), "1")
        self.assertEqual(self.provider.official_risk_value("ZPE"), "6")
        self.assertEqual(facts.currency, "TRY")
        self.assertEqual(facts.expense_ratio, 0.85)
        self.assertIn("sonFiyat", facts.raw_fields)
        self.assertIn("yatirimciSayi", facts.raw_fields)
        self.assertIn("riskDegeri", facts.raw_fields)

    def test_price_history_duplicates_and_gaps(self) -> None:
        series = parse_tefas_price_history(
            [
                {"fonKodu": "AIS", "fonUnvan": "X", "tarih": "2026-08-26", "fiyat": 1.0},
                {"fonKodu": "AIS", "fonUnvan": "X", "tarih": "2026-08-26", "fiyat": 1.1},
                {"fonKodu": "AIS", "fonUnvan": "X", "tarih": "2026-08-28", "fiyat": 1.2},
            ],
            fund_code="AIS",
            period_months=1,
        )
        self.assertEqual(series.price_field, TEFAS_PRICE_FIELD)
        self.assertEqual(series.price_semantics, TEFAS_PRICE_SEMANTICS)
        self.assertEqual(series.duplicate_dates, ("2026-08-26",))
        self.assertIn("2026-08-27", series.missing_dates)
        self.assertEqual(series.observation_count, 3)
        live = self.provider.price_history("AIS", period_months=1)
        self.assertGreaterEqual(live.observation_count, 20)
        self.assertEqual(live.duplicate_dates, ())
        year = self.provider.price_history("ZPE", period_months=12)
        self.assertGreaterEqual(year.observation_count, 200)
        self.assertEqual(year.first_date, "2025-08-28")
        self.assertEqual(year.last_date, "2026-08-28")

    def test_participation_evidence_uses_official_methodology(self) -> None:
        for code in PILOT_TEFAS_FUND_CODES:
            evidence = self.provider.sharia_evidence(code)
            self.assertTrue(evidence.official_mandate_present)
            self.assertEqual(evidence.participation_status, PARTICIPATION_STATUS_UYGUN)
            self.assertIn("NO_INVENTED_UYGUN", evidence.limitations)
            self.assertIsNone(self.provider.purification_evidence(code).latest_factor_pct)

    def test_portfolio_report_discovery(self) -> None:
        ais = self.provider.portfolio_report_audit("AIS")
        self.assertTrue(ais.asset_weights)
        self.assertTrue(ais.holdings)
        self.assertTrue(ais.issuer)
        self.assertTrue(ais.maturity)
        self.assertTrue(ais.currency)
        self.assertFalse(ais.country)
        self.assertFalse(ais.lookthrough)
        self.assertIn("ISIN KODU", ais.exact_fields)
        self.assertIn("1644043", ais.latest_report_url or "")
        zpe = self.provider.portfolio_report_audit("ZPE")
        self.assertIn("1646036", zpe.latest_report_url or "")
        self.assertNotIn("NO_HOLDINGS_PARSER", zpe.limitations)

    def test_no_eight_e_or_new_money(self) -> None:
        source = TEFAS_SRC.read_text(encoding="utf-8")
        self.assertNotIn("evaluate_official_fund_decision", source)
        self.assertNotIn("allocate_new_money", source)
        facts = self.provider.facts("AIS")
        self.assertIn("NO_EIGHT_E", facts.limitations)
        self.assertIn("NO_NEW_MONEY", facts.limitations)
        self.assertNotIn("NO_FUND_INTELLIGENCE_SCORE", facts.limitations)

    def test_sp_funds_isolation(self) -> None:
        sp = default_official_sp_funds_provider()
        for symbol in PILOT_FUND_SYMBOLS:
            self.assertTrue(sp.supports(symbol))
            self.assertFalse(self.provider.supports(symbol))
        evaluation = evaluate_official_fund_intelligence("SPUS")
        self.assertEqual(evaluation.score, 71.41)
        spsk = evaluate_official_fund_intelligence("SPSK")
        self.assertEqual(spsk.score, 65.87)
        spre = evaluate_official_fund_intelligence("SPRE")
        self.assertEqual(spre.score, 47.57)
        spwo = evaluate_official_fund_intelligence("SPWO")
        self.assertEqual(spwo.score, 52.79)

    def test_bist_and_us_equity_isolation(self) -> None:
        self.assertTrue(BIST.is_file())
        self.assertIn("ASELS", BIST.read_text(encoding="utf-8"))
        self.assertNotIn("FMPClient", TEFAS_SRC.read_text(encoding="utf-8"))
        self.assertNotIn("DATABASE_URL", KAP_SRC.read_text(encoding="utf-8"))
        self.assertNotIn("FMPClient", FOUNDATION.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
