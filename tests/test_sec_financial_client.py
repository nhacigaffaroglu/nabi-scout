import unittest

from services.sec_financial_client import SECFinancialClient


class AnnualSeriesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = SECFinancialClient(
            contact_email="test@example.com",
        )

    def test_annual_series_merges_alternative_tags_and_prefers_latest_periods(
        self,
    ) -> None:
        facts = {
            "RevenueFromContractWithCustomerExcludingAssessedTax": {
                "units": {
                    "USD": [
                        {
                            "form": "10-K",
                            "start": "2021-01-31",
                            "end": "2022-01-30",
                            "val": 26_914_000_000,
                            "filed": "2022-02-25",
                        },
                        {
                            "form": "10-K",
                            "start": "2020-01-27",
                            "end": "2021-01-31",
                            "val": 16_675_000_000,
                            "filed": "2021-02-26",
                        },
                    ],
                },
            },
            "Revenues": {
                "units": {
                    "USD": [
                        {
                            "form": "10-K",
                            "start": "2025-01-27",
                            "end": "2026-01-25",
                            "val": 215_938_000_000,
                            "filed": "2026-02-25",
                        },
                        {
                            "form": "10-K",
                            "start": "2024-01-29",
                            "end": "2025-01-26",
                            "val": 130_497_000_000,
                            "filed": "2025-02-26",
                        },
                        {
                            "form": "10-K",
                            "start": "2023-01-30",
                            "end": "2024-01-28",
                            "val": 60_922_000_000,
                            "filed": "2024-02-21",
                        },
                    ],
                },
            },
        }

        series = self.client._annual_series(
            facts,
            [
                "RevenueFromContractWithCustomerExcludingAssessedTax",
                "Revenues",
            ],
            ["USD"],
        )

        self.assertEqual(len(series), 5)
        self.assertEqual(series[0]["end"], "2026-01-25")
        self.assertEqual(series[0]["value"], 215_938_000_000)
        self.assertEqual(series[1]["end"], "2025-01-26")
        self.assertEqual(series[-1]["end"], "2021-01-31")

    def test_annual_series_dedupes_same_end_across_tags_by_latest_filed(
        self,
    ) -> None:
        facts = {
            "Revenues": {
                "units": {
                    "USD": [
                        {
                            "form": "10-K",
                            "start": "2024-01-29",
                            "end": "2025-01-26",
                            "val": 130_000_000_000,
                            "filed": "2025-02-20",
                        },
                    ],
                },
            },
            "SalesRevenueNet": {
                "units": {
                    "USD": [
                        {
                            "form": "10-K",
                            "start": "2024-01-29",
                            "end": "2025-01-26",
                            "val": 130_497_000_000,
                            "filed": "2025-02-26",
                        },
                    ],
                },
            },
        }

        series = self.client._annual_series(
            facts,
            ["Revenues", "SalesRevenueNet"],
            ["USD"],
        )

        self.assertEqual(len(series), 1)
        self.assertEqual(series[0]["value"], 130_497_000_000)
        self.assertEqual(series[0]["filed"], "2025-02-26")

    def test_extract_financials_uses_latest_revenue_for_period_end(
        self,
    ) -> None:
        payload = {
            "facts": {
                "us-gaap": {
                    "RevenueFromContractWithCustomerExcludingAssessedTax": {
                        "units": {
                            "USD": [
                                {
                                    "form": "10-K",
                                    "start": "2021-01-31",
                                    "end": "2022-01-30",
                                    "val": 26_914_000_000,
                                    "filed": "2022-02-25",
                                },
                            ],
                        },
                    },
                    "Revenues": {
                        "units": {
                            "USD": [
                                {
                                    "form": "10-K",
                                    "start": "2025-01-27",
                                    "end": "2026-01-25",
                                    "val": 215_938_000_000,
                                    "filed": "2026-02-25",
                                },
                                {
                                    "form": "10-K",
                                    "start": "2024-01-29",
                                    "end": "2025-01-26",
                                    "val": 130_497_000_000,
                                    "filed": "2025-02-26",
                                },
                                {
                                    "form": "10-K",
                                    "start": "2023-01-30",
                                    "end": "2024-01-28",
                                    "val": 60_922_000_000,
                                    "filed": "2024-02-21",
                                },
                                {
                                    "form": "10-K",
                                    "start": "2022-01-31",
                                    "end": "2023-01-29",
                                    "val": 26_975_000_000,
                                    "filed": "2023-02-24",
                                },
                            ],
                        },
                    },
                    "NetCashProvidedByUsedInOperatingActivities": {
                        "units": {
                            "USD": [
                                {
                                    "form": "10-K",
                                    "start": "2025-01-27",
                                    "end": "2026-01-25",
                                    "val": 102_718_000_000,
                                    "filed": "2026-02-25",
                                },
                            ],
                        },
                    },
                    "PaymentsToAcquirePropertyPlantAndEquipment": {
                        "units": {
                            "USD": [
                                {
                                    "form": "10-K",
                                    "start": "2025-01-27",
                                    "end": "2026-01-25",
                                    "val": 138_735_000,
                                    "filed": "2026-02-25",
                                },
                            ],
                        },
                    },
                },
            },
        }

        result = self.client.extract_financials(payload)

        self.assertEqual(result["financial_period_end"], "2026-01-25")
        self.assertEqual(result["revenue"], 215_938_000_000)
        self.assertLess(result["free_cash_flow_margin"], 100)


if __name__ == "__main__":
    unittest.main()
