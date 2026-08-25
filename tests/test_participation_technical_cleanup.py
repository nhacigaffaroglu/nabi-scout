from __future__ import annotations

from typing import Any, Dict

import unittest

from services.participation_financial_engine import evaluate_financial_rules
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    RULE_OUTCOME_INSUFFICIENT_DATA,
    RULE_OUTCOME_PASS,
)
from services.participation_sec_input_resolver import build_participation_inputs_from_sec
from services.sec_financial_client import SECFinancialClient
from tests.test_global_participation_reconciliation import _snapshot
from tests.test_participation_cached_evidence_resolver import _facts_payload
from tests.test_sec_sprint_a_extraction import _cost_facts, _idxx_facts, _extract, _screen
from services.global_participation_reconciliation import assess_from_cached_evidence
from services.sec_company_facts_evidence import build_company_facts_evidence
from services.sec_participation_evidence_population import AssessedEquityIdentity


def _instant(val: float, end: str, *, filed: str, form: str = "10-K") -> Dict[str, Any]:
    return {
        "units": {
            "USD": [
                {
                    "form": form,
                    "end": end,
                    "val": val,
                    "filed": filed,
                }
            ]
        }
    }


def _duration(
    val: float,
    start: str,
    end: str,
    *,
    filed: str,
    form: str = "10-K",
    unit: str = "USD",
) -> Dict[str, Any]:
    return {
        "units": {
            unit: [
                {
                    "form": form,
                    "start": start,
                    "end": end,
                    "val": val,
                    "filed": filed,
                }
            ]
        }
    }


def _payload(facts: Dict[str, Any], taxonomy: str = "us-gaap") -> Dict[str, Any]:
    return {"facts": {taxonomy: facts}}


def _client_extract(facts: Dict[str, Any], *, taxonomy: str = "us-gaap") -> Dict[str, Any]:
    return SECFinancialClient(contact_email="test@example.com").extract_financials(
        _payload(facts, taxonomy=taxonomy)
    )


class NoSubstitutionTests(unittest.TestCase):
    def test_cost_receivables_net_current_is_not_trade_ar(self) -> None:
        extracted = _extract(_cost_facts())
        self.assertIsNone(extracted["accounts_receivable"])
        inputs, financial, status = _screen("COST", extracted)
        self.assertIsNone(inputs.accounts_receivable)
        self.assertEqual(
            next(
                rule.outcome
                for rule in financial.rule_results
                if "receivables_and_cash" in rule.rule_id
            ),
            RULE_OUTCOME_INSUFFICIENT_DATA,
        )
        self.assertEqual(status, PARTICIPATION_STATUS_KONTROL_ET)

    def test_idxx_missing_ib_stays_none(self) -> None:
        extracted = _extract(_idxx_facts())
        self.assertIsNone(extracted["interest_bearing_securities"])
        inputs, _, status = _screen("IDXX", extracted)
        self.assertIsNone(inputs.cash_and_interest_bearing_securities)
        self.assertEqual(status, PARTICIPATION_STATUS_KONTROL_ET)


class PeriodSelectionTests(unittest.TestCase):
    def test_including_assessed_tax_selects_annual_period(self) -> None:
        extracted = _client_extract(
            {
                "RevenueFromContractWithCustomerIncludingAssessedTax": _duration(
                    5_496_389_000,
                    "2025-01-01",
                    "2025-12-31",
                    filed="2026-02-24",
                ),
                "Assets": _instant(5_470_160_000, "2025-12-31", filed="2026-02-24"),
                "CashAndCashEquivalentsAtCarryingValue": _instant(
                    50_000_000,
                    "2025-12-31",
                    filed="2026-02-24",
                ),
                "AccountsReceivableNetCurrent": _instant(
                    594_540_000,
                    "2025-12-31",
                    filed="2026-02-24",
                ),
            }
        )
        self.assertEqual(extracted["financial_period_end"], "2025-12-31")
        self.assertGreaterEqual(extracted["annual_periods_found"], 1)
        self.assertEqual(extracted["revenue"], 5_496_389_000)
        self.assertEqual(extracted["total_assets"], 5_470_160_000)

    def test_stale_revenue_tag_does_not_override_newer_annual_operating_revenue(self) -> None:
        extracted = _client_extract(
            {
                "RevenueFromContractWithCustomerExcludingAssessedTax": _duration(
                    11_537_000_000,
                    "2018-01-01",
                    "2018-12-31",
                    filed="2019-02-22",
                ),
                "RegulatedAndUnregulatedOperatingRevenue": _duration(
                    14_669_000_000,
                    "2025-01-01",
                    "2025-12-31",
                    filed="2026-02-25",
                ),
                "Assets": {
                    "units": {
                        "USD": [
                            {
                                "form": "10-K",
                                "end": "2018-12-31",
                                "val": 45_987_000_000,
                                "filed": "2019-02-22",
                            },
                            {
                                "form": "10-K",
                                "end": "2025-12-31",
                                "val": 81_371_000_000,
                                "filed": "2026-02-25",
                            },
                        ]
                    }
                },
                "AccountsReceivableNetCurrent": {
                    "units": {
                        "USD": [
                            {
                                "form": "10-K",
                                "end": "2018-12-31",
                                "val": 860_000_000,
                                "filed": "2019-02-22",
                            },
                            {
                                "form": "10-K",
                                "end": "2025-12-31",
                                "val": 1_330_000_000,
                                "filed": "2026-02-25",
                            },
                        ]
                    }
                },
            }
        )
        self.assertEqual(extracted["financial_period_end"], "2025-12-31")
        self.assertEqual(extracted["balance_sheet_period_end"], "2025-12-31")
        self.assertEqual(extracted["revenue"], 14_669_000_000)
        self.assertEqual(extracted["total_assets"], 81_371_000_000)
        self.assertEqual(extracted["accounts_receivable"], 1_330_000_000)

    def test_stale_income_is_not_mixed_with_newer_balance_sheet(self) -> None:
        extracted = _client_extract(
            {
                "Revenues": _duration(
                    11_537_000_000,
                    "2018-01-01",
                    "2018-12-31",
                    filed="2019-02-22",
                ),
                "Assets": _instant(81_371_000_000, "2025-12-31", filed="2026-02-25"),
            }
        )
        self.assertEqual(extracted["financial_period_end"], "2025-12-31")
        self.assertEqual(extracted["total_assets"], 81_371_000_000)
        self.assertIsNone(extracted["revenue"])

    def test_ten_q_only_facts_do_not_create_an_annual_period(self) -> None:
        extracted = _client_extract(
            {
                "Revenues": _duration(
                    201_155_000_000,
                    "2026-01-01",
                    "2026-06-30",
                    filed="2026-08-03",
                    form="10-Q",
                ),
                "Assets": _instant(
                    464_482_000_000,
                    "2026-06-30",
                    filed="2026-08-03",
                    form="10-Q",
                ),
            }
        )
        self.assertIsNone(extracted["financial_period_end"])
        self.assertEqual(extracted["annual_periods_found"], 0)
        self.assertIsNone(extracted["revenue"])


class CurrencySafeRatioTests(unittest.TestCase):
    def test_same_eur_inputs_compute_debt_ratio_without_fx(self) -> None:
        extracted = {
            "total_debt": 4_390_900_000.0,
            "total_assets": 50_566_600_000.0,
            "cash": 12_916_000_000.0,
            "accounts_receivable": 3_023_000_000.0,
            "interest_bearing_securities": 405_900_000.0,
            "revenue": 32_667_300_000.0,
            "financial_currency": "EUR",
            "financial_period_end": "2025-12-31",
            "annual_periods_found": 5,
        }
        result = build_participation_inputs_from_sec("ASML", extracted)
        self.assertEqual(result.inputs.total_debt, 4_390_900_000.0)
        self.assertEqual(result.inputs.total_assets, 50_566_600_000.0)
        self.assertEqual(
            result.inputs.cash_and_interest_bearing_securities,
            13_321_900_000.0,
        )
        screen = evaluate_financial_rules("msci_islamic_index_series", result.inputs)
        debt = next(rule for rule in screen.rule_results if "total_debt_to_total_assets" in rule.rule_id)
        self.assertEqual(debt.outcome, RULE_OUTCOME_PASS)
        self.assertEqual(dict(result.inputs.source_evidence)["financial_currency"], "EUR")

    def test_usd_market_cap_is_not_mixed_with_eur_financials(self) -> None:
        extracted = {
            "total_debt": 10.0,
            "total_assets": 100.0,
            "financial_currency": "EUR",
            "financial_period_end": "2025-12-31",
            "annual_periods_found": 3,
        }
        result = build_participation_inputs_from_sec(
            "ASML",
            extracted,
            market_capitalization=400.0,
        )
        self.assertIsNone(result.inputs.market_capitalization)
        self.assertEqual(result.inputs.total_debt, 10.0)

    def test_ifrs_current_trade_receivables_are_trade_ar(self) -> None:
        extracted = _client_extract(
            {
                "Revenue": _duration(
                    2_894_307_700_000,
                    "2024-01-01",
                    "2024-12-31",
                    filed="2025-04-17",
                    form="20-F",
                    unit="TWD",
                ),
                "Assets": {
                    "units": {
                        "TWD": [
                            {
                                "form": "20-F",
                                "end": "2024-12-31",
                                "val": 6_691_764_700_000,
                                "filed": "2025-04-17",
                            }
                        ]
                    }
                },
                "CurrentTradeReceivables": {
                    "units": {
                        "TWD": [
                            {
                                "form": "20-F",
                                "end": "2024-12-31",
                                "val": 270_683_200_000,
                                "filed": "2025-04-17",
                            }
                        ]
                    }
                },
            },
            taxonomy="ifrs-full",
        )
        self.assertEqual(extracted["financial_currency"], "TWD")
        self.assertEqual(extracted["accounts_receivable"], 270_683_200_000)
        self.assertEqual(extracted["accounts_receivable_tags"], "CurrentTradeReceivables")


class ApprovedRejectedRegressionTests(unittest.TestCase):
    def test_approved_anchor_not_regressed(self) -> None:
        evidence = build_company_facts_evidence(
            symbol="CRM",
            cik="0001108524",
            raw_payload=_facts_payload(),
            http_status=200,
        )
        extracted = SECFinancialClient(contact_email="cache-replay@localhost").extract_financials(
            evidence.raw_payload
        )
        item = assess_from_cached_evidence(
            identity=AssessedEquityIdentity(
                symbol="CRM",
                cik="0001108524",
                cik_source="snapshot",
                fetchable=True,
            ),
            evidence=evidence,
            snapshot=_snapshot("CRM", "0001108524", PARTICIPATION_STATUS_UYGUN),
            extracted=extracted,
        )
        self.assertEqual(item.new_status, PARTICIPATION_STATUS_UYGUN)


if __name__ == "__main__":
    unittest.main()
