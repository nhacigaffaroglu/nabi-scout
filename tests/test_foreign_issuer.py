import unittest

from services.scanner_v4_engine import ScannerV4Engine
from services.sec_financial_client import SECFinancialClient


def annual_entry(
    *,
    form: str = "10-K",
    start: str,
    end: str,
    val: float,
    filed: str = "2025-02-01",
) -> dict:
    return {
        "form": form,
        "start": start,
        "end": end,
        "val": val,
        "filed": filed,
    }


def tag_facts(unit: str, entries: list[dict]) -> dict:
    return {"units": {unit: entries}}


def payload_for(taxonomy: str, tags: dict[str, dict]) -> dict:
    return {"facts": {taxonomy: tags}}


class FakeFMP:
    def __init__(
        self,
        *,
        market_cap: float,
        currency: str = "USD",
        pe: float | None = None,
    ) -> None:
        self.market_cap = market_cap
        self.currency = currency
        self.pe = pe

    def profile(self, symbol):
        return {
            "companyName": symbol,
            "currency": self.currency,
            "marketCap": self.market_cap,
        }

    def quote(self, symbol):
        data = {
            "price": 100,
            "marketCap": self.market_cap,
            "currency": self.currency,
        }
        if self.pe is not None:
            data["pe"] = self.pe
        return data

    def ratios_ttm(self, symbol):
        if self.pe is None:
            return {"priceToEarningsRatioTTM": 20}
        return {}


class FakeSEC:
    def __init__(self, financials: dict) -> None:
        self.financials = financials

    def company_facts(self, cik):
        return {"facts": {"us-gaap": {}}}

    def extract_financials(self, payload):
        return self.financials


class ForeignIssuerFinancialTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = SECFinancialClient(
            contact_email="test@example.com",
        )

    def test_us_gaap_usd_behavior_unchanged(self) -> None:
        payload = payload_for(
            "us-gaap",
            {
                "Revenues": tag_facts(
                    "USD",
                    [annual_entry(start="2024-01-01", end="2024-12-31", val=100)],
                ),
                "NetCashProvidedByUsedInOperatingActivities": tag_facts(
                    "USD",
                    [annual_entry(start="2024-01-01", end="2024-12-31", val=30)],
                ),
                "PaymentsToAcquirePropertyPlantAndEquipment": tag_facts(
                    "USD",
                    [annual_entry(start="2024-01-01", end="2024-12-31", val=10)],
                ),
            },
        )

        result = self.client.extract_financials(payload)

        self.assertEqual(result["financial_taxonomy"], "us-gaap")
        self.assertEqual(result["financial_currency"], "USD")
        self.assertEqual(result["revenue"], 100)
        self.assertEqual(result["free_cash_flow_margin"], 20.0)

    def test_ifrs_native_currency_revenue_selected(self) -> None:
        payload = payload_for(
            "ifrs-full",
            {
                "Revenue": tag_facts(
                    "TWD",
                    [
                        annual_entry(
                            form="20-F",
                            start="2024-01-01",
                            end="2024-12-31",
                            val=2_894_307_700_000,
                            filed="2025-04-17",
                        ),
                        annual_entry(
                            form="20-F",
                            start="2023-01-01",
                            end="2023-12-31",
                            val=2_161_735_800_000,
                            filed="2024-04-18",
                        ),
                    ],
                ),
                "ProfitLossFromOperatingActivities": tag_facts(
                    "TWD",
                    [
                        annual_entry(
                            form="20-F",
                            start="2024-01-01",
                            end="2024-12-31",
                            val=1_322_053_000_000,
                            filed="2025-04-17",
                        ),
                    ],
                ),
            },
        )
        payload["facts"]["ifrs-full"]["Revenue"]["units"]["USD"] = [
            annual_entry(
                form="20-F",
                start="2024-01-01",
                end="2024-12-31",
                val=90_000_000_000,
                filed="2025-04-17",
            ),
        ]

        result = self.client.extract_financials(payload)

        self.assertEqual(result["financial_taxonomy"], "ifrs-full")
        self.assertEqual(result["financial_currency"], "TWD")
        self.assertEqual(result["revenue"], 2_894_307_700_000)

    def test_eur_us_gaap_revenue_selected(self) -> None:
        payload = payload_for(
            "us-gaap",
            {
                "RevenueFromContractWithCustomerExcludingAssessedTax": tag_facts(
                    "EUR",
                    [
                        annual_entry(
                            form="20-F",
                            start="2025-01-01",
                            end="2025-12-31",
                            val=32_667_300_000,
                            filed="2026-02-12",
                        ),
                    ],
                ),
            },
        )

        result = self.client.extract_financials(payload)

        self.assertEqual(result["financial_taxonomy"], "us-gaap")
        self.assertEqual(result["financial_currency"], "EUR")
        self.assertEqual(result["revenue"], 32_667_300_000)

    def test_fcf_margin_correct_in_same_currency(self) -> None:
        payload = payload_for(
            "ifrs-full",
            {
                "Revenue": tag_facts(
                    "EUR",
                    [annual_entry(form="20-F", start="2025-01-01", end="2025-12-31", val=100)],
                ),
                "CashFlowsFromUsedInOperatingActivities": tag_facts(
                    "EUR",
                    [annual_entry(form="20-F", start="2025-01-01", end="2025-12-31", val=40)],
                ),
                "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities": tag_facts(
                    "EUR",
                    [annual_entry(form="20-F", start="2025-01-01", end="2025-12-31", val=10)],
                ),
            },
        )

        result = self.client.extract_financials(payload)

        self.assertEqual(result["free_cash_flow_margin"], 30.0)

    def test_unsupported_taxonomy_graceful_fallback(self) -> None:
        result = self.client.extract_financials(
            {"facts": {"dei": {}, "srt": {}}},
        )

        self.assertIsNone(result["revenue"])
        self.assertEqual(result["annual_periods_found"], 0)
        self.assertIsNone(result["financial_currency"])

    def test_mixed_currency_not_blended(self) -> None:
        payload = payload_for(
            "ifrs-full",
            {
                "Revenue": tag_facts(
                    "TWD",
                    [
                        annual_entry(
                            form="20-F",
                            start="2024-01-01",
                            end="2024-12-31",
                            val=100,
                            filed="2025-04-17",
                        ),
                    ],
                ),
                "ProfitLossFromOperatingActivities": tag_facts(
                    "USD",
                    [
                        annual_entry(
                            form="20-F",
                            start="2024-01-01",
                            end="2024-12-31",
                            val=50,
                            filed="2025-04-17",
                        ),
                    ],
                ),
            },
        )

        result = self.client.extract_financials(payload)

        self.assertEqual(result["financial_currency"], "TWD")
        self.assertIsNone(result["operating_margin"])

    def test_roic_none_when_balance_sheet_missing_in_native_currency(self) -> None:
        payload = payload_for(
            "ifrs-full",
            {
                "Revenue": tag_facts(
                    "EUR",
                    [annual_entry(form="20-F", start="2025-01-01", end="2025-12-31", val=100)],
                ),
                "ProfitLossFromOperatingActivities": tag_facts(
                    "EUR",
                    [annual_entry(form="20-F", start="2025-01-01", end="2025-12-31", val=20)],
                ),
                "Equity": tag_facts(
                    "USD",
                    [{"form": "20-F", "end": "2025-12-31", "val": 500, "filed": "2026-02-12"}],
                ),
            },
        )

        result = self.client.extract_financials(payload)

        self.assertEqual(result["financial_currency"], "EUR")
        self.assertIsNone(result["equity"])
        self.assertIsNone(result["roic"])

    def test_debt_to_equity_requires_same_currency_components(self) -> None:
        payload = payload_for(
            "us-gaap",
            {
                "RevenueFromContractWithCustomerExcludingAssessedTax": tag_facts(
                    "EUR",
                    [annual_entry(form="20-F", start="2025-01-01", end="2025-12-31", val=100)],
                ),
                "StockholdersEquity": tag_facts(
                    "EUR",
                    [{"form": "20-F", "end": "2025-12-31", "val": 200, "filed": "2026-02-12"}],
                ),
                "LongTermDebtNoncurrent": tag_facts(
                    "USD",
                    [{"form": "20-F", "end": "2025-12-31", "val": 50, "filed": "2026-02-12"}],
                ),
            },
        )

        result = self.client.extract_financials(payload)

        self.assertEqual(result["financial_currency"], "EUR")
        self.assertEqual(result["equity"], 200)
        self.assertIsNone(result["total_debt"])
        self.assertIsNone(result["debt_to_equity"])


class CrossCurrencyValuationTests(unittest.TestCase):
    def test_cross_currency_ps_pb_not_computed(self) -> None:
        financials = {
            "revenue": 100_000_000_000,
            "equity": 50_000_000_000,
            "financial_currency": "EUR",
            "financial_taxonomy": "us-gaap",
            "financial_period_end": "2025-12-31",
            "annual_periods_found": 5,
        }
        engine = ScannerV4Engine(
            FakeFMP(market_cap=1_000_000_000_000, currency="USD"),
            FakeSEC(financials),
        )
        candidate = engine.analyze(
            symbol="ASML",
            cik=937966,
            company_name="ASML",
            exchange="NASDAQ",
        )["candidate"]

        self.assertIsNone(candidate["price_to_sales"])
        self.assertIsNone(candidate["price_to_book"])
        self.assertEqual(candidate["financial_currency"], "EUR")

    def test_usd_financials_keep_ps_pb(self) -> None:
        financials = {
            "revenue": 100_000,
            "equity": 50_000,
            "financial_currency": "USD",
            "financial_taxonomy": "us-gaap",
            "financial_period_end": "2025-12-31",
            "annual_periods_found": 5,
        }
        engine = ScannerV4Engine(
            FakeFMP(market_cap=1_000_000, currency="USD"),
            FakeSEC(financials),
        )
        candidate = engine.analyze(
            symbol="AAPL",
            cik=320193,
            company_name="Apple",
            exchange="NASDAQ",
        )["candidate"]

        self.assertEqual(candidate["price_to_sales"], 10.0)
        self.assertEqual(candidate["price_to_book"], 20.0)

    def test_twd_financials_block_ps_pb(self) -> None:
        financials = {
            "revenue": 1_000_000,
            "equity": 500_000,
            "financial_currency": "TWD",
            "financial_taxonomy": "ifrs-full",
            "financial_period_end": "2024-12-31",
            "annual_periods_found": 5,
        }
        engine = ScannerV4Engine(
            FakeFMP(market_cap=2_000_000, currency="USD"),
            FakeSEC(financials),
        )
        candidate = engine.analyze(
            symbol="TSM",
            cik=1046179,
            company_name="TSMC",
            exchange="NYSE",
        )["candidate"]

        self.assertIsNone(candidate["price_to_sales"])
        self.assertIsNone(candidate["price_to_book"])


if __name__ == "__main__":
    unittest.main()
