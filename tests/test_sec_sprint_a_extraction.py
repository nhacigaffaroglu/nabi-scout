from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict

import unittest

from services.participation_business_contract import (
    EVIDENCE_COMPLETENESS_COMPLETE,
    BusinessActivityRuleResult,
    BusinessActivityScreenResult,
)
from services.participation_financial_engine import evaluate_financial_rules
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
    RULE_OUTCOME_FAIL,
    RULE_OUTCOME_INSUFFICIENT_DATA,
    RULE_OUTCOME_PASS,
)
from services.participation_intelligence_service import _combined_assessment_status
from services.participation_sec_input_resolver import build_participation_inputs_from_sec
from services.sec_financial_client import SECFinancialClient


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
) -> Dict[str, Any]:
    return {
        "units": {
            "USD": [
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


def _payload(facts: Dict[str, Any]) -> Dict[str, Any]:
    return {"facts": {"us-gaap": facts}}


def _extract(facts: Dict[str, Any]) -> Dict[str, Any]:
    client = SECFinancialClient(contact_email="test@example.com")
    return client.extract_financials(_payload(facts))


def _stored_business_pass(symbol: str) -> BusinessActivityScreenResult:
    return BusinessActivityScreenResult(
        symbol=symbol,
        methodology_id="msci_islamic_index_series",
        methodology_version="2025-05",
        rule_results=(
            BusinessActivityRuleResult(
                rule_id="msci.sic_exclusions",
                category="sic",
                outcome=RULE_OUTCOME_PASS,
            ),
            BusinessActivityRuleResult(
                rule_id="msci.sector_exclusions",
                category="sector",
                outcome=RULE_OUTCOME_PASS,
            ),
            BusinessActivityRuleResult(
                rule_id="msci.description_keywords",
                category="keyword",
                outcome=RULE_OUTCOME_INSUFFICIENT_DATA,
            ),
            BusinessActivityRuleResult(
                rule_id="msci.non_permissible_revenue",
                category="revenue",
                outcome=RULE_OUTCOME_PASS,
                ratio_pct=0.0,
                threshold_pct=5.0,
                comparator="<=",
            ),
        ),
        overall_outcome=RULE_OUTCOME_PASS,
        evidence_completeness=EVIDENCE_COMPLETENESS_COMPLETE,
        business_rules_evaluated=True,
        methodology_complete=True,
    )


def _screen(symbol: str, extracted: Dict[str, Any]):
    resolution = build_participation_inputs_from_sec(symbol, extracted)
    inputs = replace(
        resolution.inputs,
        non_permissible_revenue=0.0,
    )
    financial = evaluate_financial_rules("msci_islamic_index_series", inputs)
    status = _combined_assessment_status(financial, _stored_business_pass(symbol))
    return resolution.inputs, financial, status


class PeriodAlignedCashTests(unittest.TestCase):
    def test_biib_uses_restricted_cash_tag_at_assets_period(self) -> None:
        extracted = _extract(
            {
                "Revenues": _duration(
                    9_890_600_000,
                    "2025-01-01",
                    "2025-12-31",
                    filed="2026-02-06",
                ),
                "Assets": _instant(29_439_500_000, "2025-12-31", filed="2026-02-06"),
                "CashAndCashEquivalentsAtCarryingValue": _instant(
                    99_000_000,
                    "2024-12-31",
                    filed="2025-02-12",
                ),
                "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents": _instant(
                    3_008_500_000,
                    "2025-12-31",
                    filed="2026-02-06",
                ),
            }
        )
        self.assertEqual(extracted["balance_sheet_period_end"], "2025-12-31")
        self.assertEqual(extracted["cash"], 3_008_500_000)
        self.assertEqual(
            extracted["cash_tags"],
            "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        )

    def test_stale_cash_at_other_period_does_not_fill_current_period(self) -> None:
        extracted = _extract(
            {
                "Revenues": _duration(
                    100,
                    "2025-01-01",
                    "2025-12-31",
                    filed="2026-02-01",
                ),
                "Assets": _instant(100, "2025-12-31", filed="2026-02-01"),
                "CashAndCashEquivalentsAtCarryingValue": _instant(
                    50,
                    "2024-12-31",
                    filed="2025-02-01",
                ),
            }
        )
        self.assertIsNone(extracted["cash"])


class AccountsReceivableAdmissionTests(unittest.TestCase):
    def test_cost_receivables_net_current_is_not_trade_ar(self) -> None:
        extracted = _extract(
            {
                "Revenues": _duration(
                    275_235_000_000,
                    "2024-09-01",
                    "2025-08-31",
                    filed="2025-10-08",
                ),
                "Assets": _instant(77_099_000_000, "2025-08-31", filed="2025-10-08"),
                "ReceivablesNetCurrent": _instant(
                    3_203_000_000,
                    "2025-08-31",
                    filed="2025-10-08",
                ),
                "CreditAndDebitCardReceivables": _instant(
                    2_670_000_000,
                    "2025-08-31",
                    filed="2025-10-08",
                ),
            }
        )
        self.assertIsNone(extracted["accounts_receivable"])
        self.assertIsNone(extracted["accounts_receivable_tags"])

    def test_vz_notes_receivable_is_not_trade_ar(self) -> None:
        extracted = _extract(
            {
                "Revenues": _duration(
                    138_191_000_000,
                    "2025-01-01",
                    "2025-12-31",
                    filed="2026-02-17",
                ),
                "Assets": _instant(404_258_000_000, "2025-12-31", filed="2026-02-17"),
                "NotesReceivable": _instant(
                    1_000_000_000,
                    "2025-12-31",
                    filed="2026-02-17",
                ),
            }
        )
        self.assertIsNone(extracted["accounts_receivable"])


class TotalDebtPrecedenceTests(unittest.TestCase):
    def test_adsk_uses_long_term_debt_when_split_absent(self) -> None:
        extracted = _extract(
            {
                "Revenues": _duration(
                    7_206_000_000,
                    "2025-02-01",
                    "2026-01-31",
                    filed="2026-03-03",
                ),
                "Assets": _instant(12_467_000_000, "2026-01-31", filed="2026-03-03"),
                "LongTermDebt": _instant(2_500_000_000, "2026-01-31", filed="2026-03-03"),
            }
        )
        self.assertEqual(extracted["total_debt"], 2_500_000_000)
        self.assertEqual(extracted["total_debt_tags"], "LongTermDebt")

    def test_avgo_prefers_combined_total_over_components(self) -> None:
        extracted = _extract(
            {
                "Revenues": _duration(
                    63_887_000_000,
                    "2024-11-04",
                    "2025-11-02",
                    filed="2025-12-18",
                ),
                "Assets": _instant(171_092_000_000, "2025-11-02", filed="2025-12-18"),
                "LongTermDebtCurrent": _instant(
                    3_152_000_000,
                    "2025-11-02",
                    filed="2025-12-18",
                ),
                "LongTermDebtAndCapitalLeaseObligations": _instant(
                    61_984_000_000,
                    "2025-11-02",
                    filed="2025-12-18",
                ),
                "DebtLongtermAndShorttermCombinedAmount": _instant(
                    67_120_000_000,
                    "2025-11-02",
                    filed="2025-12-18",
                ),
            }
        )
        self.assertEqual(extracted["total_debt"], 67_120_000_000)
        self.assertEqual(
            extracted["total_debt_tags"],
            "DebtLongtermAndShorttermCombinedAmount",
        )

    def test_component_sum_is_not_added_to_total(self) -> None:
        extracted = _extract(
            {
                "Revenues": _duration(100, "2025-01-01", "2025-12-31", filed="2026-02-01"),
                "Assets": _instant(100, "2025-12-31", filed="2026-02-01"),
                "DebtAndCapitalLeaseObligations": _instant(
                    50,
                    "2025-12-31",
                    filed="2026-02-01",
                ),
                "DebtCurrent": _instant(10, "2025-12-31", filed="2026-02-01"),
                "LongTermDebtAndCapitalLeaseObligations": _instant(
                    40,
                    "2025-12-31",
                    filed="2026-02-01",
                ),
            }
        )
        self.assertEqual(extracted["total_debt"], 50)
        self.assertEqual(extracted["total_debt_tags"], "DebtAndCapitalLeaseObligations")

    def test_idxx_split_beats_unsplit_long_term_debt(self) -> None:
        extracted = _extract(
            {
                "Revenues": _duration(
                    4_303_702_000,
                    "2025-01-01",
                    "2025-12-31",
                    filed="2026-02-20",
                ),
                "Assets": _instant(3_350_759_000, "2025-12-31", filed="2026-02-20"),
                "LongTermDebtCurrent": _instant(
                    74_995_000,
                    "2025-12-31",
                    filed="2026-02-20",
                ),
                "LongTermDebtNoncurrent": _instant(
                    374_842_000,
                    "2025-12-31",
                    filed="2026-02-20",
                ),
                "LongTermDebt": _instant(450_000_000, "2025-12-31", filed="2026-02-20"),
            }
        )
        self.assertEqual(extracted["total_debt"], 449_837_000)
        self.assertEqual(
            extracted["total_debt_tags"],
            "LongTermDebtCurrent+LongTermDebtNoncurrent",
        )

    def test_missing_debt_stays_none_not_zero(self) -> None:
        extracted = _extract(
            {
                "Revenues": _duration(100, "2025-01-01", "2025-12-31", filed="2026-02-01"),
                "Assets": _instant(100, "2025-12-31", filed="2026-02-01"),
            }
        )
        self.assertIsNone(extracted["total_debt"])
        self.assertIsNone(extracted["total_debt_tags"])

    def test_debt_at_other_period_is_not_aligned_to_assets(self) -> None:
        extracted = _extract(
            {
                "Revenues": _duration(100, "2025-01-01", "2025-12-31", filed="2026-02-01"),
                "Assets": _instant(100, "2025-12-31", filed="2026-02-01"),
                "LongTermDebt": _instant(40, "2024-12-31", filed="2025-02-01"),
            }
        )
        self.assertIsNone(extracted["total_debt"])


class InterestBearingSecuritiesTests(unittest.TestCase):
    def test_mu_sums_afs_debt_current_and_noncurrent(self) -> None:
        extracted = _extract(
            {
                "Revenues": _duration(
                    37_378_000_000,
                    "2024-08-30",
                    "2025-08-28",
                    filed="2025-10-03",
                ),
                "Assets": _instant(82_798_000_000, "2025-08-28", filed="2025-10-03"),
                "AvailableForSaleSecuritiesDebtSecuritiesCurrent": _instant(
                    665_000_000,
                    "2025-08-28",
                    filed="2025-10-03",
                ),
                "AvailableForSaleSecuritiesDebtSecuritiesNoncurrent": _instant(
                    1_629_000_000,
                    "2025-08-28",
                    filed="2025-10-03",
                ),
            }
        )
        self.assertEqual(extracted["interest_bearing_securities"], 2_294_000_000)
        self.assertEqual(
            extracted["interest_bearing_securities_tags"],
            "AvailableForSaleSecuritiesDebtSecuritiesCurrent+"
            "AvailableForSaleSecuritiesDebtSecuritiesNoncurrent",
        )

    def test_afs_current_noncurrent_not_double_counted_with_combined(self) -> None:
        extracted = _extract(
            {
                "Revenues": _duration(100, "2025-01-01", "2025-12-31", filed="2026-02-01"),
                "Assets": _instant(100, "2025-12-31", filed="2026-02-01"),
                "AvailableForSaleSecuritiesDebtSecuritiesCurrent": _instant(
                    80,
                    "2025-12-31",
                    filed="2026-02-01",
                ),
                "AvailableForSaleSecuritiesDebtSecuritiesNoncurrent": _instant(
                    20,
                    "2025-12-31",
                    filed="2026-02-01",
                ),
                "AvailableForSaleSecuritiesDebtSecurities": _instant(
                    100,
                    "2025-12-31",
                    filed="2026-02-01",
                ),
            }
        )
        self.assertEqual(extracted["interest_bearing_securities"], 100)
        self.assertEqual(
            extracted["interest_bearing_securities_tags"],
            "AvailableForSaleSecuritiesDebtSecuritiesCurrent+"
            "AvailableForSaleSecuritiesDebtSecuritiesNoncurrent",
        )

    def test_idxx_equity_securities_are_not_interest_bearing(self) -> None:
        extracted = _extract(
            {
                "Revenues": _duration(
                    4_303_702_000,
                    "2025-01-01",
                    "2025-12-31",
                    filed="2026-02-20",
                ),
                "Assets": _instant(3_350_759_000, "2025-12-31", filed="2026-02-20"),
                "CashAndCashEquivalentsAtCarryingValue": _instant(
                    180_070_000,
                    "2025-12-31",
                    filed="2026-02-20",
                ),
                "EquitySecuritiesFvNiCurrentAndNoncurrent": _instant(
                    31_760_000,
                    "2025-12-31",
                    filed="2026-02-20",
                ),
            }
        )
        self.assertIsNone(extracted["interest_bearing_securities"])

    def test_missing_ib_stays_none_not_zero(self) -> None:
        extracted = _extract(
            {
                "Revenues": _duration(100, "2025-01-01", "2025-12-31", filed="2026-02-01"),
                "Assets": _instant(100, "2025-12-31", filed="2026-02-01"),
                "CashAndCashEquivalentsAtCarryingValue": _instant(
                    25,
                    "2025-12-31",
                    filed="2026-02-01",
                ),
            }
        )
        self.assertEqual(extracted["cash"], 25)
        self.assertIsNone(extracted["interest_bearing_securities"])
        inputs = build_participation_inputs_from_sec("IDXX", extracted).inputs
        self.assertIsNone(inputs.cash_and_interest_bearing_securities)
        self.assertIsNone(inputs.cash_plus_interest_bearing_securities)


def _adsk_facts() -> Dict[str, Any]:
    end = "2026-01-31"
    filed = "2026-03-03"
    return {
        "Revenues": _duration(7_206_000_000, "2025-02-01", end, filed=filed),
        "Assets": _instant(12_467_000_000, end, filed=filed),
        "CashAndCashEquivalentsAtCarryingValue": _instant(2_249_000_000, end, filed=filed),
        "AccountsReceivableNetCurrent": _instant(1_439_000_000, end, filed=filed),
        "LongTermDebt": _instant(2_500_000_000, end, filed=filed),
        "MarketableSecuritiesCurrent": _instant(348_000_000, end, filed=filed),
        "MarketableSecuritiesNoncurrent": _instant(376_000_000, end, filed=filed),
    }


def _avgo_facts() -> Dict[str, Any]:
    end = "2025-11-02"
    filed = "2025-12-18"
    return {
        "Revenues": _duration(63_887_000_000, "2024-11-04", end, filed=filed),
        "Assets": _instant(171_092_000_000, end, filed=filed),
        "CashAndCashEquivalentsAtCarryingValue": _instant(16_178_000_000, end, filed=filed),
        "AccountsReceivableNetCurrent": _instant(7_145_000_000, end, filed=filed),
        "LongTermDebtCurrent": _instant(3_152_000_000, end, filed=filed),
        "LongTermDebtAndCapitalLeaseObligations": _instant(61_984_000_000, end, filed=filed),
        "DebtLongtermAndShorttermCombinedAmount": _instant(67_120_000_000, end, filed=filed),
    }


def _biib_facts() -> Dict[str, Any]:
    end = "2025-12-31"
    filed = "2026-02-06"
    return {
        "Revenues": _duration(9_890_600_000, "2025-01-01", end, filed=filed),
        "Assets": _instant(29_439_500_000, end, filed=filed),
        "CashAndCashEquivalentsAtCarryingValue": _instant(
            99_000_000,
            "2024-12-31",
            filed="2025-02-12",
        ),
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents": _instant(
            3_008_500_000,
            end,
            filed=filed,
        ),
        "AccountsReceivableNetCurrent": _instant(1_342_400_000, end, filed=filed),
        "LongTermDebt": _instant(6_286_800_000, end, filed=filed),
        "DebtCurrent": _instant(0, end, filed=filed),
        "AvailableForSaleSecuritiesDebtSecurities": _instant(1_239_100_000, end, filed=filed),
        "AvailableForSaleSecuritiesDebtSecuritiesCurrent": _instant(
            807_200_000,
            end,
            filed=filed,
        ),
        "AvailableForSaleSecuritiesDebtSecuritiesNoncurrent": _instant(
            431_900_000,
            end,
            filed=filed,
        ),
    }


def _cost_facts() -> Dict[str, Any]:
    end = "2025-08-31"
    filed = "2025-10-08"
    return {
        "Revenues": _duration(275_235_000_000, "2024-09-01", end, filed=filed),
        "Assets": _instant(77_099_000_000, end, filed=filed),
        "CashAndCashEquivalentsAtCarryingValue": _instant(14_161_000_000, end, filed=filed),
        "ReceivablesNetCurrent": _instant(3_203_000_000, end, filed=filed),
        "CreditAndDebitCardReceivables": _instant(2_670_000_000, end, filed=filed),
        "LongTermDebtCurrent": _instant(75_000_000, end, filed=filed),
        "LongTermDebtNoncurrent": _instant(5_713_000_000, end, filed=filed),
        "AvailableForSaleSecuritiesDebtSecurities": _instant(786_000_000, end, filed=filed),
        "ShortTermInvestments": _instant(1_123_000_000, end, filed=filed),
    }


def _fisv_facts() -> Dict[str, Any]:
    end = "2025-12-31"
    filed = "2026-02-19"
    return {
        "Revenues": _duration(21_193_000_000, "2025-01-01", end, filed=filed),
        "Assets": _instant(80_133_000_000, end, filed=filed),
        "CashAndCashEquivalentsAtCarryingValue": _instant(798_000_000, end, filed=filed),
        "AccountsReceivableNetCurrent": _instant(3_981_000_000, end, filed=filed),
        "DebtCurrent": _instant(1_239_000_000, end, filed=filed),
        "LongTermDebtAndCapitalLeaseObligations": _instant(27_758_000_000, end, filed=filed),
        "DebtAndCapitalLeaseObligations": _instant(28_997_000_000, end, filed=filed),
    }


def _idxx_facts() -> Dict[str, Any]:
    end = "2025-12-31"
    filed = "2026-02-20"
    return {
        "Revenues": _duration(4_303_702_000, "2025-01-01", end, filed=filed),
        "Assets": _instant(3_350_759_000, end, filed=filed),
        "CashAndCashEquivalentsAtCarryingValue": _instant(180_070_000, end, filed=filed),
        "AccountsReceivableNetCurrent": _instant(552_378_000, end, filed=filed),
        "LongTermDebtCurrent": _instant(74_995_000, end, filed=filed),
        "LongTermDebtNoncurrent": _instant(374_842_000, end, filed=filed),
        "LongTermDebt": _instant(450_000_000, end, filed=filed),
    }


def _mu_facts() -> Dict[str, Any]:
    end = "2025-08-28"
    filed = "2025-10-03"
    return {
        "Revenues": _duration(37_378_000_000, "2024-08-30", end, filed=filed),
        "Assets": _instant(82_798_000_000, end, filed=filed),
        "CashAndCashEquivalentsAtCarryingValue": _instant(9_642_000_000, end, filed=filed),
        "AccountsReceivableNetCurrent": _instant(7_163_000_000, end, filed=filed),
        "DebtCurrent": _instant(560_000_000, end, filed=filed),
        "LongTermDebt": _instant(11_533_000_000, end, filed=filed),
        "LongTermDebtAndCapitalLeaseObligations": _instant(14_017_000_000, end, filed=filed),
        "DebtAndCapitalLeaseObligations": _instant(14_577_000_000, end, filed=filed),
        "AvailableForSaleSecuritiesDebtSecuritiesCurrent": _instant(
            665_000_000,
            end,
            filed=filed,
        ),
        "AvailableForSaleSecuritiesDebtSecuritiesNoncurrent": _instant(
            1_629_000_000,
            end,
            filed=filed,
        ),
    }


def _vz_facts() -> Dict[str, Any]:
    end = "2025-12-31"
    filed = "2026-02-17"
    return {
        "Revenues": _duration(138_191_000_000, "2025-01-01", end, filed=filed),
        "Assets": _instant(404_258_000_000, end, filed=filed),
        "CashAndCashEquivalentsAtCarryingValue": _instant(19_048_000_000, end, filed=filed),
        "NotesReceivable": _instant(1_000_000_000, end, filed=filed),
        "LongTermDebtCurrent": _instant(18_618_000_000, end, filed=filed),
        "LongTermDebtAndCapitalLeaseObligations": _instant(139_532_000_000, end, filed=filed),
        "DebtCurrent": _instant(18_618_000_000, end, filed=filed),
        "ShortTermBorrowings": _instant(441_000_000, end, filed=filed),
        "DebtLongtermAndShorttermCombinedAmount": _instant(158_150_000_000, end, filed=filed),
    }


class TargetExtractionAndImpactTests(unittest.TestCase):
    def _rule(self, financial, rule_id: str):
        return next(rule for rule in financial.rule_results if rule.rule_id == rule_id)

    def test_adsk_debt_resolves_and_existing_methodology_can_emit_uygun(self) -> None:
        extracted = _extract(_adsk_facts())
        self.assertEqual(extracted["total_debt"], 2_500_000_000)
        self.assertEqual(extracted["cash"], 2_249_000_000)
        self.assertEqual(extracted["accounts_receivable"], 1_439_000_000)
        self.assertEqual(extracted["interest_bearing_securities"], 724_000_000)
        inputs, financial, status = _screen("ADSK", extracted)
        self.assertEqual(inputs.cash_and_interest_bearing_securities, 2_973_000_000)
        self.assertEqual(self._rule(financial, "msci.total_debt_to_total_assets").outcome, RULE_OUTCOME_PASS)
        self.assertEqual(status, PARTICIPATION_STATUS_UYGUN)

    def test_avgo_completed_debt_fails_leverage_and_ib_stays_none(self) -> None:
        extracted = _extract(_avgo_facts())
        self.assertEqual(extracted["total_debt"], 67_120_000_000)
        self.assertIsNone(extracted["interest_bearing_securities"])
        inputs, financial, status = _screen("AVGO", extracted)
        self.assertIsNone(inputs.cash_and_interest_bearing_securities)
        self.assertEqual(self._rule(financial, "msci.total_debt_to_total_assets").outcome, RULE_OUTCOME_FAIL)
        self.assertEqual(
            self._rule(financial, "msci.cash_and_interest_bearing_to_total_assets").outcome,
            RULE_OUTCOME_INSUFFICIENT_DATA,
        )
        self.assertEqual(status, PARTICIPATION_STATUS_UYGUN_DEGIL)

    def test_biib_cash_and_debt_resolve_without_zero_fill(self) -> None:
        extracted = _extract(_biib_facts())
        self.assertEqual(extracted["cash"], 3_008_500_000)
        self.assertEqual(extracted["total_debt"], 6_286_800_000)
        self.assertEqual(extracted["interest_bearing_securities"], 1_239_100_000)
        inputs, financial, status = _screen("BIIB", extracted)
        self.assertEqual(inputs.cash_and_interest_bearing_securities, 4_247_600_000)
        self.assertEqual(self._rule(financial, "msci.total_debt_to_total_assets").outcome, RULE_OUTCOME_PASS)
        self.assertEqual(status, PARTICIPATION_STATUS_UYGUN)

    def test_cost_ar_remains_none(self) -> None:
        extracted = _extract(_cost_facts())
        self.assertIsNone(extracted["accounts_receivable"])
        self.assertEqual(extracted["total_debt"], 5_788_000_000)
        self.assertEqual(extracted["interest_bearing_securities"], 1_909_000_000)
        inputs, financial, status = _screen("COST", extracted)
        self.assertIsNone(inputs.accounts_receivable)
        self.assertEqual(
            self._rule(financial, "msci.receivables_and_cash_to_total_assets").outcome,
            RULE_OUTCOME_INSUFFICIENT_DATA,
        )
        self.assertEqual(status, PARTICIPATION_STATUS_KONTROL_ET)

    def test_fisv_completed_debt_fails_leverage_and_ib_stays_none(self) -> None:
        extracted = _extract(_fisv_facts())
        self.assertEqual(extracted["total_debt"], 28_997_000_000)
        self.assertEqual(extracted["total_debt_tags"], "DebtAndCapitalLeaseObligations")
        self.assertIsNone(extracted["interest_bearing_securities"])
        inputs, financial, status = _screen("FISV", extracted)
        self.assertIsNone(inputs.cash_and_interest_bearing_securities)
        self.assertEqual(self._rule(financial, "msci.total_debt_to_total_assets").outcome, RULE_OUTCOME_FAIL)
        self.assertEqual(status, PARTICIPATION_STATUS_UYGUN_DEGIL)

    def test_idxx_ib_remains_none_and_cash_does_not_become_cib(self) -> None:
        extracted = _extract(_idxx_facts())
        self.assertEqual(extracted["total_debt"], 449_837_000)
        self.assertEqual(extracted["cash"], 180_070_000)
        self.assertIsNone(extracted["interest_bearing_securities"])
        inputs, financial, status = _screen("IDXX", extracted)
        self.assertIsNone(inputs.cash_and_interest_bearing_securities)
        self.assertEqual(
            self._rule(financial, "msci.cash_and_interest_bearing_to_total_assets").outcome,
            RULE_OUTCOME_INSUFFICIENT_DATA,
        )
        self.assertEqual(status, PARTICIPATION_STATUS_KONTROL_ET)

    def test_mu_debt_and_ib_resolve(self) -> None:
        extracted = _extract(_mu_facts())
        self.assertEqual(extracted["total_debt"], 14_577_000_000)
        self.assertEqual(extracted["interest_bearing_securities"], 2_294_000_000)
        inputs, financial, status = _screen("MU", extracted)
        self.assertEqual(inputs.cash_and_interest_bearing_securities, 11_936_000_000)
        self.assertEqual(self._rule(financial, "msci.total_debt_to_total_assets").outcome, RULE_OUTCOME_PASS)
        self.assertEqual(status, PARTICIPATION_STATUS_UYGUN)

    def test_vz_completed_debt_fails_leverage_and_ar_ib_stay_none(self) -> None:
        extracted = _extract(_vz_facts())
        self.assertEqual(extracted["total_debt"], 158_150_000_000)
        self.assertEqual(
            extracted["total_debt_tags"],
            "DebtLongtermAndShorttermCombinedAmount",
        )
        self.assertIsNone(extracted["accounts_receivable"])
        self.assertIsNone(extracted["interest_bearing_securities"])
        inputs, financial, status = _screen("VZ", extracted)
        self.assertIsNone(inputs.accounts_receivable)
        self.assertIsNone(inputs.cash_and_interest_bearing_securities)
        self.assertEqual(self._rule(financial, "msci.total_debt_to_total_assets").outcome, RULE_OUTCOME_FAIL)
        self.assertEqual(status, PARTICIPATION_STATUS_UYGUN_DEGIL)

    def test_resolver_provenance_uses_extracted_debt_tags(self) -> None:
        extracted = _extract(_adsk_facts())
        inputs = build_participation_inputs_from_sec("ADSK", extracted).inputs
        provenance = dict(inputs.field_provenance)
        self.assertEqual(provenance["total_debt"].source_fields, ("LongTermDebt",))
        self.assertEqual(provenance["total_debt"].period, "2026-01-31")


class ExistingComponentDebtRegressionTests(unittest.TestCase):
    def test_current_plus_noncurrent_plus_short_term_borrowings(self) -> None:
        extracted = _extract(
            {
                "Revenues": _duration(100, "2025-01-01", "2025-12-31", filed="2026-02-01"),
                "Assets": _instant(200, "2025-12-31", filed="2026-02-01"),
                "LongTermDebtCurrent": _instant(10, "2025-12-31", filed="2026-02-01"),
                "LongTermDebtNoncurrent": _instant(40, "2025-12-31", filed="2026-02-01"),
                "ShortTermBorrowings": _instant(5, "2025-12-31", filed="2026-02-01"),
            }
        )
        self.assertEqual(extracted["total_debt"], 55)
        self.assertEqual(
            extracted["total_debt_tags"],
            "LongTermDebtCurrent+LongTermDebtNoncurrent+ShortTermBorrowings",
        )


if __name__ == "__main__":
    unittest.main()
