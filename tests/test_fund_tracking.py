import copy
import unittest
from unittest.mock import MagicMock, patch

from repositories.tracked_fund_repository import TrackedFundRepository
from services.fund_analysis_contract import (
    ANALYSIS_KIND_FUND,
    DATA_PROVIDER_ALPHA_VANTAGE,
    FundAnalysisResult,
    PARTICIPATION_SOURCE_CONFIGURED,
)
from services.fund_tracking_contract import prepare_tracked_fund_payload
from services.fund_tracking_service import build_tracked_fund_payload, save_tracked_fund
from services.manual_analysis_service import analyze_security, save_tracked_fund as manual_save_tracked_fund
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
        data_provider=DATA_PROVIDER_ALPHA_VANTAGE,
        expense_ratio=0.45,
        holdings_count=220,
        top10_concentration_pct=56.39,
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


class InMemoryTrackedFundStore:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}
        self.upsert_calls = 0

    def upsert_by_symbol(self, payload):
        self.upsert_calls += 1
        symbol = payload["symbol"]
        existing = self.rows.get(symbol)
        row = {
            "id": (existing or {}).get("id", f"id-{symbol}"),
            **payload,
        }
        if existing is None:
            row["created_at"] = payload.get("updated_at")
        self.rows[symbol] = row
        return row

    def get_by_symbol(self, symbol: str):
        return self.rows.get(str(symbol or "").strip().upper())


class TrackedFundContractTests(unittest.TestCase):
    def test_prepare_payload_keeps_minimum_fields_only(self) -> None:
        payload = prepare_tracked_fund_payload({
            "symbol": "spus",
            "fund_name": "SPUS ETF",
            "exchange": "NYSE Arca",
            "asset_class": "Equity",
            "participation_status": "Uygun",
            "participation_score": 100,
            "participation_source": "configured",
            "data_provider": "Alpha Vantage",
            "resolution_source": "config_etf",
            "expense_ratio": 0.45,
            "holdings_count": 220,
        })
        self.assertEqual(payload["symbol"], "SPUS")
        self.assertNotIn("expense_ratio", payload)
        self.assertNotIn("holdings_count", payload)
        self.assertIn("updated_at", payload)
        self.assertIn("last_reviewed_at", payload)

    def test_build_payload_from_fund_result(self) -> None:
        fund = sample_fund_result("HLAL")
        payload = build_tracked_fund_payload(fund, resolved_etf("HLAL"))
        self.assertEqual(payload["symbol"], "HLAL")
        self.assertEqual(payload["participation_status"], "Uygun")
        self.assertEqual(payload["participation_source"], "configured")
        self.assertNotIn("expense_ratio", payload)


class TrackedFundPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = InMemoryTrackedFundStore()
        self.repo = MagicMock()
        self.repo.upsert_by_symbol.side_effect = self.store.upsert_by_symbol
        self.repo.get_by_symbol.side_effect = self.store.get_by_symbol

    @patch("services.manual_analysis_service.analyze_fund")
    @patch("services.manual_analysis_service.resolve_symbol")
    def test_spus_analyze_zero_write(self, mock_resolve, mock_analyze_fund) -> None:
        mock_resolve.return_value = resolved_etf("SPUS")
        mock_analyze_fund.return_value = sample_fund_result("SPUS")

        with patch("services.manual_analysis_service.run_scan") as mock_run_scan:
            analyze_security(
                "SPUS",
                candidate_repo=MagicMock(get_by_symbol=MagicMock(return_value=None)),
                scan_repo=MagicMock(),
                fmp_client=MagicMock(),
                alpha_vantage_client=MagicMock(),
                tracked_fund_repo=self.repo,
                sec_client=MagicMock(),
            )
            mock_run_scan.assert_not_called()

        self.repo.upsert_by_symbol.assert_not_called()
        self.assertEqual(self.store.upsert_calls, 0)

    def test_spus_explicit_track_one_write(self) -> None:
        fund = sample_fund_result("SPUS")
        resolved = resolved_etf("SPUS")

        saved = save_tracked_fund(self.repo, fund_result=fund, resolved=resolved)

        self.assertEqual(self.repo.upsert_by_symbol.call_count, 1)
        self.assertEqual(saved["symbol"], "SPUS")
        self.assertEqual(saved["participation_status"], "Uygun")
        self.assertEqual(saved["participation_score"], 100)
        self.assertNotIn("expense_ratio", saved)

    def test_second_save_idempotent(self) -> None:
        fund = sample_fund_result("SPUS")
        resolved = resolved_etf("SPUS")

        first = save_tracked_fund(self.repo, fund_result=fund, resolved=resolved)
        second = save_tracked_fund(self.repo, fund_result=fund, resolved=resolved)

        self.assertEqual(self.repo.upsert_by_symbol.call_count, 2)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["symbol"], second["symbol"])

    def test_hlal_spsk_participation_preserved(self) -> None:
        for symbol, score in (("HLAL", 100), ("SPSK", 100)):
            fund = sample_fund_result(
                symbol,
                participation_status="Uygun",
                participation_score=score,
                participation_source=PARTICIPATION_SOURCE_CONFIGURED,
            )
            saved = save_tracked_fund(
                self.repo,
                fund_result=fund,
                resolved=resolved_etf(symbol),
            )
            self.assertEqual(saved["participation_source"], "configured")
            self.assertEqual(saved["participation_score"], score)

    def test_qqq_unresolved_cannot_save(self) -> None:
        fund = sample_fund_result("QQQ")
        with self.assertRaises(ValueError):
            save_tracked_fund(
                self.repo,
                fund_result=fund,
                resolved=resolved_unresolved("QQQ"),
            )
        self.repo.upsert_by_symbol.assert_not_called()

    def test_nvda_cannot_enter_fund_tracking(self) -> None:
        from services.symbol_resolver_service import ResolvedSecurity, RESOLUTION_HIGH

        fund = FundAnalysisResult(symbol="NVDA", analysis_kind=ANALYSIS_KIND_FUND)
        resolved = ResolvedSecurity(
            symbol="NVDA",
            company_name="NVIDIA",
            exchange="NASDAQ",
            security_type="COMMON_STOCK",
            issuer_category="OPERATING_COMPANY",
            is_etf=False,
            cik=1045810,
            resolution_source="fmp_profile",
            resolution_confidence=RESOLUTION_HIGH,
            is_equity_eligible=True,
        )
        with self.assertRaises(ValueError):
            manual_save_tracked_fund(
                self.repo,
                fund_result=fund,
                resolved=resolved,
            )
        self.repo.upsert_by_symbol.assert_not_called()

    @patch("services.manual_analysis_service.analyze_fund")
    @patch("services.manual_analysis_service.resolve_symbol")
    def test_no_candidate_writes(self, mock_resolve, mock_analyze_fund) -> None:
        mock_resolve.return_value = resolved_etf("SPUS")
        mock_analyze_fund.return_value = sample_fund_result("SPUS")
        candidate_repo = MagicMock(get_by_symbol=MagicMock(return_value=None))

        analyze_security(
            "SPUS",
            candidate_repo=candidate_repo,
            scan_repo=MagicMock(),
            fmp_client=MagicMock(),
            alpha_vantage_client=MagicMock(),
            tracked_fund_repo=self.repo,
            sec_client=MagicMock(),
        )
        save_tracked_fund(
            self.repo,
            fund_result=sample_fund_result("SPUS"),
            resolved=resolved_etf("SPUS"),
        )

        candidate_repo.upsert_by_symbol.assert_not_called()

    @patch("services.manual_analysis_service.analyze_fund")
    @patch("services.manual_analysis_service.resolve_symbol")
    def test_analyze_marks_existing_track_status(self, mock_resolve, mock_analyze_fund) -> None:
        mock_resolve.return_value = resolved_etf("SPUS")
        mock_analyze_fund.return_value = sample_fund_result("SPUS")
        self.store.upsert_by_symbol(
            prepare_tracked_fund_payload(build_tracked_fund_payload(
                sample_fund_result("SPUS"),
                resolved_etf("SPUS"),
            ))
        )

        result = analyze_security(
            "SPUS",
            candidate_repo=MagicMock(get_by_symbol=MagicMock(return_value=None)),
            scan_repo=MagicMock(),
            fmp_client=MagicMock(),
            alpha_vantage_client=MagicMock(),
            tracked_fund_repo=self.repo,
            sec_client=MagicMock(),
        )

        self.assertTrue(result.is_tracked)
        self.assertEqual(result.tracked_fund_id, "id-SPUS")


class DailyBriefIsolationTests(unittest.TestCase):
    def test_daily_brief_does_not_query_tracked_funds(self) -> None:
        with open("services/daily_brief_service.py", encoding="utf-8") as handle:
            source = handle.read()
        self.assertNotIn("tracked_funds", source)
        self.assertNotIn("TrackedFundRepository", source)

    def test_research_monitor_does_not_query_tracked_funds(self) -> None:
        with open("services/research_monitor_service.py", encoding="utf-8") as handle:
            source = handle.read()
        self.assertNotIn("tracked_funds", source)
        self.assertNotIn("TrackedFundRepository", source)


class DashboardFundTrackingSmokeTests(unittest.TestCase):
    def test_dashboard_compiles(self) -> None:
        import py_compile

        py_compile.compile("pages/1_Dashboard.py", doraise=True)

    def test_dashboard_fund_tracking_ui(self) -> None:
        with open("pages/1_Dashboard.py", encoding="utf-8") as handle:
            source = handle.read()
        fund_block = source.split('manual_result.analysis_kind == "fund"')[1].split('elif manual_result.analysis_kind == "etf_metadata"')[0]
        self.assertIn("Takibe al", fund_block)
        self.assertIn("Bu fon takip listesinde.", fund_block)
        self.assertIn("save_tracked_fund", fund_block)
        self.assertNotIn("Company Report", fund_block)

    def test_unresolved_has_no_track_button(self) -> None:
        with open("pages/1_Dashboard.py", encoding="utf-8") as handle:
            source = handle.read()
        unresolved_block = source.split('manual_result.analysis_kind == "unresolved"')[1].split("st.divider()")[0]
        self.assertNotIn("Takibe al", unresolved_block)


class TrackedFundRepositoryTests(unittest.TestCase):
    def test_repository_uses_tracked_funds_table(self) -> None:
        client = MagicMock()
        repo = TrackedFundRepository(client)
        self.assertEqual(repo.table, "tracked_funds")


if __name__ == "__main__":
    unittest.main()
