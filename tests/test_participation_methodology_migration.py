import os
import unittest
from datetime import date

from services.participation_financial_contract import ParticipationFinancialInputs
from services.participation_financial_engine import (
    evaluate_financial_rules,
    resolve_rule_threshold_pct,
)
from services.participation_intelligence_contract import (
    RULE_OUTCOME_FAIL,
    RULE_OUTCOME_INSUFFICIENT_DATA,
    RULE_OUTCOME_PASS,
)
from services.participation_methodology_audit import audit_methodology
from services.participation_methodology_registry import (
    clear_registry_cache_for_tests,
    get_default_equity_methodology,
    get_default_equity_methodology_version,
    get_methodology,
)
from services.participation_screening_context import (
    SCREENING_CONTEXT_EXISTING_CONSTITUENT,
    SCREENING_CONTEXT_NEW_ENTRY,
    SCREENING_CONTEXT_UNKNOWN_MEMBERSHIP,
)


def _msci_inputs(**overrides) -> ParticipationFinancialInputs:
    base = dict(
        symbol="TEST",
        as_of_date=date(2026, 1, 31),
        total_debt=25.0,
        cash=10.0,
        cash_and_interest_bearing_securities=36.86,
        accounts_receivable=15.0,
        total_assets=100.0,
        total_revenue=1_000.0,
    )
    base.update(overrides)
    return ParticipationFinancialInputs(**base)


class MSCIMethodologyMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_registry_cache_for_tests()

    def test_active_default_version_is_2025_05(self) -> None:
        self.assertEqual(get_default_equity_methodology_version(), "2025-05")
        active = get_default_equity_methodology()
        self.assertEqual(active.version, "2025-05")
        self.assertTrue(active.active)
        self.assertFalse(active.archived)

    def test_receivables_thresholds_by_context(self) -> None:
        methodology = get_methodology("msci_islamic_index_series")
        assert methodology is not None
        receivables_rule = next(
            rule
            for rule in methodology.rules
            if rule.rule_id == "msci.receivables_and_cash_to_total_assets"
        )
        self.assertEqual(
            resolve_rule_threshold_pct(
                receivables_rule,
                screening_context=SCREENING_CONTEXT_NEW_ENTRY,
            ),
            46.0,
        )
        self.assertEqual(
            resolve_rule_threshold_pct(
                receivables_rule,
                screening_context=SCREENING_CONTEXT_EXISTING_CONSTITUENT,
            ),
            70.0,
        )
        self.assertEqual(
            resolve_rule_threshold_pct(
                receivables_rule,
                screening_context=SCREENING_CONTEXT_UNKNOWN_MEMBERSHIP,
            ),
            46.0,
        )

    def test_old_version_receivables_threshold_remains_33_33(self) -> None:
        old = get_methodology("msci_islamic_index_series", version="2024-10")
        assert old is not None
        receivables_rule = next(
            rule
            for rule in old.rules
            if rule.rule_id == "msci.receivables_and_cash_to_total_assets"
        )
        self.assertEqual(receivables_rule.threshold_pct, 33.33)

    def test_aapl_cash_ratio_fails_under_both_versions(self) -> None:
        inputs = _msci_inputs()
        old = evaluate_financial_rules(
            "msci_islamic_index_series",
            inputs,
            screening_context=SCREENING_CONTEXT_NEW_ENTRY,
            methodology_version="2024-10",
        )
        new = evaluate_financial_rules(
            "msci_islamic_index_series",
            inputs,
            screening_context=SCREENING_CONTEXT_NEW_ENTRY,
            methodology_version="2025-05",
        )
        old_cash = next(
            r for r in old.rule_results if "cash_and_interest_bearing" in r.rule_id
        )
        new_cash = next(
            r for r in new.rule_results if "cash_and_interest_bearing" in r.rule_id
        )
        self.assertEqual(old_cash.outcome, RULE_OUTCOME_FAIL)
        self.assertEqual(new_cash.outcome, RULE_OUTCOME_FAIL)
        self.assertAlmostEqual(old_cash.ratio_pct or 0, 36.86, places=2)
        self.assertAlmostEqual(new_cash.ratio_pct or 0, 36.86, places=2)
        self.assertEqual(old_cash.threshold_pct, 33.33)
        self.assertEqual(new_cash.threshold_pct, 30.0)

    def test_aapl_receivables_passes_under_new_entry_2025_05(self) -> None:
        inputs = _msci_inputs()
        new = evaluate_financial_rules(
            "msci_islamic_index_series",
            inputs,
            screening_context=SCREENING_CONTEXT_NEW_ENTRY,
            methodology_version="2025-05",
        )
        receivables = next(
            r for r in new.rule_results if "receivables_and_cash" in r.rule_id
        )
        self.assertEqual(receivables.outcome, RULE_OUTCOME_PASS)
        self.assertAlmostEqual(receivables.ratio_pct or 0, 25.0, places=2)
        self.assertEqual(receivables.threshold_pct, 46.0)

    def test_active_methodology_self_audit_passes(self) -> None:
        result = audit_methodology("msci_islamic_index_series", version="2025-05")
        self.assertTrue(result.ok, msg=[issue.message for issue in result.issues])

    def test_archived_2024_10_reproducible(self) -> None:
        result = audit_methodology("msci_islamic_index_series", version="2024-10")
        self.assertTrue(result.ok, msg=[issue.message for issue in result.issues])


@unittest.skipUnless(
    os.environ.get("RUN_LIVE_PARTICIPATION_TESTS") == "1",
    "Set RUN_LIVE_PARTICIPATION_TESTS=1 for live symbol migration checks",
)
class LiveSymbolMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_registry_cache_for_tests()
        from services.company_report_participation_service import (
            build_company_report_participation,
        )
        from services.sec_financial_client import SECFinancialClient

        email = os.environ.get("SEC_CONTACT_EMAIL", "").strip()
        if not email:
            self.skipTest("SEC_CONTACT_EMAIL required")
        self.build = build_company_report_participation
        self.sec = SECFinancialClient(contact_email=email)
        self.lookup = {
            "AAPL": {"cik": "320193"},
            "CRM": {"cik": "1108524"},
            "AVGO": {"cik": "1730168"},
            "MSFT": {"cik": "789019"},
        }

    def _view(self, symbol: str, **candidate):
        base = {"symbol": symbol, "sector_theme": "Technology", "market_cap": 1e12}
        base.update(candidate)
        return self.build(
            base,
            sec_client=self.sec,
            sec_ticker_lookup=self.lookup,
        )

    def test_symbols_use_2025_05_methodology(self) -> None:
        view = self._view("AAPL", cik="320193")
        result = view.result
        assert result is not None
        self.assertEqual(result.resolved_methodology_version, "2025-05")


if __name__ == "__main__":
    unittest.main()
