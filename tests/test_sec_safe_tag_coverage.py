from __future__ import annotations

import unittest

from services.participation_sec_input_resolver import build_participation_inputs_from_sec
from services.sec_financial_client import SECFinancialClient
from tests.test_sec_sprint_a_extraction import _duration, _extract, _instant


def _base(**facts):
    payload = {
        "Revenues": _duration(100, "2025-01-01", "2025-12-31", filed="2026-02-01"),
        "Assets": _instant(100, "2025-12-31", filed="2026-02-01"),
    }
    payload.update(facts)
    return payload


class SafeDebtAliasTests(unittest.TestCase):
    def test_ea_senior_notes_supply_total_debt(self) -> None:
        extracted = _extract(
            _base(
                SeniorNotes=_instant(1_485_000_000, "2025-12-31", filed="2026-05-11"),
            )
        )
        self.assertEqual(extracted["total_debt"], 1_485_000_000)
        self.assertEqual(extracted["total_debt_tags"], "SeniorNotes")

    def test_dxcm_convertible_long_term_notes_supply_debt(self) -> None:
        extracted = _extract(
            _base(
                ConvertibleLongTermNotesPayable=_instant(
                    1_240_900_000,
                    "2025-12-31",
                    filed="2026-02-12",
                ),
            )
        )
        self.assertEqual(extracted["total_debt"], 1_240_900_000)
        self.assertEqual(extracted["total_debt_tags"], "ConvertibleLongTermNotesPayable")

    def test_ilmn_notes_current_plus_long_term_sum_without_double_count(self) -> None:
        extracted = _extract(
            _base(
                NotesPayableCurrent=_instant(499_000_000, "2025-12-31", filed="2026-02-12"),
                LongTermNotesPayable=_instant(
                    1_490_000_000,
                    "2025-12-31",
                    filed="2026-02-12",
                ),
            )
        )
        self.assertEqual(extracted["total_debt"], 1_989_000_000)
        self.assertEqual(
            extracted["total_debt_tags"],
            "NotesPayableCurrent+LongTermNotesPayable",
        )

    def test_aggregate_debt_beats_alias_components(self) -> None:
        extracted = _extract(
            _base(
                DebtAndCapitalLeaseObligations=_instant(
                    50,
                    "2025-12-31",
                    filed="2026-02-01",
                ),
                SeniorNotes=_instant(40, "2025-12-31", filed="2026-02-01"),
                NotesPayableCurrent=_instant(10, "2025-12-31", filed="2026-02-01"),
                ConvertibleLongTermNotesPayable=_instant(
                    40,
                    "2025-12-31",
                    filed="2026-02-01",
                ),
            )
        )
        self.assertEqual(extracted["total_debt"], 50)
        self.assertEqual(extracted["total_debt_tags"], "DebtAndCapitalLeaseObligations")

    def test_existing_long_term_debt_beats_notes_aliases(self) -> None:
        extracted = _extract(
            _base(
                LongTermDebt=_instant(80, "2025-12-31", filed="2026-02-01"),
                LongTermNotesPayable=_instant(80, "2025-12-31", filed="2026-02-01"),
                SeniorNotes=_instant(80, "2025-12-31", filed="2026-02-01"),
            )
        )
        self.assertEqual(extracted["total_debt"], 80)
        self.assertEqual(extracted["total_debt_tags"], "LongTermDebt")

    def test_operating_lease_liability_is_not_total_debt(self) -> None:
        extracted = _extract(
            _base(
                OperatingLeaseLiability=_instant(90, "2025-12-31", filed="2026-02-01"),
                OperatingLeaseLiabilityCurrent=_instant(
                    20,
                    "2025-12-31",
                    filed="2026-02-01",
                ),
                OperatingLeaseLiabilityNoncurrent=_instant(
                    70,
                    "2025-12-31",
                    filed="2026-02-01",
                ),
            )
        )
        self.assertIsNone(extracted["total_debt"])
        self.assertIsNone(extracted["total_debt_tags"])

    def test_debt_maturity_schedule_is_not_total_debt(self) -> None:
        extracted = _extract(
            _base(
                LongTermDebtMaturitiesRepaymentsOfPrincipalInYearTwo=_instant(
                    6_631_000_000,
                    "2025-12-31",
                    filed="2026-03-02",
                ),
            )
        )
        self.assertIsNone(extracted["total_debt"])

    def test_zero_convertible_debt_current_is_not_proof_of_zero_total_debt(self) -> None:
        extracted = _extract(
            _base(
                ConvertibleDebtCurrent=_instant(0, "2025-12-31", filed="2026-02-01"),
            )
        )
        self.assertIsNone(extracted["total_debt"])

    def test_zero_line_of_credit_is_not_proof_of_zero_total_debt(self) -> None:
        extracted = _extract(
            _base(
                LineOfCredit=_instant(0, "2025-12-31", filed="2026-02-01"),
                OtherBorrowings=_instant(0, "2025-12-31", filed="2026-02-01"),
            )
        )
        self.assertIsNone(extracted["total_debt"])

    def test_finance_lease_liability_is_not_added_this_sprint(self) -> None:
        extracted = _extract(
            _base(
                FinanceLeaseLiability=_instant(60_500_000, "2025-12-31", filed="2026-02-12"),
                FinanceLeaseLiabilityCurrent=_instant(
                    6_700_000,
                    "2025-12-31",
                    filed="2026-02-12",
                ),
                FinanceLeaseLiabilityNoncurrent=_instant(
                    53_800_000,
                    "2025-12-31",
                    filed="2026-02-12",
                ),
            )
        )
        self.assertIsNone(extracted["total_debt"])

    def test_missing_debt_stays_none(self) -> None:
        extracted = _extract(_base())
        self.assertIsNone(extracted["total_debt"])


class SafeInterestBearingAliasTests(unittest.TestCase):
    def test_cecl_afs_excluding_accrued_interest_supplies_ib(self) -> None:
        extracted = _extract(
            _base(
                DebtSecuritiesAvailableForSaleExcludingAccruedInterest=_instant(
                    1_081_000_000,
                    "2025-12-31",
                    filed="2026-02-12",
                ),
            )
        )
        self.assertEqual(extracted["interest_bearing_securities"], 1_081_000_000)
        self.assertEqual(
            extracted["interest_bearing_securities_tags"],
            "DebtSecuritiesAvailableForSaleExcludingAccruedInterest",
        )

    def test_cecl_afs_current_and_noncurrent_sum_and_beat_aggregate(self) -> None:
        extracted = _extract(
            _base(
                DebtSecuritiesAvailableForSaleExcludingAccruedInterestCurrent=_instant(
                    1_668_000_000,
                    "2025-12-31",
                    filed="2026-02-01",
                ),
                DebtSecuritiesAvailableForSaleExcludingAccruedInterestNoncurrent=_instant(
                    94_000_000,
                    "2025-12-31",
                    filed="2026-02-01",
                ),
                DebtSecuritiesAvailableForSaleExcludingAccruedInterest=_instant(
                    1_818_000_000,
                    "2025-12-31",
                    filed="2026-02-01",
                ),
            )
        )
        self.assertEqual(extracted["interest_bearing_securities"], 1_762_000_000)
        self.assertEqual(
            extracted["interest_bearing_securities_tags"],
            "DebtSecuritiesAvailableForSaleExcludingAccruedInterestCurrent+"
            "DebtSecuritiesAvailableForSaleExcludingAccruedInterestNoncurrent",
        )

    def test_legacy_afs_current_noncurrent_beats_cecl_aliases(self) -> None:
        extracted = _extract(
            _base(
                AvailableForSaleSecuritiesDebtSecuritiesCurrent=_instant(
                    80,
                    "2025-12-31",
                    filed="2026-02-01",
                ),
                AvailableForSaleSecuritiesDebtSecuritiesNoncurrent=_instant(
                    20,
                    "2025-12-31",
                    filed="2026-02-01",
                ),
                DebtSecuritiesAvailableForSaleExcludingAccruedInterest=_instant(
                    100,
                    "2025-12-31",
                    filed="2026-02-01",
                ),
            )
        )
        self.assertEqual(extracted["interest_bearing_securities"], 100)
        self.assertEqual(
            extracted["interest_bearing_securities_tags"],
            "AvailableForSaleSecuritiesDebtSecuritiesCurrent+"
            "AvailableForSaleSecuritiesDebtSecuritiesNoncurrent",
        )

    def test_legacy_afs_aggregate_beats_cecl_aggregate(self) -> None:
        extracted = _extract(
            _base(
                AvailableForSaleSecuritiesDebtSecurities=_instant(
                    100,
                    "2025-12-31",
                    filed="2026-02-01",
                ),
                DebtSecuritiesAvailableForSaleExcludingAccruedInterest=_instant(
                    100,
                    "2025-12-31",
                    filed="2026-02-01",
                ),
            )
        )
        self.assertEqual(extracted["interest_bearing_securities"], 100)
        self.assertEqual(
            extracted["interest_bearing_securities_tags"],
            "AvailableForSaleSecuritiesDebtSecurities",
        )

    def test_blk_htm_plus_trading_debt_sum(self) -> None:
        extracted = _extract(
            _base(
                HeldToMaturitySecurities=_instant(
                    507_000_000,
                    "2025-12-31",
                    filed="2026-02-01",
                ),
                TradingSecuritiesDebt=_instant(
                    2_789_000_000,
                    "2025-12-31",
                    filed="2026-02-01",
                ),
            )
        )
        self.assertEqual(extracted["interest_bearing_securities"], 3_296_000_000)
        self.assertEqual(
            extracted["interest_bearing_securities_tags"],
            "HeldToMaturitySecurities+TradingSecuritiesDebt",
        )

    def test_marketable_tier_beats_htm_and_trading(self) -> None:
        extracted = _extract(
            _base(
                MarketableSecurities=_instant(10, "2025-12-31", filed="2026-02-01"),
                HeldToMaturitySecurities=_instant(5, "2025-12-31", filed="2026-02-01"),
                TradingSecuritiesDebt=_instant(5, "2025-12-31", filed="2026-02-01"),
            )
        )
        self.assertEqual(extracted["interest_bearing_securities"], 10)
        self.assertEqual(extracted["interest_bearing_securities_tags"], "MarketableSecurities")

    def test_equity_fvni_is_not_interest_bearing(self) -> None:
        extracted = _extract(
            _base(
                EquitySecuritiesFvNi=_instant(31_760_000, "2025-12-31", filed="2026-02-20"),
                EquitySecuritiesFvNiCurrentAndNoncurrent=_instant(
                    31_760_000,
                    "2025-12-31",
                    filed="2026-02-20",
                ),
            )
        )
        self.assertIsNone(extracted["interest_bearing_securities"])

    def test_afs_maturity_buckets_are_not_interest_bearing(self) -> None:
        extracted = _extract(
            _base(
                AvailableForSaleSecuritiesDebtMaturitiesWithinOneYearFairValue=_instant(
                    847_000_000,
                    "2025-12-31",
                    filed="2026-02-01",
                ),
                AvailableForSaleSecuritiesDebtMaturitiesAfterTenYearsFairValue=_instant(
                    22_845_000_000,
                    "2025-12-31",
                    filed="2026-02-01",
                ),
            )
        )
        self.assertIsNone(extracted["interest_bearing_securities"])

    def test_time_deposits_remain_excluded(self) -> None:
        extracted = _extract(
            _base(
                TimeDepositsAtCarryingValue=_instant(
                    72_700_000,
                    "2025-12-31",
                    filed="2026-02-01",
                ),
            )
        )
        self.assertIsNone(extracted["interest_bearing_securities"])
        inputs = build_participation_inputs_from_sec("MRVL", extracted).inputs
        self.assertIsNone(inputs.cash_and_interest_bearing_securities)

    def test_missing_ib_stays_none_not_zero(self) -> None:
        extracted = _extract(
            _base(
                CashAndCashEquivalentsAtCarryingValue=_instant(
                    25,
                    "2025-12-31",
                    filed="2026-02-01",
                ),
            )
        )
        self.assertIsNone(extracted["interest_bearing_securities"])
        inputs = build_participation_inputs_from_sec("WMT", extracted).inputs
        self.assertIsNone(inputs.cash_and_interest_bearing_securities)


class UnchangedCashAndReceivableTests(unittest.TestCase):
    def test_receivables_net_current_is_still_not_trade_ar(self) -> None:
        extracted = _extract(
            _base(
                ReceivablesNetCurrent=_instant(3_203_000_000, "2025-12-31", filed="2026-02-01"),
                CreditAndDebitCardReceivablesAtCarryingValue=_instant(
                    2_670_000_000,
                    "2025-12-31",
                    filed="2026-02-01",
                ),
            )
        )
        self.assertIsNone(extracted["accounts_receivable"])

    def test_disposal_group_cash_tag_is_not_accepted(self) -> None:
        extracted = _extract(
            _base(
                CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsIncludingDisposalGroupAndDiscontinuedOperations=_instant(
                    6_307_900_000,
                    "2025-12-31",
                    filed="2026-02-01",
                ),
            )
        )
        self.assertIsNone(extracted["cash"])


class OdflReplayShapeTests(unittest.TestCase):
    def test_including_assessed_tax_revenue_resolves_annual_period(self) -> None:
        extracted = _extract(
            {
                "RevenueFromContractWithCustomerIncludingAssessedTax": _duration(
                    5_496_389_000,
                    "2025-01-01",
                    "2025-12-31",
                    filed="2026-02-25",
                ),
                "Assets": _instant(5_470_160_000, "2025-12-31", filed="2026-02-25"),
                "CashAndCashEquivalentsAtCarryingValue": _instant(
                    120_091_000,
                    "2025-12-31",
                    filed="2026-02-25",
                ),
                "AccountsReceivableNetCurrent": _instant(
                    471_947_000,
                    "2025-12-31",
                    filed="2026-02-25",
                ),
                "DebtAndCapitalLeaseObligations": _instant(
                    39_995_000,
                    "2025-12-31",
                    filed="2026-02-25",
                ),
                "ShortTermInvestments": _instant(0, "2025-12-31", filed="2026-02-25"),
            }
        )
        self.assertEqual(extracted["financial_period_end"], "2025-12-31")
        self.assertGreaterEqual(extracted["annual_periods_found"], 1)
        self.assertEqual(extracted["total_debt"], 39_995_000)
        self.assertEqual(extracted["interest_bearing_securities"], 0)
        inputs = build_participation_inputs_from_sec("ODFL", extracted).inputs
        self.assertEqual(inputs.cash_and_interest_bearing_securities, 120_091_000)


class AsmlTsmResolverReplayTests(unittest.TestCase):
    def test_eur_extract_populates_asml_inputs_without_fx(self) -> None:
        extracted = SECFinancialClient(contact_email="test@example.com").extract_financials(
            {
                "facts": {
                    "us-gaap": {
                        "Revenues": {
                            "units": {
                                "EUR": [
                                    {
                                        "form": "20-F",
                                        "start": "2025-01-01",
                                        "end": "2025-12-31",
                                        "val": 32_667_300_000,
                                        "filed": "2026-03-01",
                                    }
                                ]
                            }
                        },
                        "Assets": {
                            "units": {
                                "EUR": [
                                    {
                                        "form": "20-F",
                                        "end": "2025-12-31",
                                        "val": 50_566_600_000,
                                        "filed": "2026-03-01",
                                    }
                                ]
                            }
                        },
                        "LongTermDebtCurrent": {
                            "units": {
                                "EUR": [
                                    {
                                        "form": "20-F",
                                        "end": "2025-12-31",
                                        "val": 1_000_000,
                                        "filed": "2026-03-01",
                                    }
                                ]
                            }
                        },
                        "LongTermDebtAndCapitalLeaseObligations": {
                            "units": {
                                "EUR": [
                                    {
                                        "form": "20-F",
                                        "end": "2025-12-31",
                                        "val": 4_389_900_000,
                                        "filed": "2026-03-01",
                                    }
                                ]
                            }
                        },
                    }
                }
            }
        )
        self.assertEqual(extracted["financial_currency"], "EUR")
        result = build_participation_inputs_from_sec("ASML", extracted)
        self.assertEqual(result.inputs.total_debt, 4_390_900_000)
        self.assertEqual(result.inputs.total_assets, 50_566_600_000)
        self.assertIsNone(result.inputs.non_permissible_revenue)

    def test_twd_ifrs_extract_populates_tsm_inputs_without_fx(self) -> None:
        from tests.test_participation_technical_cleanup import _client_extract, _duration

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
                "CurrentPortionOfLongtermBorrowings": {
                    "units": {
                        "TWD": [
                            {
                                "form": "20-F",
                                "end": "2024-12-31",
                                "val": 10_000_000,
                                "filed": "2025-04-17",
                            }
                        ]
                    }
                },
                "LongtermBorrowings": {
                    "units": {
                        "TWD": [
                            {
                                "form": "20-F",
                                "end": "2024-12-31",
                                "val": 91_672_300_000,
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
        result = build_participation_inputs_from_sec("TSM", extracted)
        self.assertEqual(result.inputs.total_debt, 91_682_300_000)
        self.assertEqual(result.inputs.accounts_receivable, 270_683_200_000)
        self.assertIsNone(result.inputs.non_permissible_revenue)


if __name__ == "__main__":
    unittest.main()
