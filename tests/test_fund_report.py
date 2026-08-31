import copy
import importlib
import sys
import py_compile
import unittest
from unittest.mock import MagicMock, patch

from services.fund_analysis_contract import (
    ANALYSIS_KIND_FUND,
    FundAnalysisResult,
    FundPerformanceMetrics,
    FundRiskMetrics,
    PARTICIPATION_SOURCE_CONFIGURED,
    PRICE_RETURN_DISCLAIMER,
    RETURN_1Y_INSUFFICIENT_MESSAGE,
)
from services.fund_analysis_service import analyze_fund
from services.fund_report_service import (
    COLD_OPEN_BANNER,
    FUND_REPORT_QUERY_PARAM,
    FUND_REPORT_SESSION_LIVE,
    FUND_REPORT_SESSION_RESOLVED,
    FUND_REPORT_SESSION_SYMBOL,
    SHARIAH_DISCLAIMER,
    build_fund_report_view,
    is_valid_session_fund_handoff,
    merge_live_result_for_symbol,
    resolve_display_fund_name,
    validate_fund_report_entry,
)
from services.manual_analysis_service import analyze_security
from services.symbol_resolver_service import SECURITY_TYPE_UNRESOLVED


def resolved_etf(symbol: str):
    from services.symbol_resolver_service import ResolvedSecurity

    return ResolvedSecurity(
        symbol=symbol,
        company_name=symbol,
        exchange="NYSE Arca",
        security_type="ETF",
        issuer_category="FUND",
        is_etf=True,
        cik=None,
        resolution_source="config_etf",
        resolution_confidence="HIGH",
        is_equity_eligible=False,
    )


def resolved_equity(symbol: str):
    from services.symbol_resolver_service import ResolvedSecurity

    return ResolvedSecurity(
        symbol=symbol,
        company_name=symbol,
        exchange="NASDAQ",
        security_type="COMMON_STOCK",
        issuer_category="OPERATING",
        is_etf=False,
        cik=1045810,
        resolution_source="fmp",
        resolution_confidence="HIGH",
        is_equity_eligible=True,
    )


def resolved_unresolved(symbol: str):
    from services.symbol_resolver_service import ResolvedSecurity

    return ResolvedSecurity(
        symbol=symbol,
        company_name=f"{symbol} TRUST",
        exchange="NASDAQ",
        security_type=SECURITY_TYPE_UNRESOLVED,
        issuer_category="UNKNOWN",
        is_etf=False,
        cik=1067839,
        resolution_source="sec",
        resolution_confidence="LOW",
        is_equity_eligible=False,
    )


def sample_fund_result(symbol: str = "SPUS", **overrides) -> FundAnalysisResult:
    base = FundAnalysisResult(
        symbol=symbol,
        analysis_kind=ANALYSIS_KIND_FUND,
        fund_name=f"{symbol} ETF",
        exchange="NYSE Arca",
        asset_class="Equity",
        participation_status="Uygun",
        participation_score=100,
        participation_source=PARTICIPATION_SOURCE_CONFIGURED,
        expense_ratio=0.45,
        holdings_count=220,
        top10_concentration_pct=56.39,
        data_completeness_pct=71.4,
        analysis_confidence="MEDIUM",
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def tracked_spus_row() -> dict:
    return {
        "id": "id-spus",
        "symbol": "SPUS",
        "fund_name": "SPUS",
        "participation_status": "Uygun",
        "participation_score": 100,
        "participation_source": PARTICIPATION_SOURCE_CONFIGURED,
        "data_provider": "Alpha Vantage",
        "resolution_source": "config_etf",
        "last_reviewed_at": "2026-08-12T16:18:54+00:00",
        "updated_at": "2026-08-12T16:18:54+00:00",
    }


class FundReportServiceTests(unittest.TestCase):
    def test_tracked_spus_opens_successfully(self) -> None:
        view = build_fund_report_view(
            "SPUS",
            tracked_row=tracked_spus_row(),
        )
        self.assertTrue(view.entry_allowed)
        self.assertTrue(view.is_tracked)
        self.assertFalse(view.has_live_data)
        self.assertEqual(view.symbol, "SPUS")

    def test_same_symbol_transient_reused(self) -> None:
        live = sample_fund_result("SPUS")
        view = build_fund_report_view(
            "SPUS",
            tracked_row=tracked_spus_row(),
            live_result=live,
            resolved=resolved_etf("SPUS"),
        )
        self.assertTrue(view.has_live_data)
        self.assertEqual(view.live_result.expense_ratio, 0.45)

    def test_different_symbol_transient_ignored(self) -> None:
        live = sample_fund_result("HLAL")
        view = build_fund_report_view(
            "SPUS",
            tracked_row=tracked_spus_row(),
            live_result=live,
            resolved=resolved_etf("HLAL"),
        )
        self.assertFalse(view.has_live_data)
        self.assertIsNone(view.live_result)

    def test_merge_live_result_for_symbol(self) -> None:
        self.assertIsNone(
            merge_live_result_for_symbol("SPUS", sample_fund_result("HLAL"))
        )
        self.assertIsNotNone(
            merge_live_result_for_symbol("SPUS", sample_fund_result("SPUS"))
        )

    def test_untracked_query_param_only_blocked(self) -> None:
        allowed, reason = validate_fund_report_entry(
            "SPUS",
            tracked_row=None,
            live_result=None,
            resolved=None,
        )
        self.assertFalse(allowed)
        self.assertIn("açılamaz", reason or "")

    def test_session_fund_handoff_without_track_allowed(self) -> None:
        live = sample_fund_result("SPUS")
        allowed, _ = validate_fund_report_entry(
            "SPUS",
            tracked_row=None,
            live_result=live,
            resolved=resolved_etf("SPUS"),
        )
        self.assertTrue(allowed)

    def test_qqq_unresolved_blocked(self) -> None:
        allowed, _ = validate_fund_report_entry(
            "QQQ",
            tracked_row=None,
            live_result=sample_fund_result("QQQ"),
            resolved=resolved_unresolved("QQQ"),
            analysis_kind="fund",
        )
        self.assertFalse(allowed)

    def test_nvda_equity_blocked(self) -> None:
        allowed, _ = validate_fund_report_entry(
            "NVDA",
            tracked_row=None,
            live_result=sample_fund_result("NVDA"),
            resolved=resolved_equity("NVDA"),
            analysis_kind="fund",
        )
        self.assertFalse(allowed)

    def test_untracked_while_open_message(self) -> None:
        view = build_fund_report_view(
            "SPUS",
            tracked_row=None,
            live_result=sample_fund_result("SPUS"),
            resolved=resolved_etf("SPUS"),
            had_tracked_context=True,
        )
        self.assertTrue(any("takip listesinde değil" in msg for msg in view.state_messages))

    def test_cold_load_has_live_prompt(self) -> None:
        view = build_fund_report_view("SPUS", tracked_row=tracked_spus_row())
        self.assertIn(COLD_OPEN_BANNER, view.state_messages)

    def test_display_fund_name_uses_candidate_hint(self) -> None:
        view = build_fund_report_view(
            "SPUS",
            tracked_row=tracked_spus_row(),
            candidate_row={
                "symbol": "SPUS",
                "company_name": "SP Funds S&P 500 Sharia Industry Exclusions ETF",
            },
        )
        self.assertIn("Sharia", view.fund_name)

    def test_resolve_display_fund_name_prefers_meaningful_name(self) -> None:
        name = resolve_display_fund_name(
            "SPUS",
            tracked_row={"fund_name": "SPUS"},
            candidate_row={
                "company_name": "SP Funds S&P 500 Sharia Industry Exclusions ETF",
            },
        )
        self.assertIn("Sharia", name)

    def test_is_valid_session_fund_handoff_uses_live_kind(self) -> None:
        live = sample_fund_result("SPUS")
        self.assertTrue(
            is_valid_session_fund_handoff(
                "SPUS",
                analysis_kind=None,
                live_result=live,
                resolved=resolved_etf("SPUS"),
            )
        )


class FundReportRefreshTests(unittest.TestCase):
    @patch("services.manual_analysis_service.analyze_fund")
    @patch("services.manual_analysis_service.resolve_symbol")
    def test_refresh_uses_existing_fund_path(
        self,
        mock_resolve,
        mock_analyze_fund,
    ) -> None:
        mock_resolve.return_value = resolved_etf("SPUS")
        mock_analyze_fund.return_value = sample_fund_result("SPUS")
        tracked_repo = MagicMock()
        tracked_repo.get_by_symbol.return_value = tracked_spus_row()
        tracked_repo.upsert_by_symbol = MagicMock()

        result = analyze_security(
            "SPUS",
            candidate_repo=MagicMock(get_by_symbol=MagicMock(return_value=None)),
            scan_repo=MagicMock(),
            fmp_client=MagicMock(),
            alpha_vantage_client=MagicMock(),
            tracked_fund_repo=tracked_repo,
            sec_client=MagicMock(),
        )

        self.assertEqual(result.analysis_kind, "fund")
        mock_analyze_fund.assert_called_once()
        tracked_repo.upsert_by_symbol.assert_not_called()

    @patch("services.manual_analysis_service.analyze_fund")
    @patch("services.manual_analysis_service.resolve_symbol")
    def test_refresh_zero_write(
        self,
        mock_resolve,
        mock_analyze_fund,
    ) -> None:
        mock_resolve.return_value = resolved_etf("SPUS")
        mock_analyze_fund.return_value = sample_fund_result("SPUS")
        candidate_repo = MagicMock()
        scan_repo = MagicMock()
        tracked_repo = MagicMock()
        tracked_repo.get_by_symbol.return_value = tracked_spus_row()

        analyze_security(
            "SPUS",
            candidate_repo=candidate_repo,
            scan_repo=scan_repo,
            fmp_client=MagicMock(),
            alpha_vantage_client=MagicMock(),
            tracked_fund_repo=tracked_repo,
            sec_client=MagicMock(),
        )

        candidate_repo.upsert_by_symbol.assert_not_called()
        scan_repo.create_run.assert_not_called()
        tracked_repo.upsert_by_symbol.assert_not_called()

    @patch("services.fund_analysis_service.get_fund_cache")
    @patch("services.manual_analysis_service.analyze_fund")
    @patch("services.manual_analysis_service.resolve_symbol")
    def test_cache_hit_refresh_zero_incremental_calls(
        self,
        mock_resolve,
        mock_analyze_fund,
        mock_get_cache,
    ) -> None:
        mock_resolve.return_value = resolved_etf("SPUS")
        mock_analyze_fund.return_value = sample_fund_result("SPUS")
        mock_get_cache.return_value = MagicMock()

        alpha = MagicMock()
        analyze_security(
            "SPUS",
            candidate_repo=MagicMock(get_by_symbol=MagicMock(return_value=None)),
            scan_repo=MagicMock(),
            fmp_client=MagicMock(),
            alpha_vantage_client=alpha,
            tracked_fund_repo=MagicMock(get_by_symbol=MagicMock(return_value=tracked_spus_row())),
            sec_client=MagicMock(),
        )
        alpha.etf_profile.assert_not_called()
        alpha.time_series_daily.assert_not_called()


class FundReportProviderFailureTests(unittest.TestCase):
    def test_provider_failure_retains_tracked_metadata(self) -> None:
        live = sample_fund_result(
            "SPUS",
            price_history_status="RATE_LIMIT",
            performance_metrics=None,
            risk_metrics=None,
        )
        view = build_fund_report_view(
            "SPUS",
            tracked_row=tracked_spus_row(),
            live_result=live,
            resolved=resolved_etf("SPUS"),
        )
        self.assertTrue(view.is_tracked)
        self.assertEqual(view.tracked_row["symbol"], "SPUS")
        self.assertTrue(view.has_live_data)


class FundReportSemanticsTests(unittest.TestCase):
    def test_fund_report_page_has_no_equity_backbone(self) -> None:
        with open("pages/9_Fund_Report.py", encoding="utf-8") as handle:
            source = handle.read()
        self.assertNotIn("CandidateRepository.get_all", source)
        self.assertNotIn("company_report_candidate", source)
        self.assertNotIn("build_company_intelligence", source)
        self.assertNotIn("nabi_score", source.lower())

    def test_fund_report_page_no_auto_analyze_on_load(self) -> None:
        with open("pages/9_Fund_Report.py", encoding="utf-8") as handle:
            source = handle.read()
        pre_view = source.split("view = build_fund_report_view")[0]
        self.assertNotIn("if refresh_clicked", pre_view)
        after_refresh_click = source.split("if refresh_clicked and not turkiye_canonical:")[1]
        self.assertIn("_refresh_live_fund_analysis(requested_symbol)", after_refresh_click)

    def test_fund_report_metadata_refresh_button(self) -> None:
        with open("pages/9_Fund_Report.py", encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("Kayıtlı bilgileri güncelle", source)
        self.assertIn("refresh_tracked_fund_metadata", source)

    def test_dashboard_navigation_contract(self) -> None:
        with open("pages/1_Dashboard.py", encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("📊 Fon Raporu", source)
        self.assertIn("FUND_REPORT_SESSION_SYMBOL", source)
        self.assertIn("FUND_REPORT_QUERY_PARAM", source)
        self.assertIn("pages/9_Fund_Report.py", source)
        self.assertNotIn("company_report_candidate", source.split("_open_fund_report")[1].split("def _render_tracked_funds_section")[0])

    def test_participation_disclaimer_present(self) -> None:
        with open("components/fund_report_ui.py", encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("SHARIAH_DISCLAIMER", source)
        self.assertIn("Katılım bilgisi: Yapılandırılmış", source)

    def test_price_return_disclaimer_present(self) -> None:
        with open("components/fund_report_ui.py", encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("PRICE_RETURN_DISCLAIMER", source)
        self.assertIn("RETURN_1Y_INSUFFICIENT_MESSAGE", source)

    def test_no_chart_in_fund_report(self) -> None:
        with open("pages/9_Fund_Report.py", encoding="utf-8") as handle:
            source = handle.read()
        self.assertNotIn("line_chart", source)
        self.assertNotIn("area_chart", source)


class FundReportPerformanceRiskTests(unittest.TestCase):
    def test_insufficient_1y_suppressed_in_service_output(self) -> None:
        from services.alpha_vantage_cache import AlphaVantageFundCache
        from tests.test_fund_analysis import make_alpha_client, sample_alpha_time_series

        alpha = make_alpha_client(
            history=sample_alpha_time_series(100, anchor_end_to_today=True),
        )
        result = analyze_fund(
            resolved_etf("SPUS"),
            alpha_vantage_client=alpha,
            alpha_cache=AlphaVantageFundCache(),
        )
        self.assertIsNotNone(result.performance_metrics)
        self.assertIsNone(result.performance_metrics.return_1y_pct)
        self.assertFalse(result.performance_metrics.history_is_full_year)

    def test_spsk_fixed_income_label_guard(self) -> None:
        from tests.test_fund_analysis import make_alpha_client, sample_alpha_etf_profile

        alpha = make_alpha_client(
            profile=sample_alpha_etf_profile(
                "SPSK",
                asset_class="Fixed Income Sukuk",
            ),
        )
        result = analyze_fund(
            resolved_etf("SPSK"),
            alpha_vantage_client=alpha,
        )
        self.assertIsNotNone(result.risk_metrics)
        self.assertIsNone(result.risk_metrics.volatility_label)


class FundReportImportSmokeTests(unittest.TestCase):
    def test_fresh_process_imports(self) -> None:
        import subprocess
        import sys

        script = (
            "import importlib; "
            "importlib.import_module('services.fund_report_service'); "
            "importlib.import_module('components.fund_report_ui'); "
            "import py_compile; "
            "py_compile.compile('pages/9_Fund_Report.py', doraise=True)"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)


class FundReportColdLoadCallTests(unittest.TestCase):
    def test_cold_report_build_zero_provider_calls(self) -> None:
        tracked_repo = MagicMock()
        tracked_repo.get_by_symbol.return_value = tracked_spus_row()
        alpha = MagicMock()
        fmp = MagicMock()

        tracked_repo.get_by_symbol("SPUS")
        view = build_fund_report_view("SPUS", tracked_row=tracked_spus_row())

        self.assertTrue(view.entry_allowed)
        alpha.etf_profile.assert_not_called()
        fmp.profile.assert_not_called()
        tracked_repo.upsert_by_symbol.assert_not_called()


if __name__ == "__main__":
    unittest.main()
