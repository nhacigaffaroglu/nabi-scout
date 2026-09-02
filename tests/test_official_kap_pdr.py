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

        # OCR-corrupted identity must remain raw evidence only.
        # It must not be promoted to canonical ISIN/official_code.
        self.assertIsNone(holding.isin)
        self.assertIsNone(holding.official_code)
        self.assertIsNone(holding.market_value)

        rec = reconcile_pdr_weights(pdr.holdings)
        self.assertAlmostEqual(rec.reported_weight_sum, 0.37)
        self.assertAlmostEqual(rec.known_weight, 0.0)
        self.assertAlmostEqual(rec.unknown_weight, 0.37)

        official = pdr_rows_to_official_holdings(pdr)
        self.assertEqual(len(official.holdings), 1)
        self.assertEqual(official.holdings[0].ticker, "")

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


if __name__ == "__main__":
    unittest.main()
