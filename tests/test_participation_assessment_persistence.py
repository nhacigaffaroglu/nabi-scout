import inspect
import unittest
from dataclasses import replace
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

from components import company_report_ui
from repositories.participation_assessment_repository import (
    ParticipationAssessmentRepository,
)
from services.company_report_participation_service import (
    CompanyReportParticipationView,
    build_company_report_participation,
)
from services.participation_assessment_change_service import (
    annotate_history_with_changes,
    compare_participation_snapshots,
)
from services.participation_assessment_persistence_service import (
    build_snapshot_payload,
    compute_semantic_identity,
    fetch_participation_assessment_history,
    save_participation_assessment_snapshot,
    saved_snapshot_is_final_uygun,
    snapshot_from_row,
)
from services.participation_assessment_service import ParticipationAssessmentResult
from services.participation_intelligence_contract import (
    ASSET_KIND_EQUITY,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    METHODOLOGY_COMPLETENESS_PARTIAL,
    PARTICIPATION_SOURCE_METHODOLOGY,
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
    ParticipationAssessment,
    RULE_OUTCOME_FAIL,
    RULE_OUTCOME_INSUFFICIENT_DATA,
    RULE_OUTCOME_PASS,
)
from services.participation_business_contract import BusinessActivityScreenResult
from services.participation_financial_contract import ParticipationFinancialScreenResult


def sample_sec_financials(**overrides):
    base = {
        "total_debt": 30_000_000.0,
        "cash": 10_000_000.0,
        "total_assets": 100_000_000.0,
        "revenue": 1_000_000_000.0,
        "accounts_receivable": 15_000_000.0,
        "financial_period_end": "2025-12-31",
        "annual_periods_found": 3,
        "financial_currency": "USD",
        "financial_taxonomy": "us-gaap",
    }
    base.update(overrides)
    return base


def sample_candidate(**overrides):
    base = {
        "symbol": "AAPL",
        "company_name": "Apple Inc.",
        "sector_theme": "Technology",
        "notes": "Designs consumer electronics.",
        "cik": 320193,
        "market_cap": 3_000_000_000_000,
    }
    base.update(overrides)
    return base


def sample_assessment_result(**overrides) -> ParticipationAssessmentResult:
    assessment = ParticipationAssessment(
        symbol="AAPL",
        asset_kind=ASSET_KIND_EQUITY,
        status=PARTICIPATION_STATUS_KONTROL_ET,
        source=PARTICIPATION_SOURCE_METHODOLOGY,
        confidence=CONFIDENCE_MEDIUM,
        methodology_id="sp_us",
        methodology_version="2026.08",
        methodology_completeness=METHODOLOGY_COMPLETENESS_PARTIAL,
        data_completeness_pct=55.0,
        holdings_coverage_pct=None,
        freshness_label="recent",
    )
    financial_screen = ParticipationFinancialScreenResult(
        symbol="AAPL",
        methodology_id="sp_us",
        methodology_version="2026.08",
        rule_results=(),
        overall_outcome=RULE_OUTCOME_INSUFFICIENT_DATA,
        as_of_date=date(2025, 12, 31),
    )
    business_screen = BusinessActivityScreenResult(
        symbol="AAPL",
        methodology_id="sp_us",
        methodology_version="2026.08",
        rule_results=(),
        overall_outcome=RULE_OUTCOME_PASS,
        evidence_completeness="partial",
    )
    base = ParticipationAssessmentResult(
        symbol="AAPL",
        methodology_id="sp_us",
        resolved_methodology_version="2026.08",
        participation_assessment=assessment,
        financial_screen_result=financial_screen,
        business_screen_result=business_screen,
        provider_status=(("sec", "ok"),),
        sec_available=True,
        missing_capabilities=("assessment_persistence",),
    )
    if not overrides:
        return base
    if "participation_assessment" in overrides:
        return replace(base, participation_assessment=overrides["participation_assessment"])
    return replace(base, **overrides)


class InMemoryParticipationTable:
    def __init__(self, store: "InMemorySupabase") -> None:
        self.store = store
        self._operation = "select"
        self._payload: Optional[Dict[str, Any]] = None
        self._filters: List[tuple] = []
        self._order: Optional[tuple] = None
        self._limit: Optional[int] = None

    def select(self, columns: str):
        self._operation = "select"
        return self

    def insert(self, payload: Dict[str, Any]):
        self._operation = "insert"
        self._payload = payload
        return self

    def eq(self, field: str, value: Any):
        self._filters.append(("eq", field, value))
        return self

    def order(self, field: str, desc: bool = False):
        self._order = (field, desc)
        return self

    def limit(self, count: int):
        self._limit = count
        return self

    def execute(self):
        rows = list(self.store.snapshots)
        for op, field, value in self._filters:
            if op == "eq":
                rows = [row for row in rows if row.get(field) == value]

        if self._order is not None:
            field, desc = self._order
            rows.sort(key=lambda row: row.get(field) or "", reverse=desc)

        if self._operation == "insert":
            row = {
                "id": f"snap-{len(self.store.snapshots) + 1}",
                **self._payload,
            }
            self.store.snapshots.append(row)
            return MagicMock(data=[row])

        if self._limit is not None:
            rows = rows[: self._limit]
        return MagicMock(data=rows)


class InMemorySupabase:
    def __init__(self) -> None:
        self.snapshots: List[Dict[str, Any]] = []

    def table(self, name: str):
        if name == ParticipationAssessmentRepository.TABLE:
            return InMemoryParticipationTable(self)
        raise KeyError(name)


class ParticipationAssessmentRepositoryTests(unittest.TestCase):
    def test_append_latest_and_history(self) -> None:
        repo = ParticipationAssessmentRepository(InMemorySupabase())
        payload = build_snapshot_payload(sample_assessment_result())
        repo.append_snapshot(payload)
        latest = repo.get_latest("AAPL")
        self.assertIsNotNone(latest)
        self.assertEqual(latest["status"], PARTICIPATION_STATUS_KONTROL_ET)
        history = repo.get_recent_history("AAPL", limit=5)
        self.assertEqual(len(history), 1)

    def test_history_is_append_only(self) -> None:
        repo = ParticipationAssessmentRepository(InMemorySupabase())
        first = build_snapshot_payload(sample_assessment_result())
        second = build_snapshot_payload(
            sample_assessment_result(
                participation_assessment=ParticipationAssessment(
                    symbol="AAPL",
                    asset_kind=ASSET_KIND_EQUITY,
                    status=PARTICIPATION_STATUS_UYGUN_DEGIL,
                    source=PARTICIPATION_SOURCE_METHODOLOGY,
                    confidence=CONFIDENCE_LOW,
                    methodology_id="sp_us",
                    methodology_version="2026.08",
                )
            )
        )
        repo.append_snapshot(first)
        repo.append_snapshot(second)
        history = repo.get_recent_history("AAPL", limit=5)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["status"], PARTICIPATION_STATUS_UYGUN_DEGIL)


class ParticipationPersistenceServiceTests(unittest.TestCase):
    def test_snapshot_payload_round_trip_audit_fields(self) -> None:
        result = sample_assessment_result()
        payload = build_snapshot_payload(
            result,
            assessed_at=datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(payload["symbol"], "AAPL")
        self.assertEqual(payload["financial_overall_outcome"], RULE_OUTCOME_INSUFFICIENT_DATA)
        self.assertEqual(payload["business_overall_outcome"], RULE_OUTCOME_PASS)
        self.assertIn("assessment_payload", payload)
        self.assertNotIn("participation_score", payload["assessment_payload"])
        restored = snapshot_from_row({"id": "1", **payload})
        self.assertEqual(restored["methodology_id"], "sp_us")
        self.assertEqual(restored["missing_capabilities"], ["assessment_persistence"])

    def test_semantic_identity_stable_for_same_result(self) -> None:
        result = sample_assessment_result()
        self.assertEqual(
            compute_semantic_identity(result),
            compute_semantic_identity(result),
        )

    def test_explicit_save_only_with_available_view(self) -> None:
        repo = ParticipationAssessmentRepository(InMemorySupabase())
        view = CompanyReportParticipationView(
            symbol="AAPL",
            available=False,
            error_message="missing",
        )
        result = save_participation_assessment_snapshot(repo, view)
        self.assertFalse(result.saved)
        self.assertEqual(repo.get_recent_history("AAPL"), [])

    def test_save_appends_snapshot(self) -> None:
        repo = ParticipationAssessmentRepository(InMemorySupabase())
        view = CompanyReportParticipationView(
            symbol="AAPL",
            available=True,
            result=sample_assessment_result(),
        )
        result = save_participation_assessment_snapshot(repo, view)
        self.assertTrue(result.saved)
        self.assertEqual(len(repo.get_recent_history("AAPL")), 1)

    def test_duplicate_snapshot_is_skipped(self) -> None:
        repo = ParticipationAssessmentRepository(InMemorySupabase())
        view = CompanyReportParticipationView(
            symbol="AAPL",
            available=True,
            result=sample_assessment_result(),
        )
        first = save_participation_assessment_snapshot(repo, view)
        second = save_participation_assessment_snapshot(repo, view)
        self.assertTrue(first.saved)
        self.assertFalse(second.saved)
        self.assertTrue(second.skipped_duplicate)
        self.assertEqual(len(repo.get_recent_history("AAPL")), 1)

    def test_fetch_history_helper(self) -> None:
        repo = ParticipationAssessmentRepository(InMemorySupabase())
        repo.append_snapshot(build_snapshot_payload(sample_assessment_result()))
        history = fetch_participation_assessment_history(repo, "AAPL", limit=3)
        self.assertTrue(history.available)
        self.assertEqual(len(history.history), 1)
        self.assertEqual(history.history[0]["status"], PARTICIPATION_STATUS_KONTROL_ET)

    def test_no_final_uygun_in_saved_snapshot(self) -> None:
        snapshot = snapshot_from_row(
            build_snapshot_payload(sample_assessment_result())
        )
        self.assertFalse(saved_snapshot_is_final_uygun(snapshot))


class ParticipationChangeComparatorTests(unittest.TestCase):
    def test_detects_status_and_outcome_changes(self) -> None:
        previous = {
            "status": PARTICIPATION_STATUS_KONTROL_ET,
            "methodology_id": "sp_us",
            "methodology_version": "2026.08",
            "financial_overall_outcome": RULE_OUTCOME_INSUFFICIENT_DATA,
            "business_overall_outcome": RULE_OUTCOME_PASS,
            "confidence": CONFIDENCE_MEDIUM,
            "missing_capabilities": ["assessment_persistence"],
        }
        current = {
            **previous,
            "status": PARTICIPATION_STATUS_UYGUN_DEGIL,
            "financial_overall_outcome": RULE_OUTCOME_FAIL,
            "confidence": CONFIDENCE_LOW,
        }
        change = compare_participation_snapshots(previous, current)
        self.assertTrue(change["has_change"])
        fields = {item["field"] for item in change["changes"]}
        self.assertIn("status", fields)
        self.assertIn("financial_overall_outcome", fields)
        self.assertIn("confidence", fields)

    def test_first_snapshot_summary(self) -> None:
        change = compare_participation_snapshots(None, {"status": "Kontrol Et"})
        self.assertEqual(change["summary"], "İlk kayıt")

    def test_annotate_history_with_changes(self) -> None:
        rows = [
            {"status": "Uygun Değil", "missing_capabilities": []},
            {"status": "Kontrol Et", "missing_capabilities": ["assessment_persistence"]},
        ]
        annotated = annotate_history_with_changes(rows)
        self.assertTrue(annotated[0]["change_from_previous"]["has_change"])


class CompanyReportPersistenceIntegrationTests(unittest.TestCase):
    def test_page_has_explicit_save_not_autosave(self) -> None:
        with open("pages/4_Company_Report.py", encoding="utf-8") as handle:
            source = handle.read()
        before_save = source.split("if save_clicked:")[0]
        after_save = source.split("if save_clicked:")[1]
        self.assertNotIn("save_participation_assessment_snapshot(", before_save)
        self.assertIn("save_participation_assessment_snapshot(", after_save)

    def test_page_save_only_on_button_click(self) -> None:
        with open("pages/4_Company_Report.py", encoding="utf-8") as handle:
            source = handle.read()
        save_block = source.split("if save_clicked:")[1]
        self.assertIn("save_participation_assessment_snapshot", save_block)
        self.assertIn("if save_result.saved or save_result.skipped_duplicate:", save_block)

    def test_failed_save_does_not_rerun(self) -> None:
        with open("pages/4_Company_Report.py", encoding="utf-8") as handle:
            source = handle.read()
        save_block = source.split("if save_clicked:")[1]
        self.assertIn("if save_result.saved or save_result.skipped_duplicate:", save_block)
        self.assertNotIn(
            "persistence_failed",
            save_block.split("if save_result.saved or save_result.skipped_duplicate:")[1],
        )

    def test_ui_save_button_and_history(self) -> None:
        render_source = inspect.getsource(
            company_report_ui.render_company_report_participation_section
        )
        history_source = inspect.getsource(company_report_ui._render_participation_history)
        self.assertIn("Katılım incelemesini kaydet", render_source)
        self.assertIn("Katılım geçmişi", history_source)
        self.assertNotIn("participation_score", render_source + history_source)

    def test_non_equity_guard_before_participation(self) -> None:
        with open("pages/4_Company_Report.py", encoding="utf-8") as handle:
            source = handle.read()
        guard_index = source.index("if not is_equity_candidate_surface_eligible(candidate):")
        participation_index = source.index("participation_view = build_company_report_participation")
        self.assertLess(guard_index, participation_index)

    def test_persistence_has_no_provider_calls(self) -> None:
        import services.participation_assessment_persistence_service as module

        source = inspect.getsource(module)
        for token in ("SECFinancialClient", "company_facts", "fmp", "alpha"):
            self.assertNotIn(token, source.lower())

    def test_repository_does_not_touch_candidates(self) -> None:
        import repositories.participation_assessment_repository as module

        source = inspect.getsource(module)
        self.assertNotIn("investment_candidates", source)
        self.assertNotIn("tracked_funds", source)

    def test_build_company_report_participation_does_not_persist(self) -> None:
        import services.company_report_participation_service as module

        source = inspect.getsource(module)
        self.assertNotIn("append_snapshot", source)
        self.assertNotIn("ParticipationAssessmentRepository", source)

    def test_history_fetch_uses_repository_only(self) -> None:
        repo = ParticipationAssessmentRepository(InMemorySupabase())
        repo.append_snapshot(build_snapshot_payload(sample_assessment_result()))
        client = MagicMock()
        isolated_repo = ParticipationAssessmentRepository(client)
        isolated_repo.get_recent_history = repo.get_recent_history  # type: ignore[method-assign]
        history = fetch_participation_assessment_history(isolated_repo, "AAPL")
        self.assertTrue(history.available)
        self.assertEqual(len(history.history), 1)
        client.table.assert_not_called()


class ParticipationPersistenceHardeningTests(unittest.TestCase):
    def test_history_db_failure_returns_unavailable(self) -> None:
        repo = ParticipationAssessmentRepository(MagicMock())
        repo.get_recent_history = MagicMock(  # type: ignore[method-assign]
            side_effect=RuntimeError(
                'relation "participation_assessment_snapshots" does not exist'
            )
        )
        history = fetch_participation_assessment_history(repo, "AAPL")
        self.assertFalse(history.available)
        self.assertEqual(history.history, ())
        self.assertIn("yüklenemedi", history.message)

    def test_save_select_failure_is_graceful(self) -> None:
        repo = ParticipationAssessmentRepository(MagicMock())
        repo.get_latest = MagicMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("connection failed")
        )
        view = CompanyReportParticipationView(
            symbol="AAPL",
            available=True,
            result=sample_assessment_result(),
        )
        result = save_participation_assessment_snapshot(repo, view)
        self.assertFalse(result.saved)
        self.assertTrue(result.persistence_failed)
        repo.append_snapshot = MagicMock()  # type: ignore[method-assign]
        repo.append_snapshot.assert_not_called()

    def test_save_insert_failure_is_graceful(self) -> None:
        repo = ParticipationAssessmentRepository(MagicMock())
        repo.get_latest = MagicMock(return_value=None)  # type: ignore[method-assign]
        repo.append_snapshot = MagicMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("insert failed")
        )
        view = CompanyReportParticipationView(
            symbol="AAPL",
            available=True,
            result=sample_assessment_result(),
        )
        result = save_participation_assessment_snapshot(repo, view)
        self.assertFalse(result.saved)
        self.assertTrue(result.persistence_failed)

    def test_successful_save_unchanged(self) -> None:
        repo = ParticipationAssessmentRepository(InMemorySupabase())
        view = CompanyReportParticipationView(
            symbol="AAPL",
            available=True,
            result=sample_assessment_result(),
        )
        result = save_participation_assessment_snapshot(repo, view)
        self.assertTrue(result.saved)
        self.assertFalse(result.persistence_failed)

    def test_persistence_failure_handling_has_zero_provider_calls(self) -> None:
        import services.participation_assessment_persistence_service as module

        source = inspect.getsource(module)
        self.assertNotIn("SECFinancialClient", source)
        self.assertNotIn("company_facts", source)

    def test_ui_shows_history_unavailable_state(self) -> None:
        source = inspect.getsource(company_report_ui._render_participation_history)
        self.assertIn("unavailable_message", source)
        self.assertIn("st.info(unavailable_message)", source)

    def test_ui_shows_save_failure_warning(self) -> None:
        source = inspect.getsource(company_report_ui.render_company_report_participation_section)
        self.assertIn("save_failed", source)
        self.assertIn("st.warning(save_message)", source)


class CompanyReportParticipationRenderTests(unittest.TestCase):
    def test_render_signature_supports_history_and_save_feedback(self) -> None:
        source = inspect.getsource(company_report_ui.render_company_report_participation_section)
        self.assertIn("history:", source)
        self.assertIn("history_unavailable_message:", source)
        self.assertIn("save_message:", source)
        self.assertIn("save_failed:", source)
        self.assertIn("return save_clicked", source)

    def test_empty_history_message_present(self) -> None:
        source = inspect.getsource(company_report_ui._render_participation_history)
        self.assertIn("Henüz kaydedilmiş katılım incelemesi yok.", source)


class ExistingParticipationRegressionTests(unittest.TestCase):
    def test_company_report_evaluate_without_save(self) -> None:
        view = build_company_report_participation(
            sample_candidate(),
            sec_client=MagicMock(),
            sec_financials=sample_sec_financials(),
        )
        self.assertTrue(view.available)
        self.assertNotIn("participation_score", view.to_dict())

    def test_no_final_uygun_from_live_assessment(self) -> None:
        view = build_company_report_participation(
            sample_candidate(),
            sec_client=MagicMock(),
            sec_financials=sample_sec_financials(),
        )
        self.assertNotEqual(
            view.result.participation_assessment.status,
            PARTICIPATION_STATUS_UYGUN,
        )


if __name__ == "__main__":
    unittest.main()
