import unittest
from unittest.mock import MagicMock

from services.scanner_v4_engine import ScannerV4Engine


class ValuationFallbackTests(unittest.TestCase):
    def _engine(self, *, quote=None, ratios=None, quote_error=None, ratios_error=None):
        fmp = MagicMock()
        sec = MagicMock()

        if quote_error:
            fmp.profile.return_value = {"companyName": "Test Co", "marketCap": 1000}
            fmp.quote.side_effect = quote_error
        else:
            fmp.profile.return_value = {"companyName": "Test Co", "marketCap": 1000}
            fmp.quote.return_value = quote or {}

        if ratios_error:
            fmp.ratios_ttm.side_effect = ratios_error
        else:
            fmp.ratios_ttm.return_value = ratios or {}

        sec.company_facts.return_value = {"facts": {"us-gaap": {}}}
        sec.extract_financials.return_value = {
            "revenue": 100.0,
            "equity": 50.0,
            "revenue_growth_1y": 10.0,
            "revenue_cagr_3y": 12.0,
            "eps_growth_1y": 8.0,
            "eps_cagr_3y": 10.0,
            "fcf_cagr_3y": 9.0,
            "gross_margin": 40.0,
            "operating_margin": 20.0,
            "net_margin": 15.0,
            "free_cash_flow_margin": 12.0,
            "roic": 18.0,
            "roe": 20.0,
            "roa": 10.0,
            "current_ratio": 1.5,
            "debt_to_equity": 0.8,
            "net_debt_to_fcf": 1.0,
            "interest_coverage": 10.0,
            "share_change_3y": -2.0,
            "payout_ratio": 20.0,
            "financial_period_end": "2025-12-31",
            "annual_periods_found": 5,
        }

        return ScannerV4Engine(fmp, sec)

    def test_pe_from_quote_when_available(self):
        engine = self._engine(quote={"pe": 18.5, "price": 100, "marketCap": 1000})
        result = engine.analyze(
            symbol="TEST",
            cik=1,
            company_name="Test Co",
            exchange="Nasdaq",
        )
        self.assertEqual(result["candidate"]["pe_ratio"], 18.5)
        engine.fmp.ratios_ttm.assert_not_called()

    def test_pe_fallback_from_ratios_when_quote_missing_pe(self):
        engine = self._engine(
            quote={"price": 100, "marketCap": 1000},
            ratios={"priceToEarningsRatioTTM": 24.2},
        )
        result = engine.analyze(
            symbol="TEST",
            cik=1,
            company_name="Test Co",
            exchange="Nasdaq",
        )
        self.assertEqual(result["candidate"]["pe_ratio"], 24.2)
        engine.fmp.ratios_ttm.assert_called_once_with("TEST")

    def test_pe_expensive_affects_valuation_score(self):
        engine = self._engine(
            quote={"pe": 55.0, "price": 100, "marketCap": 1000},
        )
        result = engine.analyze(
            symbol="TEST",
            cik=1,
            company_name="Test Co",
            exchange="Nasdaq",
        )
        self.assertLess(result["candidate"]["valuation_score"], 20)

    def test_pe_missing_and_no_fallback_keeps_pe_none(self):
        engine = self._engine(
            quote={"price": 100, "marketCap": 1000},
            ratios={},
        )
        result = engine.analyze(
            symbol="TEST",
            cik=1,
            company_name="Test Co",
            exchange="Nasdaq",
        )
        self.assertIsNone(result["candidate"]["pe_ratio"])

    def test_quote_failure_but_ratios_fallback_pe(self):
        from services.fmp_client import FMPError

        engine = self._engine(
            quote_error=FMPError("quote kapalı"),
            ratios={"priceToEarningsRatioTTM": 21.0},
        )
        result = engine.analyze(
            symbol="TEST",
            cik=1,
            company_name="Test Co",
            exchange="Nasdaq",
        )
        self.assertEqual(result["candidate"]["pe_ratio"], 21.0)


if __name__ == "__main__":
    unittest.main()
