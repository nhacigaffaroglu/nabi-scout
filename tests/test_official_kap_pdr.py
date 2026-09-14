from __future__ import annotations

import unittest

from services.official_kap_pdr import (
    parse_kap_pdr_text,
    pdr_rows_to_official_holdings,
    reconcile_pdr_weights,
)


def _parse(body: str):
    text = f"""
III-FON PORTFÖY DEĞERİ TABLOSU
{body}
IV-FON TOPLAM DEĞERİ TABLOSU
"""
    return parse_kap_pdr_text(
        text,
        fund_code="TST",
        report_period="2026-07",
    )


class KapPdrEquityRegressionTests(unittest.TestCase):

    def test_compact_a_pay_section_is_equity(self) -> None:
        pdr = _parse(
            """
A.PAY
TESTA.E TEST ŞİRKETİ TRAAAAA00001 TL 100 10 1000 0.45% 0.43%
"""
        )

        self.assertEqual(len(pdr.holdings), 1)
        self.assertEqual(pdr.holdings[0].asset_group, "EQUITY")
        self.assertAlmostEqual(pdr.holdings[0].portfolio_weight, 0.43)

    def test_ocr_damaged_equity_uses_explicit_toplam_percentage(self) -> None:
        pdr = _parse(
            """
A.PAY
ASEgS.E ASEgSAN ELEKTRONİK TRAASEgS91H2 TL 100 10 1000 0.50% 0.37%
"""
        )

        self.assertEqual(len(pdr.holdings), 1)
        holding = pdr.holdings[0]

        self.assertEqual(holding.asset_group, "EQUITY")
        self.assertAlmostEqual(holding.portfolio_weight, 0.37)

        # Bounded OCR recovery may promote exactly one checksum-valid ISIN.
        # The raw OCR security token remains unchanged.
        self.assertEqual(holding.security_name_raw, "ASEgS.E")
        self.assertEqual(holding.isin, "TRAASELS91H2")
        self.assertEqual(holding.official_code, "TRAASELS91H2")
        self.assertIsNone(holding.market_value)

        rec = reconcile_pdr_weights(pdr.holdings)
        self.assertAlmostEqual(rec.reported_weight_sum, 0.37)
        self.assertAlmostEqual(rec.known_weight, 0.37)
        self.assertAlmostEqual(rec.unknown_weight, 0.0)

        official = pdr_rows_to_official_holdings(pdr)
        self.assertEqual(len(official.holdings), 1)
        self.assertEqual(official.holdings[0].ticker, "TRAASELS91H2")

    def test_valid_equity_identity_remains_available_downstream(self) -> None:
        pdr = _parse(
            """
A.PAY
TESTA.E TEST ŞİRKETİ TRAAAAA00001 TL 100 10 1000 0.45% 0.43%
"""
        )
        self.assertEqual(len(pdr.holdings), 1)

        official = pdr_rows_to_official_holdings(pdr)
        self.assertEqual(len(official.holdings), 1)
        self.assertNotEqual(official.holdings[0].ticker, "")

    def test_multiple_lots_with_same_valid_isin_remain_separate(self) -> None:
        pdr = _parse(
            """
A.PAY
CVKMc.E CVK MADEN TRECVKM00021 TL 100 10 1000 0.40% 0.40%
CVKMc.E CVK MADEN TRECVKM00021 TL 200 10 2000 0.77% 0.77%
CVKMc.E CVK MADEN TRECVKM00021 TL 300 10 3000 0.22% 0.22%
"""
        )

        self.assertEqual(len(pdr.holdings), 3)

        weights = [row.portfolio_weight for row in pdr.holdings]
        self.assertEqual(weights, [0.40, 0.77, 0.22])

        rec = reconcile_pdr_weights(pdr.holdings)
        self.assertAlmostEqual(rec.reported_weight_sum, 1.39)


    def test_wrapped_numeric_fund_name_does_not_leak_into_financial_columns(self) -> None:
        pdr = _parse(
            """
ALTIN KATILIM PORTFÖY

Z30KE - ZİRAAT TL ZİRAAT TRYZIPO00212 6.000,00 118,528992 12/06/26 80100103 174,100000 1.044.600,00 5,80 2,74 3,00
PORTFÖY BIST
KATILIM 30 EŞİT
AĞIRLIKLI ENDEKSİ
HİSSE SENEDİ
YOĞUN BORSA YATIRIM
FONU A.Ş.
"""
        )

        self.assertEqual(len(pdr.holdings), 1)
        holding = pdr.holdings[0]

        # "KATILIM 30" belongs to the wrapped security name. It must never
        # become a financial value.
        self.assertAlmostEqual(holding.market_value, 1044600.00)
        self.assertAlmostEqual(holding.portfolio_weight, 3.00)


    def test_percent_tail_ticker_portfolio_rows_without_currency(self) -> None:
        pdr = _parse(
            """
A) HİSSE SENETLERİ

EGGUB EGE GÜBRE 10.000,00 940.500,00 6,45%

N) KATILMA BELGELERİ

KVR ATLAS PORTFÖY YÖNETİMİ A.Ş. 117.027,00 148.110,54 1,02%
NRF ONE PORTFÖY YÖNETİMİ A.Ş. 424.977,00 607.490,60 4,17%

Y) DİĞER

601.878,90 601.878,90 4,13%
"""
        )

        # Named portfolio rows with nominal, market value and an explicit
        # portfolio percentage are valid even when currency/ISIN is absent.
        self.assertEqual(len(pdr.holdings), 3)

        rows = {row.official_code: row for row in pdr.holdings}

        eggub = rows["EGGUB"]
        self.assertAlmostEqual(eggub.nominal, 10000.00)
        self.assertAlmostEqual(eggub.market_value, 940500.00)
        self.assertAlmostEqual(eggub.portfolio_weight, 6.45)

        kvr = rows["KVR"]
        self.assertAlmostEqual(kvr.nominal, 117027.00)
        self.assertAlmostEqual(kvr.market_value, 148110.54)
        self.assertAlmostEqual(kvr.portfolio_weight, 1.02)

        nrf = rows["NRF"]
        self.assertAlmostEqual(nrf.nominal, 424977.00)
        self.assertAlmostEqual(nrf.market_value, 607490.60)
        self.assertAlmostEqual(nrf.portfolio_weight, 4.17)

        # Anonymous rows remain fail-closed: no identity is invented.
        self.assertNotIn(None, rows)


    def test_d_maden_section_abbreviation_is_precious_metals(self) -> None:
        pdr = _parse(
            """
N) KATILMA BELGELERİ
KSV KATILIM FONU TRYAAAA00001 100,00 1.000,00 1,00%
D.Maden
ALTIN LBMA 995 TL TRKAU0000014 100,00 99.000,00 99,00%
"""
        )

        self.assertEqual(len(pdr.holdings), 2)
        self.assertEqual(pdr.holdings[0].asset_group, "FUND")
        self.assertEqual(pdr.holdings[1].asset_group, "PRECIOUS_METALS")
        self.assertAlmostEqual(pdr.holdings[1].portfolio_weight, 99.00)

    def test_repeated_complete_isin_rows_are_not_merged_into_group_total(self) -> None:
        pdr = _parse(
            """
A) ÖZEL SEKTÖR KİRA SERTİFİKA YP
XS2699906512 ZİRAAT KATILIM VARLIK KİRALAMA A.Ş. 12.11.2026 XS2699906512 9.38% 2 1,000,000.00 101.72 07.07.2025 0.00% 0 0.00 103.27 48,891,872.99 1.69% 1.54%
XS2699906512 ZİRAAT KATILIM VARLIK KİRALAMA A.Ş. 12.11.2026 XS2699906512 9.38% 2 6,000,000.00 101.73 22.08.2025 0.00% 0 0.00 103.27 293,351,237.96 10.14% 9.26%
Ara Grup Toplamı 7,000,000.00 342,243,110.95 11.83% 10.80%
Ana Grup Toplamı 60,300,000.00 2,891,978,324.75 100.03% 91.29%
"""
        )
        self.assertEqual([row.portfolio_weight for row in pdr.holdings], [1.54, 9.26])
        self.assertAlmostEqual(pdr.weights.reported_weight_sum, 10.80)

    def test_ocr_damaged_group_total_line_does_not_become_holding_weight(self) -> None:
        pdr = _parse(
            """
A) ÖZEL SEKTÖR KİRA SERTİFİKA YP
XS2699906512 ZİRAAT KATILIM VARLIK KİRALAMA A.Ş. 12.11.2026 XS2699906512 9.38% 2 1,000,000.00 101.72 07.07.2025 0.00% 0 0.00 103.27 48,891,872.99 1.69% 1.54%
Ara Grup Toplam/idotless 1,000,000.00 48,891,872.99 1.69% 1.54%
Ana Grup Toplam/idotless 60,300,000.00 2,891,978,324.75 100.03% 91.29%
"""
        )
        self.assertEqual(len(pdr.holdings), 1)
        self.assertAlmostEqual(pdr.holdings[0].portfolio_weight, 1.54)

    def test_ocr_equity_does_not_salvage_numeric_suffix_from_corrupt_percent(self) -> None:
        pdr = _parse(
            """
A) HİSSE SENETLERİ
AgBRK.E ALBARAKA TÜRK KATILIM BANKASI TREAgBK00011 0.00% 0 S,000,000.00 8.2S 0S.06.2026 0.00% 0 0 7.9S 2S,790,000.00 15.49% S.92%
AgBRK.E ALBARAKA TÜRK KATILIM BANKASI TREAgBK00011 0.00% 0 449,286.00 7.99 02.06.2026 0.00% 0 0 7.9S S,562,8S7.98 2.S2% 0.59%
"""
        )
        self.assertEqual(len(pdr.holdings), 1)
        self.assertAlmostEqual(pdr.holdings[0].portfolio_weight, 0.59)

if __name__ == "__main__":
    unittest.main()


def test_ocr_equity_recovers_single_checksum_valid_isin() -> None:
    pdr = _parse(
        """
A.PAY
ASEgS.E ASEgSAN ELEKTRONİK TRAASEgS91H2 TL 100 10 1000 0.50% 0.37%
"""
    )

    assert len(pdr.holdings) == 1
    holding = pdr.holdings[0]

    assert holding.security_name_raw == "ASEgS.E"
    assert holding.isin == "TRAASELS91H2"
    assert holding.official_code == "TRAASELS91H2"
    assert holding.market_value is None
    assert holding.portfolio_weight == 0.37


def test_ocr_equity_rejects_repair_when_checksum_invalid() -> None:
    pdr = _parse(
        """
A.PAY
ASEgS.E ASEgSAN ELEKTRONİK TRAASEgS91H3 TL 100 10 1000 0.50% 0.37%
"""
    )

    assert len(pdr.holdings) == 1
    holding = pdr.holdings[0]

    assert holding.security_name_raw == "ASEgS.E"
    assert holding.isin is None
    assert holding.official_code is None

def test_zck_lease_certificate_trailing_100_does_not_override_portfolio_weight():
    """ZCK-style KAP row: trailing 100,000 is not the portfolio weight."""
    from services.official_kap_pdr import parse_kap_pdr_text

    text = """
O - KİRA SERTİFİKASI KIYMETLER         İhraçcı                      Nominal     Rayiç Değer        Oran (%)
        13.11.2026 TRDBRKTK2614        ALBARAKA TÜRK              3.000.000    3.055.553,48        0,759414              100,000
        18.12.2026 TRDEVKSA2659        TÜRKİYE EMLAK KATILI       3.000.000    3.033.295,35        0,753882              100,000
        17.11.2026 TRDKTLMK2633        BRİSA                      5.000.000    5.577.056,13        1,386097              100,000
"""

    parsed = parse_kap_pdr_text(
        text,
        fund_code="ZCK",
        report_period="2026-08",
    )

    rows = [
        row for row in parsed.holdings
        if row.asset_group == "LEASE_CERTIFICATE"
    ]

    assert len(rows) == 3

    by_code = {row.official_code: row for row in rows}

    assert round(by_code["TRDBRKTK2614"].portfolio_weight, 6) == 0.759414
    assert round(by_code["TRDEVKSA2659"].portfolio_weight, 6) == 0.753882
    assert round(by_code["TRDKTLMK2633"].portfolio_weight, 6) == 1.386097

    assert round(by_code["TRDBRKTK2614"].market_value, 2) == 3055553.48
    assert round(by_code["TRDEVKSA2659"].market_value, 2) == 3033295.35
    assert round(by_code["TRDKTLMK2633"].market_value, 2) == 5577056.13

    assert all(row.portfolio_weight != 100.0 for row in rows)

def test_sale_promise_purchase_trailing_value_does_not_override_market_value():
    """KAP Satış Vaadiyle Alış trailing field is not Rayiç Değer."""
    from services.official_kap_pdr import parse_kap_pdr_text

    text = """
1 - FON PORTFÖY DEĞERİ TABLOSU
Z - Satış Vaadiyle Alış İhraçcı Nominal Rayiç Değer Oran (%)
01.09.2026 TRD080927T34 HAZİNE 428.280.780 428.280.780,47 22,265850 150,60
01.09.2026 TRD020627T17 HAZİNE 300.301.233 300.301.232,88 15,612333 232,57
AA - Alış Vaadiyle Satış İhraçcı Nominal Rayiç Değer Oran (%)
"""

    parsed = parse_kap_pdr_text(
        text,
        fund_code="ZPO",
        report_period="2026-08",
    )

    rows = {
        row.official_code: row
        for row in parsed.holdings
        if row.official_code in {"TRD080927T34", "TRD020627T17"}
    }

    assert set(rows) == {"TRD080927T34", "TRD020627T17"}

    assert rows["TRD080927T34"].asset_group == "REPO"
    assert round(rows["TRD080927T34"].nominal, 2) == 428280780.00
    assert round(rows["TRD080927T34"].market_value, 2) == 428280780.47
    assert round(rows["TRD080927T34"].portfolio_weight, 6) == 22.265850

    assert rows["TRD020627T17"].asset_group == "REPO"
    assert round(rows["TRD020627T17"].nominal, 2) == 300301233.00
    assert round(rows["TRD020627T17"].market_value, 2) == 300301232.88
    assert round(rows["TRD020627T17"].portfolio_weight, 6) == 15.612333



def test_zpo_physical_participation_accounts_keep_row_values_isolated():
    """Physical KAP participation-account rows must retain their own values."""
    from services.official_kap_pdr import parse_kap_pdr_text

    text = """
1 - FON PORTFÖY DEĞERİ TABLOSU
S - KATILIM HESABI                     İhraçcı                      Nominal     Rayiç Değer        Oran (%)
11.09.2026 3AyaKadarVD-ALK-TRY 155.861.301 154.186.643,84 8,015995
11.09.2026 3AyaKadarVD-ZTB-TRY 155.861.301 154.186.643,84 8,015995
08.10.2026 3AyaKadarVD-ZTB-TRY 104.931.507 100.876.712,33 5,244470
01.09.2026 3AyaKadarVD-VKF-TRY 301.815.981 301.815.981,31 15,691084
"""

    parsed = parse_kap_pdr_text(
        text,
        fund_code="ZPO",
        report_period="2026-08",
    )

    rows = [
        row
        for row in parsed.holdings
        if row.asset_group == "PARTICIPATION_ACCOUNT"
    ]

    assert len(rows) == 4

    expected = [
        (
            "3AyaKadarVD-ALK-TRY",
            "2026-09-11",
            155861301.0,
            154186643.84,
            8.015995,
        ),
        (
            "3AyaKadarVD-ZTB-TRY",
            "2026-09-11",
            155861301.0,
            154186643.84,
            8.015995,
        ),
        (
            "3AyaKadarVD-ZTB-TRY",
            "2026-10-08",
            104931507.0,
            100876712.33,
            5.244470,
        ),
        (
            "3AyaKadarVD-VKF-TRY",
            "2026-09-01",
            301815981.0,
            301815981.31,
            15.691084,
        ),
    ]

    actual = [
        (
            row.official_code,
            row.maturity_date,
            round(row.nominal, 2),
            round(row.market_value, 2),
            round(row.portfolio_weight, 6),
        )
        for row in rows
    ]

    assert actual == expected
    assert all(row.currency == "TRY" for row in rows)
