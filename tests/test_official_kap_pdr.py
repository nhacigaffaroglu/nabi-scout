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


if __name__ == "__main__":
    unittest.main()
