from __future__ import annotations

import unittest
from pathlib import Path

from services.fund_intelligence_engine import evaluate_official_fund_intelligence
from services.fund_product_contract import (
    ASSET_GROUP_CASH,
    ASSET_GROUP_EQUITY,
    ASSET_GROUP_FUND,
    ASSET_GROUP_LEASE_CERTIFICATE,
    ASSET_GROUP_OTHER,
    ASSET_GROUP_PARTICIPATION_ACCOUNT,
    ASSET_GROUP_REPO,
    ASSET_GROUP_UNKNOWN,
    PDR_SUBJECT,
    PDR_SUBJECT_OID,
    PILOT_FUND_SYMBOLS,
    PILOT_TEFAS_FUND_CODES,
)
from services.official_kap_pdr import (
    KapPdrError,
    KapPdrHolding,
    discover_latest_pdr,
    explicit_subgroup_weights,
    issuer_count,
    join_pdr_to_security_master,
    largest_holding,
    normalize_pdr_asset_group,
    parse_kap_pdr_text,
    parse_pdr_attachment_html,
    parse_tr_date,
    pdr_lookthrough_readiness,
    reconcile_pdr_weights,
    reconstruct_split_table_rows,
    top_holdings,
)
from services.official_kap_pdr_evidence import (
    load_captured_pdr_discovery,
    load_captured_pdr_holdings,
    load_pdr_discovery_rows,
)
from services.official_sp_funds_product import default_official_sp_funds_provider
from services.official_tefas_product import default_tefas_fund_provider

PDR_SRC = Path("services/official_kap_pdr.py")
TEFAS_SRC = Path("services/official_tefas_product.py")
BIST = Path("services/bist_refresh_contract.py")
WEALTH_NEW_MONEY = Path("services/wealth_new_money_allocation.py")

AIS_JAMMED_TAAHHUT = """
III-FON PORTFÖY DEĞERİ TABLOSU
## Taahhüt Sözleşmesi Satış
TRD170730T14 TL HAZİNE 03/08/26 0 TRD170730T14 38,00 2 100.312.328,77 100.312.328,77 1,25 0,73 0,74
| VADEYE VADE İHRAÇCI ISIN KODU TRD190728T16 TL HAZİNE 07/08/26 4 TRD190728T16 TRD190728T16 TL HAZİNE 07/08/26 4 TRD190728T16 GRUP TOPLAMI | 38,40 2 100.736.438,36 38,40 2 100.736.438,36 | 38,400000 100.314.954,58 1,25 0,73 0,74 38,400000 100.314.954,58 1,25 0,74 0,74 8.025.117.591,97 100,00 58,80 59,19 |
IV-FON TOPLAM DEĞERİ TABLOSU
"""


def _holding(**kwargs) -> KapPdrHolding:
    payload = {
        "fund_code": "AIS",
        "report_period": "2026-07",
        "report_date": None,
        "asset_group": ASSET_GROUP_LEASE_CERTIFICATE,
        "asset_group_raw": "KİRA SERTİFİKALARI",
        "security_name_raw": "TRD080927T34",
        "issuer_raw": "HAZİNE",
        "isin": "TRD080927T34",
        "official_code": "TRD080927T34",
        "maturity_date": "2027-09-08",
        "currency": "TL",
        "quantity": None,
        "nominal": 100.0,
        "unit_price": 100.0,
        "market_value": 100.0,
        "portfolio_weight": 10.0,
        "fund_total_value": 1000.0,
        "source_notification_id": "1",
        "source_attachment": "x.pdf",
        "provenance": ("kap_pdr_official",),
    }
    payload.update(kwargs)
    return KapPdrHolding(**payload)


class KapPortfolioHoldingsTests(unittest.TestCase):
    def test_pdr_discovery_uses_fund_type_and_period(self) -> None:
        rows = load_pdr_discovery_rows()
        ais = discover_latest_pdr(rows, "AIS")
        zpe = discover_latest_pdr(rows, "ZPE")
        iat = discover_latest_pdr(rows, "IAT")
        self.assertTrue(ais.resolved)
        self.assertEqual(ais.disclosure_index, 1644043)
        self.assertEqual(ais.report_period, "2026-07")
        self.assertEqual(ais.subject, PDR_SUBJECT)
        self.assertNotEqual(ais.disclosure_index, 1625691)
        self.assertEqual(zpe.disclosure_index, 1646036)
        self.assertNotEqual(zpe.disclosure_index, 1628321)
        self.assertEqual(iat.disclosure_index, 1643690)
        self.assertEqual(PDR_SUBJECT_OID, "8aca490d502e34b801502e380044002b")
        missing = discover_latest_pdr(rows, "ZZZ")
        self.assertFalse(missing.resolved)
        self.assertIn("LATEST_PDR_UNRESOLVED", missing.limitations)

    def test_attachment_parser_does_not_need_hardcoded_ids(self) -> None:
        name, file_id = parse_pdr_attachment_html(
            '<a href="/tr/api/file/download/abc123def456">AIS_2026.07.pdf</a>'
        )
        self.assertEqual(name, "AIS_2026.07.pdf")
        self.assertEqual(file_id, "abc123def456")
        captured = load_captured_pdr_discovery("AIS")
        self.assertEqual(captured.attachment_name, "AIS_2026.07.pdf")

    def test_asset_group_normalization_is_label_only(self) -> None:
        self.assertEqual(normalize_pdr_asset_group("HİSSE SENETLERİ"), ASSET_GROUP_EQUITY)
        self.assertEqual(normalize_pdr_asset_group("KİRA SERTİFİKALARI"), ASSET_GROUP_LEASE_CERTIFICATE)
        self.assertEqual(normalize_pdr_asset_group("KATILIM HESABI"), ASSET_GROUP_PARTICIPATION_ACCOUNT)
        self.assertEqual(normalize_pdr_asset_group("Satış Vaadiyle Alış"), ASSET_GROUP_REPO)
        self.assertEqual(normalize_pdr_asset_group("HAZIR DEĞERLER"), ASSET_GROUP_CASH)
        self.assertEqual(normalize_pdr_asset_group("BORÇLAR"), ASSET_GROUP_OTHER)
        self.assertEqual(normalize_pdr_asset_group("menkul kıymet"), ASSET_GROUP_UNKNOWN)

    def test_ais_parser(self) -> None:
        file = load_captured_pdr_holdings("AIS")
        self.assertGreaterEqual(len(file.holdings), 20)
        groups = {row.asset_group for row in file.holdings}
        self.assertIn(ASSET_GROUP_LEASE_CERTIFICATE, groups)
        self.assertIn(ASSET_GROUP_PARTICIPATION_ACCOUNT, groups)
        self.assertEqual(sum(1 for row in file.holdings if row.asset_group == ASSET_GROUP_PARTICIPATION_ACCOUNT), 8)
        self.assertTrue(any(row.isin == "TRD080927T34" for row in file.holdings))
        self.assertTrue(any(row.issuer_raw and "HAZİNE" in row.issuer_raw for row in file.holdings))
        self.assertTrue(any(row.maturity_date == "2027-09-08" for row in file.holdings))
        self.assertTrue(any(row.currency == "TL" for row in file.holdings))
        self.assertGreater(issuer_count(file), 3)
        largest = largest_holding(file)
        self.assertIsNotNone(largest)
        self.assertEqual(len(top_holdings(file, 10)), 10)
        self.assertFalse(file.weights.renormalized)
        self.assertTrue(file.weights.weight_reconciled)
        self.assertGreaterEqual(file.weights.reported_weight_sum, 95.0)
        self.assertLessEqual(file.weights.reported_weight_sum, 100.50)
        repo_w = sum(float(row.portfolio_weight or 0) for row in file.holdings if row.asset_group == ASSET_GROUP_REPO)
        self.assertAlmostEqual(repo_w, 59.19, places=2)
        self.assertFalse(any((row.portfolio_weight or 0) == 23.97 for row in file.holdings))
        self.assertTrue(
            any(
                row.asset_group_raw and "Taahhüt" in row.asset_group_raw
                for row in file.holdings
                if row.asset_group == ASSET_GROUP_REPO
            )
        )

    def test_zpe_parser(self) -> None:
        file = load_captured_pdr_holdings("ZPE")
        self.assertGreaterEqual(len(file.holdings), 25)
        equity_w = sum(float(row.portfolio_weight or 0) for row in file.holdings if row.asset_group == ASSET_GROUP_EQUITY)
        fund_w = sum(float(row.portfolio_weight or 0) for row in file.holdings if row.asset_group == ASSET_GROUP_FUND)
        self.assertGreater(equity_w, 50)
        self.assertGreater(fund_w, 10)
        self.assertTrue(any(row.official_code == "ASELS.E" for row in file.holdings))
        self.assertTrue(any(row.official_code == "TUPRS.E" for row in file.holdings))
        self.assertTrue(any(row.isin == "TRD160926T35" for row in file.holdings))
        asels = next(row for row in file.holdings if row.official_code == "ASELS.E")
        self.assertIsNone(asels.isin)
        self.assertEqual(asels.asset_group, ASSET_GROUP_EQUITY)
        self.assertFalse(file.weights.renormalized)

    def test_iat_parser(self) -> None:
        file = load_captured_pdr_holdings("IAT")
        self.assertGreaterEqual(len(file.holdings), 40)
        self.assertTrue(all(row.asset_group in {ASSET_GROUP_LEASE_CERTIFICATE, ASSET_GROUP_CASH, ASSET_GROUP_OTHER} for row in file.holdings))
        public_w = explicit_subgroup_weights(file, "Kamu Kesimi")
        private_w = explicit_subgroup_weights(file, "Özel Sektör")
        self.assertGreater(public_w, 30)
        self.assertGreater(private_w, 50)
        self.assertTrue(any(row.isin == "TRD080927T34" and row.issuer_raw == "HAZİNE" for row in file.holdings))
        self.assertTrue(any(row.issuer_raw and "ZİRAAT KATILIM" in row.issuer_raw for row in file.holdings))
        self.assertGreater(issuer_count(file), 5)
        self.assertFalse(file.weights.renormalized)

    def test_multi_section_pdf_and_field_preservation(self) -> None:
        text = """
        III-FON PORTFÖY DEĞERİ TABLOSU
        KİRA SERTİFİKALARI
        TRD120826T14 TL HAZİNE 12/08/26 9 TRD120826T14 0,00 2 4.880.000,00 101,402500 5.752.586,91 0,33 0,33 0,33
        KATILIM HESABI
        ZIRAAT KATILIM TL 03/08/26 0 38,50 770.697.821,97 773.136.605,49 22,85 5,66 5,67
        IV-FON TOPLAM DEĞERİ TABLOSU
        E-)BORÇLAR -5.686.289,75 -0,04 %
        """
        file = parse_kap_pdr_text(text, fund_code="AIS", report_period="2026-07")
        groups = [row.asset_group for row in file.holdings]
        self.assertIn(ASSET_GROUP_LEASE_CERTIFICATE, groups)
        self.assertIn(ASSET_GROUP_PARTICIPATION_ACCOUNT, groups)
        self.assertIn(ASSET_GROUP_OTHER, groups)
        kira = next(row for row in file.holdings if row.isin == "TRD120826T14")
        self.assertEqual(kira.issuer_raw, "HAZİNE")
        self.assertEqual(kira.maturity_date, "2026-08-12")
        self.assertEqual(kira.currency, "TL")
        self.assertEqual(kira.portfolio_weight, 0.33)
        debt = next(row for row in file.holdings if row.asset_group_raw == "BORÇLAR")
        self.assertEqual(debt.portfolio_weight, -0.04)
        self.assertEqual(debt.market_value, -5686289.75)

    def test_negative_row_preserved_and_no_renormalize(self) -> None:
        rows = (
            _holding(portfolio_weight=60.0),
            _holding(isin="TRD1", official_code="TRD1", portfolio_weight=-3.5, asset_group=ASSET_GROUP_REPO),
            _holding(isin=None, official_code=None, portfolio_weight=30.0),
        )
        weights = reconcile_pdr_weights(rows)
        self.assertEqual(weights.reported_weight_sum, 86.5)
        self.assertEqual(weights.known_weight, 56.5)
        self.assertEqual(weights.unknown_weight, 30.0)
        self.assertEqual(weights.residual_weight, 13.5)
        self.assertFalse(weights.renormalized)
        self.assertFalse(weights.weight_reconciled)

    def test_unknown_weight_and_maturity_currency(self) -> None:
        self.assertEqual(parse_tr_date("08/09/27"), "2027-09-08")
        file = parse_kap_pdr_text(
            """
            III-FON PORTFÖY DEĞERİ TABLOSU
            KİRA SERTİFİKALARI
            TRD080927T34 TL HAZİNE 08/09/27 401 TRD080927T34 0,00 2 99.290.000,00 106,165600 116.838.480,52 6,69 6,68 6,61
            """,
            fund_code="IAT",
        )
        row = file.holdings[0]
        self.assertEqual(row.isin, "TRD080927T34")
        self.assertEqual(row.maturity_date, "2027-09-08")
        self.assertEqual(row.currency, "TL")

    def test_deterministic_security_master_join_no_fuzzy_names(self) -> None:
        file = load_captured_pdr_holdings("ZPE")
        overlap = join_pdr_to_security_master(file)
        self.assertIn("ASELS", overlap.matched_symbols)
        self.assertIn("BIMAS", overlap.matched_symbols)
        self.assertIn("TUPRS", overlap.matched_symbols)
        self.assertGreater(overlap.matched_weight, 15)
        self.assertGreater(overlap.unmatched_holdings, overlap.matched_holdings)
        named = parse_kap_pdr_text(
            """
            III-FON PORTFÖY DEĞERİ TABLOSU
            KİRA SERTİFİKALARI
            TRD999999T99 TL ASELSAN 08/09/27 401 TRD999999T99 0,00 2 10.000,00 100,000000 10.000,00 4,49 4,49 4,49
            """,
            fund_code="ZPE",
        )
        fuzzy = join_pdr_to_security_master(named)
        self.assertEqual(fuzzy.matched_holdings, 0)
        self.assertNotIn("ASELS", fuzzy.matched_symbols)
        exact = parse_kap_pdr_text(
            """
            ZPE table
            2 ASELS.E ASELSAN 157.608,000 53.941.338,00 4,490423 306,688
            """,
            fund_code="ZPE",
        )
        hit = join_pdr_to_security_master(exact)
        self.assertEqual(hit.matched_symbols, ("ASELS",))

    def test_participation_isolation(self) -> None:
        provider = default_tefas_fund_provider()
        source = PDR_SRC.read_text(encoding="utf-8")
        self.assertNotIn("PARTICIPATION_STATUS_UYGUN", source)
        self.assertNotIn("purification", source.lower())
        for code in PILOT_TEFAS_FUND_CODES:
            self.assertIsNone(provider.purification_evidence(code).latest_factor_pct)

    def test_sp_funds_bist_us_eight_e_isolation(self) -> None:
        provider = default_tefas_fund_provider()
        source = PDR_SRC.read_text(encoding="utf-8")
        self.assertNotIn("evaluate_official_fund_intelligence", source)
        self.assertNotIn("evaluate_official_fund_decision", source)
        self.assertNotIn("allocate_new_money", source)
        self.assertNotIn("DATABASE_URL", source)
        self.assertNotIn("FMPClient", source)
        for symbol in PILOT_FUND_SYMBOLS:
            self.assertFalse(provider.supports(symbol))
        self.assertEqual(evaluate_official_fund_intelligence("SPUS").score, 71.41)
        self.assertEqual(evaluate_official_fund_intelligence("SPSK").score, 65.87)
        self.assertEqual(evaluate_official_fund_intelligence("SPRE").score, 47.57)
        self.assertEqual(evaluate_official_fund_intelligence("SPWO").score, 52.79)
        self.assertTrue(BIST.is_file())
        self.assertIn("ASELS", BIST.read_text(encoding="utf-8"))
        self.assertTrue(WEALTH_NEW_MONEY.is_file())
        self.assertNotIn("AIS", WEALTH_NEW_MONEY.read_text(encoding="utf-8"))
        self.assertNotIn("pdr_holdings", Path("services/official_sp_funds_product.py").read_text(encoding="utf-8"))

    def test_lookthrough_readiness_without_fi_score(self) -> None:
        zpe = load_captured_pdr_holdings("ZPE")
        overlap = join_pdr_to_security_master(zpe)
        ready = pdr_lookthrough_readiness(zpe, overlap=overlap)
        self.assertTrue(ready.diversification_ready)
        self.assertTrue(ready.concentration_ready)
        self.assertTrue(ready.security_master_overlap_ready)
        ais = load_captured_pdr_holdings("AIS")
        ais_ready = pdr_lookthrough_readiness(ais)
        self.assertTrue(ais_ready.maturity_ready)
        iat = load_captured_pdr_holdings("IAT")
        iat_ready = pdr_lookthrough_readiness(iat)
        self.assertTrue(iat_ready.issuer_concentration_ready)
        self.assertTrue(iat_ready.maturity_ready)

    def test_empty_text_fails_closed(self) -> None:
        with self.assertRaises(KapPdrError):
            parse_kap_pdr_text("", fund_code="AIS")

    def test_provider_surface(self) -> None:
        provider = default_tefas_fund_provider()
        for code in PILOT_TEFAS_FUND_CODES:
            file = provider.pdr_holdings(code)
            self.assertEqual(file.fund_code, code)
            self.assertGreater(len(file.holdings), 0)

    def test_ais_jammed_taahhut_continuation(self) -> None:
        pipe = next(line for line in AIS_JAMMED_TAAHHUT.splitlines() if line.startswith("|"))
        rebuilt = reconstruct_split_table_rows(pipe)
        self.assertEqual(len(rebuilt), 2)
        self.assertTrue(all("TRD190728T16" in row and "HAZİNE" in row for row in rebuilt))
        self.assertTrue(all("0,74" in row or "0,73" in row for row in rebuilt))
        unmatched = reconstruct_split_table_rows(
            "| TRD190728T16 TL HAZİNE 07/08/26 4 TRD190728T16 | 100,00 58,80 59,19 |"
        )
        self.assertEqual(unmatched, [])
        file = parse_kap_pdr_text(AIS_JAMMED_TAAHHUT, fund_code="AIS", report_period="2026-07")
        self.assertEqual(len(file.holdings), 3)
        self.assertTrue(all(row.asset_group_raw == "Taahhüt Sözleşmesi Satış" for row in file.holdings))
        self.assertAlmostEqual(sum(float(row.portfolio_weight or 0) for row in file.holdings), 2.22, places=2)
        self.assertFalse(file.weights.renormalized)
        self.assertFalse(any((row.portfolio_weight or 0) == 23.97 for row in file.holdings))
        zpe = load_captured_pdr_holdings("ZPE")
        iat = load_captured_pdr_holdings("IAT")
        self.assertEqual(zpe.weights.reported_weight_sum, 100.0)
        self.assertAlmostEqual(iat.weights.reported_weight_sum, 99.99, places=2)

    def test_wrapped_pdr_layout_no_forced_reconciliation(self) -> None:
        from services.official_kap_pdr import is_valid_isin

        self.assertTrue(is_valid_isin("TRXDRP012213"))
        self.assertFalse(is_valid_isin("TOPLAMTOPLAM"))
        wrapped = """
III-FON PORTFÖY DEĞERİ TABLOSU
HİSSE SENETLERİ
ALTIN                  TL     HAZİNE                        TRXDRP012213 26.000,00 1.769.040,00 50,98 4,37 5,04
ALTIN                  TL     HAZİNE                        TRXDRP012213 25.000,00 1.701.000,00 49,02 4,20 4,84
  GRUP TOPLAMI 100,00 8,57 9,88
KİRA SERTİFİKALARI
TRDZKBV82629           TL       ZKB      19/08/26    16 TRDZKBV82629 1.000.000,00 1.181.586,29 4,57 2,92 3,36
                              VARLIK                        TRDZKBV82629
                             KİRALAMA
                                A.Ş.
TRD270127T13          AU1     HAZİNE     27/01/27    177 TRD270127T13 18.503.052,67 71,53 45,70 52,68
TRD180827T17          AU1     HAZİNE     18/08/27    380 TRD180827T17 6.183.634,50 23,90 15,28 17,61
KATILIM HESABI
MİSYON YATIRIM         TL                03/08/26     0 1.143.705,00 100,00 2,82 3,26
BANKASI A.Ş.
Borsa Y.Fonu Türk
GLDTR                TL     QNB 2.484.000,00 24,84 6,14 7,07
GLDTR                TL     QNB 3.622.500,00 36,23 8,95 10,31
GMSTR                TL     QNB 852.800,00 8,53 2,11 2,43
PRR-INVEO            TL    GEDİK 3.040.229,45 30,40 7,51 8,66
IV-FON TOPLAM DEĞERİ TABLOSU
FON TOPLAM DEĞERİ 35.122.410,69 100,00 %
B-)HAZIR DEĞERLER 3.548,03 0,01 %
C-)ALACAKLAR 37.868,72 0,11 %
E-)BORÇLAR -5.400.553,97 -15,38 %
"""
        file = parse_kap_pdr_text(wrapped, fund_code="BAI", report_period="2026-07")
        self.assertFalse(file.weights.renormalized)
        self.assertTrue(file.weights.weight_reconciled)
        self.assertAlmostEqual(file.weights.reported_weight_sum, 100.0, places=2)
        self.assertTrue(any(row.official_code == "GLDTR" for row in file.holdings))
        self.assertTrue(any((row.portfolio_weight or 0) < 0 for row in file.holdings))
        ais = load_captured_pdr_holdings("AIS")
        self.assertEqual(len(ais.holdings), 120)
        self.assertTrue(ais.weights.weight_reconciled)


if __name__ == "__main__":
    unittest.main()
