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
    PROFILE_LIQUIDITY_PARTICIPATION_FUND,
    PROFILE_MIXED_MULTI_ASSET_PARTICIPATION,
    PROFILE_MIXED_MULTI_ASSET_PARTICIPATION_FUND,
    PROFILE_PRECIOUS_METALS_PARTICIPATION,
    PROFILE_SHORT_TERM_PARTICIPATION,
    PROFILE_SUKUK_LEASE_CERTIFICATE,
    PROVIDER_TEFAS,
    TEFAS_PRICE_FIELD,
    TEFAS_PRICE_SEMANTICS,
)
from services.official_kap_fund import (
    match_tefas_kap_identity,
    official_fi_profile_from_general_strategy,
    official_profile_from_kap,
    _explicit_min_80_kira_sertifikasi,
    participation_holdings_profile_from_kap_fund10,
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
from services.official_tefas_product import (
    TefasFundProductProvider as OfficialTefasFundProductProvider,
    default_tefas_fund_provider,
)
from services.turkiye_fund_kap_rsc import (
    kap_genel_investment_strategy,
    parse_kap_genel_rsc,
)
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.official_turkiye_fund_participation import _explicit_governance, _explicit_mandate

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
        self.assertEqual(ybf["management_fee_annual_pct"], 0.85)

    def test_kap_ybf_management_fee_prefers_direct_official_value(self) -> None:
        direct = parse_kap_ybf_text(
            "Fon’dan Karşılanan Giderler (yıllık) % "
            "Yönetim Ücreti 3,20 - Kurucu/Yönetici (Asgari %35, azami %65)"
        )
        self.assertEqual(direct["management_fee_annual_pct"], 3.20)

        allocation_after_split = parse_kap_ybf_text(
            "Yönetim ücreti (yıllık) "
            "- Kurucu/Yönetici Asgari %35, azami %65 1,10 "
            "- Fon Dağıtım Kuruluşu"
        )
        self.assertEqual(
            allocation_after_split["management_fee_annual_pct"],
            1.10,
        )

        two_row_allocation = parse_kap_ybf_text(
            "Yönetim ücreti (yıllık) "
            "- Kurucu/Yönetici Asgari %35, azami %65 "
            "- Fon Dağıtım Kuruluşu : Asgari %35, azami %65 "
            "1,00 Saklama ücreti 0,05"
        )
        self.assertEqual(
            two_row_allocation["management_fee_annual_pct"],
            1.00,
        )

        interleaved_columns = parse_kap_ybf_text(
            "Yönetim ücreti (yıllık) "
            "Kurucu %35 (En az) 2,25 riski, likidite riski"
        )
        self.assertEqual(
            interleaved_columns["management_fee_annual_pct"],
            2.25,
        )

        percent_prefixed_fee = parse_kap_ybf_text(
            "Yönetim ücreti (yıllık) Kurucu piyasa "
            "(Asgari %35, azami %65) ile Fon %3,20 "
            "kaynaklanabilecek riskleri"
        )
        self.assertEqual(
            percent_prefixed_fee["management_fee_annual_pct"],
            3.20,
        )

        integer_fee_before_custody = parse_kap_ybf_text(
            "Fon’dan karşılanan giderler % "
            "Yönetim ücreti (yıllık) temel yatırım riskleri "
            "Kurucu ile Dağıtıcı Kuruluş arasında 1 "
            "maruz kalabileceği temel riskler "
            "Asgari %35-Azami %65 oranında paylaştırılır. "
            "Portföy Saklayıcısı 0,08 Diğer Giderler 0,20"
        )
        self.assertEqual(
            integer_fee_before_custody["management_fee_annual_pct"],
            1.0,
        )

        trailing_page_number = parse_kap_ybf_text(
            "Yıllık Azami Fon Toplam Gider Oranı 3,65 "
            "Yönetim Ücreti (Yıllık) 3,00 Saklama Ücreti 0,12 "
            "Bu form 20/07/2026 tarihi itibarıyla günceldir. 2"
        )
        self.assertEqual(trailing_page_number["management_fee_annual_pct"], 3.00)

        distributor_split_only = parse_kap_ybf_text(
            "Yönetim ücreti (yıllık) Kurucu/Yönetici Asgari %35, azami %65"
        )
        self.assertIsNone(distributor_split_only["management_fee_annual_pct"])

    def test_explicit_participation_fund_type_profiles(self) -> None:
        money_market = parse_kap_ybf_text(
            "Bu fon, para piyasası katılım fonudur."
        )
        self.assertTrue(money_market["money_market_participation"])
        self.assertEqual(
            official_profile_from_kap(
                umbrella_type="Serbest",
                ybf=money_market,
            ),
            PROFILE_SHORT_TERM_PARTICIPATION,
        )

        short_term = parse_kap_ybf_text(
            "Bu fon, kısa vadeli katılım serbest fondur."
        )
        self.assertTrue(short_term["short_term_participation"])
        self.assertEqual(
            official_profile_from_kap(
                umbrella_type="Serbest",
                ybf=short_term,
            ),
            PROFILE_SHORT_TERM_PARTICIPATION,
        )

        # Umbrella alone must never create a profile.
        self.assertIsNone(
            official_profile_from_kap(
                umbrella_type="Katılım Şemsiye Fonu",
                ybf={},
            )
        )

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


    def test_high_confidence_strategy_profile_overrides_broad_asset_mentions(self) -> None:
        mixed = parse_kap_mandate(
            fund_code="TST",
            ozet_fields={},
            ybf_payload={
                "strategy": (
                    "Fon portföyünde çoklu varlık yönetim modeli benimsenir. "
                    "Portföye kira sertifikaları ve altın işlemleri dahil edilebilir."
                )
            },
        )
        self.assertEqual(mixed.official_profile, PROFILE_MIXED_MULTI_ASSET_PARTICIPATION)

        equity = parse_kap_mandate(
            fund_code="TST",
            ozet_fields={},
            ybf_payload={
                "strategy": (
                    "Bu fon, hisse senedi fonudur. Portföye dahil edilebilecek varlıklar "
                    "faizsiz finans ilkelerine uyumlu finansal varlıklardan ibarettir. "
                    "Kira sertifikaları da portföye alınabilir."
                )
            },
        )
        self.assertEqual(equity.official_profile, PROFILE_PARTICIPATION_EQUITY)

        short_term = parse_kap_mandate(
            fund_code="TST",
            ozet_fields={},
            ybf_payload={
                "strategy": (
                    "Kısa vadeli katılım serbest fon. "
                    "Fon'un portföyünün aylık ağırlıklı ortalama vadesi 25-90 gün olacaktır."
                )
            },
        )
        self.assertEqual(short_term.official_profile, PROFILE_SHORT_TERM_PARTICIPATION)

        precious = parse_kap_mandate(
            fund_code="TST",
            ozet_fields={},
            ybf_payload={
                "strategy": (
                    "Fon toplam değerinin en az %80’i devamlı olarak borsada işlem gören "
                    "altın ve altına dayalı sermaye piyasası araçlarına yatırılır. "
                    "Kalan bölümde kira sertifikaları ve BIST Katılım 100 araçları bulunabilir."
                )
            },
        )
        self.assertEqual(precious.official_profile, PROFILE_PRECIOUS_METALS_PARTICIPATION)

    def test_min_80_semantics_require_explicit_minimum(self) -> None:
        bare_equity = parse_kap_mandate(
            fund_code="TST",
            ozet_fields={},
            ybf_payload={"strategy": "BIST Katılım 100 Endeksi referans alınabilir."},
        )
        self.assertIsNone(bare_equity.official_profile)

        bare_sukuk = parse_kap_mandate(
            fund_code="TST",
            ozet_fields={},
            ybf_payload={"strategy": "Portföyde kira sertifikaları bulunabilir."},
        )
        self.assertIsNone(bare_sukuk.official_profile)

        for prefix in ("en az", "asgari"):
            equity = parse_kap_mandate(
                fund_code="TST",
                ozet_fields={},
                ybf_payload={
                    "strategy": (
                        f"Fon toplam değerinin {prefix} %80'i devamlı olarak "
                        "BIST Katılım 100 Endeksindeki paylara yatırılır."
                    )
                },
            )
            self.assertEqual(
                equity.official_profile,
                PROFILE_PARTICIPATION_EQUITY,
            )

            sukuk = parse_kap_mandate(
                fund_code="TST",
                ozet_fields={},
                ybf_payload={
                    "strategy": (
                        f"Fon toplam değerinin {prefix} %80'i devamlı olarak "
                        "kira sertifikalarına yatırılır."
                    )
                },
            )
            self.assertEqual(
                sukuk.official_profile,
                PROFILE_SUKUK_LEASE_CERTIFICATE,
            )


    def test_participation_holdings_profile_is_fund10_methodology_freeze(self) -> None:
        fi = parse_kap_mandate(
            fund_code="TST",
            ozet_fields={},
            ybf_payload={"strategy": "Portföyde kira sertifikaları bulunabilir."},
        )
        self.assertIsNone(fi.official_profile)

        legacy = participation_holdings_profile_from_kap_fund10(
            umbrella_type="Katılım Şemsiye Fonu",
            ybf_payload={"strategy": "Portföyde kira sertifikaları bulunabilir."},
        )
        self.assertEqual(legacy, PROFILE_SUKUK_LEASE_CERTIFICATE)

        bky_like = participation_holdings_profile_from_kap_fund10(
            umbrella_type="Serbest Şemsiye Fon",
            ybf_text=(
                "Fon toplam değerinin en az %80’i devamlı olarak, T.C. Hazine ve "
                "günlerde 10.30) sonra verilen talimatları ilk pay fiyatı Maliye "
                "Bakanlığı tarafından döviz cinsinden ihraç edilen hesaplamasından "
                "sonra verilmiş olarak kabul edilerek ve kira sertifikaları ile "
                "yerli ihraççıların katılım esasına uygun araçlarına yatırılacaktır."
            ),
        )
        self.assertEqual(bky_like, PROFILE_SUKUK_LEASE_CERTIFICATE)

    def test_min_80_sukuk_tolerates_official_ocr_interleaving(self) -> None:
        bky = (
            "Fon toplam değerinin en az %80’i devamlı olarak, T.C. Hazine ve "
            "günlerde 10.30) sonra verilen talimatları ilk pay fiyatı Maliye "
            "Bakanlığı tarafından döviz cinsinden ihraç edilen hesaplamasından "
            "sonra verilmiş olarak kabul edilerek ve kira sertifikaları ile "
            "yerli ihraççıların katılım esasına uygun araçlarına yatırılacaktır."
        )
        ktn = (
            "Fon toplam değerinin e n az % 80’i - Katılma payı satın almak veya "
            "elden çıkarmak isteyen kamu ve özel sektör tarafından ihraç edilen "
            "kira yatırımcılar, Kurucunun ilan ettiği sertifikalarına yatırılır."
        )
        unrelated = (
            "Fon toplam değerinin en az %80’i ortaklık paylarına yatırılır. "
            "Portföyde kira sertifikaları bulunabilir."
        )

        self.assertTrue(_explicit_min_80_kira_sertifikasi(bky))
        self.assertTrue(_explicit_min_80_kira_sertifikasi(ktn))
        self.assertFalse(_explicit_min_80_kira_sertifikasi(unrelated))

    def test_general_strategy_fi_classifier_is_deliberately_narrow(self) -> None:
        self.assertEqual(
            official_fi_profile_from_general_strategy(
                "Bu fon kısa vadeli katılım fonudur."
            ),
            PROFILE_SHORT_TERM_PARTICIPATION,
        )
        self.assertEqual(
            official_fi_profile_from_general_strategy(
                "Fon türü Kısa Vadeli Katılım Fonu olarak belirlenmiştir."
            ),
            PROFILE_SHORT_TERM_PARTICIPATION,
        )
        self.assertEqual(
            official_fi_profile_from_general_strategy(
                "Portföye vadesine en fazla 184 gün kalmış araçlar alınır ve "
                "ağırlıklı ortalama vadesi 45 günü aşamaz."
            ),
            PROFILE_SHORT_TERM_PARTICIPATION,
        )
        self.assertEqual(
            official_fi_profile_from_general_strategy(
                "Fon portföyünde çoklu varlık yönetim modeli uygulanır."
            ),
            PROFILE_MIXED_MULTI_ASSET_PARTICIPATION,
        )
        for strategy in (
            "BIST Katılım 100 Endeksi referans alınabilir.",
            "Portföyde kira sertifikaları bulunabilir.",
            "Portföyde altın bulunabilir.",
            "Teknoloji payları, kira sertifikaları ve altın birlikte bulunabilir.",
        ):
            self.assertIsNone(
                official_fi_profile_from_general_strategy(strategy)
            )

    def test_kap_genel_strategy_requires_exact_unambiguous_label(self) -> None:
        exact = parse_kap_genel_rsc(
            '"itemName":"Yatırım Stratejisi","itemKey":"strategy","value":"ABC"'
        )
        self.assertEqual(kap_genel_investment_strategy(exact), "ABC")

        unrelated = parse_kap_genel_rsc(
            '"itemName":"Yatırım Stratejisi Notu","itemKey":"strategy","value":"ABC"'
        )
        self.assertIsNone(kap_genel_investment_strategy(unrelated))

        same_key_conflict = parse_kap_genel_rsc(
            '"itemName":"Yatırım Stratejisi","itemKey":"strategy","value":"ABC"'
            '"itemName":"Yatırım Stratejisi","itemKey":"strategy","value":"XYZ"'
        )
        self.assertEqual(same_key_conflict["items"]["strategy"], "ABC")
        self.assertIsNone(kap_genel_investment_strategy(same_key_conflict))

        different_key_conflict = parse_kap_genel_rsc(
            '"itemName":"Yatırım Stratejisi","itemKey":"strategy1","value":"ABC"'
            '"itemName":"Yatırım Stratejisi","itemKey":"strategy2","value":"XYZ"'
        )
        self.assertIsNone(kap_genel_investment_strategy(different_key_conflict))

        duplicate_same_value = parse_kap_genel_rsc(
            '"itemName":"Yatırım Stratejisi","itemKey":"strategy1","value":"ABC"'
            '"itemName":"Yatırım Stratejisi","itemKey":"strategy2","value":"ABC"'
        )
        self.assertEqual(
            kap_genel_investment_strategy(duplicate_same_value),
            "ABC",
        )

    def test_provider_general_strategy_fallback_is_fi_only(self) -> None:
        pack = {
            "fund_code": "TST",
            "identity_status": IDENTITY_RESOLVED,
            "tefas_snapshot": {
                "fonKodu": "TST",
                "fonUnvan": "TEST FONU",
            },
            "tefas_returns": {"fonKodu": "TST"},
            "ozet_fields": {},
            "ybf": {},
            "general_strategy": "Bu fon kısa vadeli katılım fonudur.",
            "genel_url": "https://www.kap.org.tr/tr/fon-bilgileri/genel/tst",
        }
        provider = OfficialTefasFundProductProvider(
            tefas_bundle={"snapshot": {}, "returns": {}},
            kap_bundle={"funds": {}},
            evidence_packs={"TST": pack},
        )

        self.assertTrue(provider.supports("TST"))
        self.assertIsNone(provider.kap_mandate("TST").official_profile)

        fallback = provider.mandate("TST")
        self.assertEqual(
            fallback.vehicle,
            PROFILE_LIQUIDITY_PARTICIPATION_FUND,
        )
        self.assertEqual(fallback.confidence, "MEDIUM")
        self.assertIn(
            "FI_ONLY_KAP_GENERAL_STRATEGY_FALLBACK",
            fallback.limitations,
        )
        self.assertIn("NOT_PARTICIPATION_EVIDENCE", fallback.limitations)
        self.assertEqual(fallback.source_url, pack["genel_url"])
        self.assertIsNone(provider.facts("TST").strategy)

        canonical_pack = {
            **pack,
            "ybf": {
                "strategy": (
                    "Fon portföyünde çoklu varlık yönetim modeli benimsenir."
                )
            },
            "general_strategy": "Bu fon kısa vadeli katılım fonudur.",
        }
        canonical_provider = OfficialTefasFundProductProvider(
            tefas_bundle={"snapshot": {}, "returns": {}},
            kap_bundle={"funds": {}},
            evidence_packs={"TST": canonical_pack},
        )
        canonical = canonical_provider.mandate("TST")
        self.assertEqual(
            canonical.vehicle,
            PROFILE_MIXED_MULTI_ASSET_PARTICIPATION_FUND,
        )
        self.assertEqual(canonical.confidence, "HIGH")
        self.assertNotIn(
            "FI_ONLY_KAP_GENERAL_STRATEGY_FALLBACK",
            canonical.limitations,
        )

    def test_explicit_faizsiz_finans_strategy_is_mandate_evidence(self) -> None:
        self.assertTrue(
            _explicit_mandate((
                "Fon portföyü faizsiz finans ilkelerine uygun para ve sermaye "
                "piyasası araçlarına yatırılacaktır.",
            ))
        )
        self.assertFalse(
            _explicit_mandate((
                "Fon hesabına faizsiz finansman sağlanmasından kaynaklanan giderler.",
            ))
        )

    def test_binding_independent_adviser_is_governance_evidence(self) -> None:
        self.assertTrue(
            _explicit_governance((
                "Uluslararası kabul görmüş faizsiz finans ilkelerine uygunluğunun "
                "belirlenmesinde bağımsız bir danışman kararı aranacak ve bu karar "
                "bağlayıcı olacaktır.",
            ))
        )
        self.assertFalse(
            _explicit_governance((
                "Bağımsız danışmanlık hizmeti alınabilir.",
            ))
        )

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


from services.official_kap_pdr import (
    ASSET_GROUP_FUND,
    ASSET_GROUP_PARTICIPATION_ACCOUNT,
    KapPdrError,
    parse_kap_pdr_text,
)


def test_pdr_recovers_embedded_complete_equity_row_without_residual_fill():
    text = """
III-FON PORTFÖY DEĞERİ
HİSSE SENETLERİ
KİMYA SANAYİ VE TREMRCN00023 TİCARET A.Ş. ORGE TL ORGE TREORGE00011 25.000,00 19,498977 21/08/26 80100511 24,020000 600.500,00 11,08 5,18 5,28 ENERJİ
RGYAS TL RÖNESAN 2.600,00 153,436385 04/08/26 80100511 215,400000 560.040,00 10,34 4,83 4,92
IV-FON TOPLAM DEĞERİ TABLOSU
"""
    parsed = parse_kap_pdr_text(
        text,
        fund_code="TST",
        report_period="2026-08",
    )
    weights = [
        row.portfolio_weight
        for row in parsed.holdings
        if row.portfolio_weight is not None
    ]
    assert 5.28 in weights
    assert 4.92 in weights


def test_pdr_recovers_complete_physical_fund_row():
    text = """
III-FON PORTFÖY DEĞERİ
YATIRIM FONU
ZGOLD - ZİRAAT TL ZİRAAT 6.880,00 653,216500 31/08/26 80100103 713,000000 4.905.440,00 10,30 4,14 4,49
IV-FON TOPLAM DEĞERİ TABLOSU
"""
    parsed = parse_kap_pdr_text(
        text,
        fund_code="TST",
        report_period="2026-08",
    )
    assert any(
        row.asset_group == ASSET_GROUP_FUND
        and row.portfolio_weight == 4.49
        for row in parsed.holdings
    )


def test_pdr_recovers_clean_ocr_participation_account_row():
    text = """
III-FON PORTFÖY DEĞERİ
MEVcUAT
VAcEgI T FINANS KATIgIM BANKASI 01.09.2026 VAcEgI 36.50% 11,681,670.00 11,670,000.00 31.08.2026 0.00% 0 0 0 11,681,670.00 33.33% 2.96%
IV-FON TOPLAM DEĞERİ TABLOSU
"""
    parsed = parse_kap_pdr_text(
        text,
        fund_code="TST",
        report_period="2026-08",
    )
    assert any(
        row.asset_group == ASSET_GROUP_PARTICIPATION_ACCOUNT
        and row.portfolio_weight == 2.96
        for row in parsed.holdings
    )


def test_pdr_rejects_ocr_corrupted_numeric_participation_row():
    text = """
III-FON PORTFÖY DEĞERİ
MEVcUAT
VAcEgI ZİRAAT KATIgIM BANKASI A.Ş. 01.09.2026 VAcEgI 38.7S% 3S,237,369.86 3S,200,000.00 31.08.2026 0.00% 0 0 0 3S,237,369.86 49.89% 0.77%
IV-FON TOPLAM DEĞERİ TABLOSU
"""
    try:
        parsed = parse_kap_pdr_text(
            text,
            fund_code="TST",
            report_period="2026-08",
        )
    except KapPdrError:
        return

    assert not any(
        row.asset_group == ASSET_GROUP_PARTICIPATION_ACCOUNT
        and row.portfolio_weight == 0.77
        for row in parsed.holdings
    )
