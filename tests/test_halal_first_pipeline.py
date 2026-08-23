from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

from repositories.scan_repository import ScanRepository
from repositories.universe_expansion_repository import UniverseExpansionRepository
from services.candidate_identity import merge_preserving_enriched
from services.candidate_pipeline_presentation import is_actionable_opportunity
from services.opportunity_center_presentation import (
    count_research_waiting,
    discovery_user_label,
    present_discovery_summary,
)
from services.participation_authority import (
    SCANNER_SKIP_MISSING,
    SCANNER_SKIP_REJECTED,
    SCANNER_SKIP_UNRESOLVED,
    overlay_authoritative_participation,
    resolve_authoritative_participation,
)
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)
from services.scan_runner_service import run_scan
from services.scan_universe_service import filter_scanner_eligible_rows
from services.universe_expansion_contract import (
    ERROR_CATEGORY_DATA_INSUFFICIENT,
    EXPANSION_STATUS_COMPLETED,
    EXPANSION_STATUS_PENDING,
    EXPANSION_STATUS_RETRYABLE,
)
from services.universe_expansion_onboarding_service import (
    OnboardingResult,
    onboarding_final_status,
)
from tests.test_scan_runner import InMemoryScanStore, analyze_result, symbol_row

ROOT = Path(__file__).resolve().parents[1]
WEALTH = Path("pages/10_Wealth.py")
DASHBOARD = Path("pages/1_Dashboard.py")
FIRSATLAR = Path("pages/5_Firsatlar.py")
UI = Path("services/ui.py")
SCORE = Path("services/nabi_score_v4.py")
REGISTRY = Path("config/participation_methodologies/registry.json")
BUSINESS = Path("config/participation_business_rules.json")
SIC = Path("config/participation_sic_mapping.json")
CATALOG = Path("config/participation_catalog.py")


def _now() -> datetime:
    return datetime(2026, 8, 23, 6, 0, tzinfo=timezone.utc)


class AuthorityResolverTests(unittest.TestCase):
    def test_snapshot_overrides_stale_candidate_rejected(self) -> None:
        authority = resolve_authoritative_participation(
            "AAPL",
            candidate={"symbol": "AAPL", "participation_status": "Kontrol Et"},
            snapshot={"symbol": "AAPL", "status": "Uygun Değil"},
        )
        self.assertTrue(authority.rejected)
        self.assertFalse(authority.scanner_allowed)
        self.assertEqual(authority.skip_reason, SCANNER_SKIP_REJECTED)
        overlaid = overlay_authoritative_participation(
            {"symbol": "AAPL", "participation_status": "Kontrol Et", "decision": "ARAŞTIR"},
            {"status": "Uygun Değil"},
        )
        self.assertEqual(overlaid["participation_status"], PARTICIPATION_STATUS_UYGUN_DEGIL)
        self.assertFalse(is_actionable_opportunity(overlaid))

    def test_snapshot_overrides_stale_candidate_approved(self) -> None:
        authority = resolve_authoritative_participation(
            "CRM",
            candidate={"symbol": "CRM", "participation_status": "Kontrol Et"},
            snapshot={"symbol": "CRM", "status": "Uygun"},
        )
        self.assertTrue(authority.approved)
        self.assertTrue(authority.scanner_allowed)
        overlaid = overlay_authoritative_participation(
            {"symbol": "CRM", "participation_status": "Kontrol Et"},
            {"status": "Uygun"},
        )
        self.assertEqual(overlaid["participation_status"], PARTICIPATION_STATUS_UYGUN)

    def test_jnj_style_snapshot_uygun(self) -> None:
        authority = resolve_authoritative_participation(
            "JNJ",
            candidate={"symbol": "JNJ", "participation_status": "Kontrol Et"},
            snapshot={"participation_status": "Uygun"},
        )
        self.assertTrue(authority.approved)


class ScannerFirewallTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = InMemoryScanStore()
        self.scan_repo = ScanRepository(self.store)
        self.candidate_repo = MagicMock()
        self.fmp_client = MagicMock()
        self.sec_client = MagicMock()
        self.engine = MagicMock()
        self.engine.analyze.return_value = analyze_result("X")

    def _run(self, symbol: str, **kwargs):
        self.engine.analyze.return_value = analyze_result(symbol)
        kwargs.setdefault("participation_defaults", {})
        return run_scan(
            symbols=[symbol_row(symbol)],
            universe_name="halal-test",
            scan_repo=self.scan_repo,
            candidate_repo=self.candidate_repo,
            fmp_client=self.fmp_client,
            sec_client=self.sec_client,
            engine=self.engine,
            inter_symbol_pause_seconds=0,
            **kwargs,
        )

    def test_uygun_scanner_allowed(self) -> None:
        result = self._run(
            "CRM",
            participation_snapshots={"CRM": {"status": "Uygun"}},
        )
        self.engine.analyze.assert_called_once()
        self.assertEqual(result.participation_skipped, 0)

    def test_uygun_degil_scanner_not_called(self) -> None:
        result = self._run(
            "AAPL",
            existing_candidates={"AAPL": {"participation_status": "Kontrol Et"}},
            participation_snapshots={"AAPL": {"status": "Uygun Değil"}},
        )
        self.engine.analyze.assert_not_called()
        self.assertEqual(result.participation_skip_reasons["AAPL"], SCANNER_SKIP_REJECTED)
        self.candidate_repo.upsert_by_symbol.assert_not_called()

    def test_kontrol_et_scanner_not_called(self) -> None:
        result = self._run(
            "NVDA",
            existing_candidates={"NVDA": {"participation_status": "Kontrol Et"}},
        )
        self.engine.analyze.assert_not_called()
        self.assertEqual(result.participation_skip_reasons["NVDA"], SCANNER_SKIP_UNRESOLVED)

    def test_missing_scanner_not_called(self) -> None:
        result = self._run("NEWCO")
        self.engine.analyze.assert_not_called()
        self.assertEqual(result.participation_skip_reasons["NEWCO"], SCANNER_SKIP_MISSING)

    def test_etf_catalog_remains_allowed(self) -> None:
        result = self._run(
            "SPUS",
            participation_defaults={"SPUS": ("Uygun", 100)},
        )
        self.engine.analyze.assert_called_once()
        self.assertEqual(result.participation_skipped, 0)


class ExpansionTerminalTests(unittest.TestCase):
    def test_uygun_degil_terminal_without_upsert(self) -> None:
        status = onboarding_final_status(
            OnboardingResult(
                symbol="JPM",
                success=False,
                participation_status="Uygun Değil",
                research_allowed=False,
                error_category=ERROR_CATEGORY_DATA_INSUFFICIENT,
                candidate_upserted=False,
            ),
            budget_rate_limited=False,
        )
        self.assertEqual(status, EXPANSION_STATUS_COMPLETED)

    def test_kontrol_et_without_upsert_remains_retryable(self) -> None:
        status = onboarding_final_status(
            OnboardingResult(
                symbol="ORCL",
                success=False,
                participation_status="Kontrol Et",
                research_allowed=False,
                error_category=ERROR_CATEGORY_DATA_INSUFFICIENT,
                candidate_upserted=False,
            ),
            budget_rate_limited=False,
        )
        self.assertEqual(status, EXPANSION_STATUS_RETRYABLE)

    def test_rejected_rows_do_not_consume_safety_cap(self) -> None:
        repo = UniverseExpansionRepository()
        rejected = repo.upsert_pending("JPM", source_universe="sp500", priority=1)
        repo.finalize(
            rejected["id"],
            {
                "status": EXPANSION_STATUS_RETRYABLE,
                "participation_status": "Uygun Değil",
                "next_retry_at": _now().isoformat(),
            },
        )
        pending = repo.upsert_pending("ADP", source_universe="nasdaq", priority=50)
        eligible = repo.list_eligible(_now(), limit=10)
        symbols = [row["symbol"] for row in eligible]
        self.assertIn(pending["symbol"], symbols)
        self.assertNotIn("JPM", symbols)

    def test_pending_fairness_still_precedes_retryable(self) -> None:
        repo = UniverseExpansionRepository()
        retry = repo.upsert_pending("ORCL", source_universe="retry", priority=1)
        repo.finalize(
            retry["id"],
            {
                "status": EXPANSION_STATUS_RETRYABLE,
                "participation_status": "Kontrol Et",
                "next_retry_at": _now().isoformat(),
            },
        )
        pending = repo.upsert_pending("ADP", source_universe="fresh", priority=50)
        eligible = repo.list_eligible(_now(), limit=10)
        self.assertEqual(eligible[0]["symbol"], pending["symbol"])
        self.assertEqual(eligible[1]["symbol"], "ORCL")


class ResearchWaitingTests(unittest.TestCase):
    def test_research_waiting_counts_uygun_only(self) -> None:
        rows = [
            {
                "symbol": "CRM",
                "participation_status": "Uygun",
                "research_status": "YENI",
                "research_allowed": True,
            },
            {
                "symbol": "NVDA",
                "participation_status": "Kontrol Et",
                "research_status": "YENI",
            },
            {
                "symbol": "AAPL",
                "participation_status": "Uygun Değil",
                "research_status": "YENI",
            },
        ]
        self.assertEqual(count_research_waiting(rows), 1)

    def test_default_yeni_kontrol_et_does_not_count(self) -> None:
        self.assertEqual(
            count_research_waiting(
                [{"symbol": "META", "participation_status": "Kontrol Et", "research_status": "YENI"}]
            ),
            0,
        )

    def test_missing_does_not_count(self) -> None:
        self.assertEqual(
            count_research_waiting([{"symbol": "NEW", "research_status": "YENI"}]),
            0,
        )


class OpportunityAndDiscoveryTests(unittest.TestCase):
    def test_unresolved_and_rejected_cannot_be_opportunities(self) -> None:
        kontrol = {
            "symbol": "TSM",
            "decision": "GÜÇLÜ ADAY",
            "current_price": 120,
            "nabi_score": 85,
            "data_completeness": 92,
            "last_scanned_at": "2026-08-23T00:00:00+00:00",
            "participation_status": "Kontrol Et",
        }
        rejected = dict(kontrol, symbol="AAPL", participation_status="Uygun Değil")
        self.assertFalse(is_actionable_opportunity(kontrol))
        self.assertFalse(is_actionable_opportunity(rejected))

    def test_rejected_not_evaluation_waiting(self) -> None:
        self.assertEqual(
            discovery_user_label(EXPANSION_STATUS_RETRYABLE, "Uygun Değil"),
            "Değerlendirme tamamlanamadı",
        )
        summary = present_discovery_summary(
            [
                {"symbol": "JPM", "status": EXPANSION_STATUS_RETRYABLE, "participation_status": "Uygun Değil"},
                {"symbol": "ADP", "status": EXPANSION_STATUS_PENDING},
                {"symbol": "ORCL", "status": EXPANSION_STATUS_RETRYABLE, "participation_status": "Kontrol Et"},
            ],
            [],
        )
        self.assertEqual(summary.new_count, 1)
        self.assertEqual(summary.waiting_count, 1)
        self.assertNotIn("JPM", [item.symbol for item in summary.items])


class DailyUniverseFilterTests(unittest.TestCase):
    def test_rejected_name_filtered_from_automatic_scan(self) -> None:
        rows = [
            {"symbol": "AAPL"},
            {"symbol": "SPUS"},
            {"symbol": "CRM"},
        ]
        kept = filter_scanner_eligible_rows(
            rows,
            snapshots={"AAPL": {"status": "Uygun Değil"}, "CRM": {"status": "Uygun"}},
            catalog_defaults={"SPUS": ("Uygun", 100)},
        )
        symbols = [row["symbol"] for row in kept]
        self.assertEqual(symbols, ["SPUS", "CRM"])
        self.assertNotIn("AAPL", symbols)


class MergeParticipationOverwriteTests(unittest.TestCase):
    def test_authoritative_status_overwrites_stale_candidate(self) -> None:
        patch = merge_preserving_enriched(
            {"symbol": "AAPL", "participation_status": "Kontrol Et", "current_price": 180},
            {"symbol": "AAPL", "participation_status": "Uygun Değil"},
        )
        self.assertEqual(patch["participation_status"], "Uygun Değil")
        self.assertNotIn("current_price", patch)


class FreezeAndReligiousSafetyTests(unittest.TestCase):
    def test_nabi_score_formula_unchanged(self) -> None:
        source = SCORE.read_text(encoding="utf-8")
        self.assertIn("del participation_score, participation_status", source)
        self.assertNotIn("PARTICIPATION_STATUS_UYGUN_DEGIL", source)

    def test_methodology_thresholds_unchanged(self) -> None:
        registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
        msci = next(
            item
            for item in registry["methodologies"]
            if item["methodology_id"] == "msci_islamic_index_series"
            and item.get("financial_screen_complete_methodology") is True
        )
        by_id = {rule["rule_id"]: rule for rule in msci["rules"]}
        self.assertEqual(by_id["msci.total_debt_to_total_assets"]["threshold_pct"], 30.0)
        self.assertEqual(
            by_id["msci.cash_and_interest_bearing_to_total_assets"]["threshold_pct"],
            30.0,
        )
        self.assertEqual(by_id["msci.receivables_and_cash_to_total_assets"]["threshold_pct"], 46.0)
        self.assertEqual(by_id["msci.non_permissible_revenue"]["threshold_pct"], 5.0)

    def test_business_and_sic_files_present(self) -> None:
        self.assertTrue(BUSINESS.exists())
        self.assertTrue(SIC.exists())
        self.assertIn("SPUS", CATALOG.read_text(encoding="utf-8"))

    def test_wealth_dashboard_firsatlar_freeze(self) -> None:
        self.assertIn("render_wealth_command_center", WEALTH.read_text(encoding="utf-8"))
        self.assertNotIn("nabi_today_presentation", WEALTH.read_text(encoding="utf-8"))
        self.assertIn("render_nabi_home_executive", DASHBOARD.read_text(encoding="utf-8"))
        self.assertIn("Gelişmiş Araçlar", DASHBOARD.read_text(encoding="utf-8"))
        self.assertIn("render_opportunity_center", FIRSATLAR.read_text(encoding="utf-8"))
        self.assertIn('("pages/1_Dashboard.py", "Dashboard"', UI.read_text(encoding="utf-8"))
        self.assertIn('("pages/10_Wealth.py", "Wealth"', UI.read_text(encoding="utf-8"))
        self.assertIn('("pages/5_Firsatlar.py", "Fırsatlar"', UI.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
