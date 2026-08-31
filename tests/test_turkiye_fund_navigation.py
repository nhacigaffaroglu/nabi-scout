from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from services.fund_product_contract import LAYER_CASH_LIKE, PILOT_FUND_SYMBOLS, PILOT_TEFAS_FUND_CODES
from services.fund_report_service import (
    FUND_REPORT_QUERY_INSTRUMENT,
    FUND_REPORT_QUERY_MARKET,
    FUND_REPORT_QUERY_PARAM,
    FUND_REPORT_SESSION_INSTRUMENT,
    FUND_REPORT_SESSION_LIVE,
    FUND_REPORT_SESSION_MARKET,
    FUND_REPORT_SESSION_RESOLVED,
    FUND_REPORT_SESSION_SYMBOL,
    build_fund_report_view,
    resolve_display_fund_name,
    resolve_requested_identity,
    turkiye_fund_report_canonical_from_read,
    validate_fund_report_entry,
)
from services.hybrid_exposure_allocation_policy import HybridExposureAllocationPolicy
from services.official_sp_funds_product import default_official_sp_funds_provider
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.portfolio_security_decision_contract import DECISION_WATCH
from services.turkiye_fund_navigation import (
    apply_turkiye_fund_report_handoff,
    build_turkiye_fund_report_handoff,
    discard_us_etf_live_for_turkiye,
    format_turkiye_fund_nav_caption,
    is_turkiye_fund_nav_identity,
    list_turkiye_fund_nav_items,
    nav_item_is_cash_instrument,
    us_etf_live_handoff_allowed,
)
from services.turkiye_fund_snapshot_reader import (
    REASON_STALE_FI,
    SnapshotReadError,
    is_turkiye_fund_production_identity,
    read_turkiye_fund_canonical,
)
from services.wealth_new_money_allocation import allocate_new_money
from tests.test_fund_report import resolved_etf, sample_fund_result
from tests.test_turkiye_fund_8e import FROZEN_FI
from tests.test_turkiye_fund_snapshot_read import _seeded_repos

DASHBOARD = Path("pages/1_Dashboard.py")
FUND_REPORT = Path("pages/9_Fund_Report.py")
NAV = Path("services/turkiye_fund_navigation.py")
REPORT = Path("services/fund_report_service.py")
COMPANY = Path("pages/4_Company_Report.py")
PORTFOLIO = Path("pages/11_Portfolio_Intelligence.py")
NEW_MONEY = Path("services/wealth_new_money_allocation.py")
BIST = Path("services/bist_refresh_contract.py")
BIST_ORCH = Path("services/bist_refresh_orchestrator.py")
US_SI = Path("services/security_intelligence_engine.py")


class TurkiyeFundNavigationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.part_repo, self.fi_repo = _seeded_repos()

    def _canonical(self, code: str):
        return read_turkiye_fund_canonical(
            participation_repo=self.part_repo,
            snapshot_repo=self.fi_repo,
            fund_code=code,
            is_holding=True,
            portfolio_weight=5.0,
        )

    def test_catalog_is_ais_zpe_iat_fund_tr(self) -> None:
        items = {item.fund_code: item for item in list_turkiye_fund_nav_items()}
        self.assertEqual(tuple(items), PILOT_TEFAS_FUND_CODES)
        for code in ("AIS", "ZPE", "IAT"):
            item = items[code]
            self.assertEqual(item.instrument, "FUND")
            self.assertEqual(item.market, "TR")
            self.assertEqual(item.identity_label, "FUND/TR")
            self.assertTrue(is_turkiye_fund_nav_identity(code, instrument="FUND", market="TR"))
            self.assertFalse(us_etf_live_handoff_allowed(code, instrument="FUND", market="TR"))

    def test_dashboard_ais_zpe_iat_navigation_surface(self) -> None:
        source = DASHBOARD.read_text(encoding="utf-8")
        self.assertIn("_render_turkiye_fund_section", source)
        self.assertIn("list_turkiye_fund_nav_items", source)
        self.assertIn("apply_turkiye_fund_report_handoff", source)
        self.assertIn("Türkiye Fonları · FUND/TR", source)
        turkiye_block = source.split("def _render_turkiye_fund_section")[1].split(
            "def _render_tracked_funds_section"
        )[0]
        self.assertIn("📊 Fon Raporu", turkiye_block)
        self.assertNotIn("Analiz et / Güncelle", turkiye_block)
        self.assertNotIn("Takipten çıkar", turkiye_block)
        self.assertNotIn("analyze_security", turkiye_block)
        self.assertNotIn("FMPClient", turkiye_block)
        self.assertNotIn("allocate_new_money", turkiye_block)
        self.assertIn("_render_turkiye_fund_section()", source)

    def test_fund_tr_identity_handoff(self) -> None:
        for code in PILOT_TEFAS_FUND_CODES:
            session = {
                FUND_REPORT_SESSION_LIVE: object(),
                FUND_REPORT_SESSION_RESOLVED: object(),
                "fund_report_had_tracked_context": True,
            }
            query: dict[str, str] = {}
            handoff = apply_turkiye_fund_report_handoff(session, query, code)
            self.assertEqual(handoff.fund_code, code)
            self.assertEqual(handoff.instrument, "FUND")
            self.assertEqual(handoff.market, "TR")
            self.assertEqual(handoff.page, "pages/9_Fund_Report.py")
            self.assertFalse(handoff.attach_us_etf_live)
            self.assertFalse(handoff.invokes_live_analysis)
            self.assertFalse(handoff.live_refresh)
            self.assertEqual(session[FUND_REPORT_SESSION_SYMBOL], code)
            self.assertEqual(session[FUND_REPORT_SESSION_INSTRUMENT], "FUND")
            self.assertEqual(session[FUND_REPORT_SESSION_MARKET], "TR")
            self.assertFalse(session["fund_report_had_tracked_context"])
            self.assertNotIn(FUND_REPORT_SESSION_LIVE, session)
            self.assertNotIn(FUND_REPORT_SESSION_RESOLVED, session)
            self.assertEqual(query[FUND_REPORT_QUERY_PARAM], code)
            self.assertEqual(query[FUND_REPORT_QUERY_INSTRUMENT], "FUND")
            self.assertEqual(query[FUND_REPORT_QUERY_MARKET], "TR")
            symbol, instrument, market = resolve_requested_identity(
                session_symbol=session[FUND_REPORT_SESSION_SYMBOL],
                query_symbol=query[FUND_REPORT_QUERY_PARAM],
                session_instrument=session[FUND_REPORT_SESSION_INSTRUMENT],
                query_instrument=query[FUND_REPORT_QUERY_INSTRUMENT],
                session_market=session[FUND_REPORT_SESSION_MARKET],
                query_market=query[FUND_REPORT_QUERY_MARKET],
            )
            self.assertEqual((symbol, instrument, market), (code, "FUND", "TR"))

    def test_no_etf_us_handoff(self) -> None:
        live = sample_fund_result("AIS")
        resolved = resolved_etf("AIS")
        view = build_fund_report_view(
            "AIS",
            tracked_row=None,
            live_result=live,
            resolved=resolved,
            analysis_kind="fund",
            instrument="FUND",
            market="TR",
            canonical=turkiye_fund_report_canonical_from_read(self._canonical("AIS")),
        )
        self.assertIsNone(view.live_result)
        self.assertIsNone(view.resolved)
        self.assertFalse(view.has_live_data)
        self.assertEqual(view.instrument, "FUND")
        self.assertEqual(view.market, "TR")
        stripped = discard_us_etf_live_for_turkiye(
            "AIS",
            instrument="FUND",
            market="TR",
            live_result=live,
            resolved=resolved,
            analysis_kind="fund",
        )
        self.assertEqual(stripped, (None, None, None))
        self.assertTrue(us_etf_live_handoff_allowed("SPUS"))
        self.assertFalse(is_turkiye_fund_nav_identity("SPUS", instrument="FUND", market="US"))
        self.assertFalse(is_turkiye_fund_production_identity("AIS", instrument="ETF", market="US"))

    def test_no_fmp_tefas_kap_or_evaluator_on_navigation(self) -> None:
        forbidden = (
            "FMPClient",
            "evaluate_official_fund_intelligence",
            "evaluate_official_fund_decision",
            "evaluate_turkiye_fund_participation",
            "default_tefas_fund_provider",
            "allocate_new_money",
            "run_turkiye_fund_refresh",
            "from services.manual_analysis_service import",
            "from services.fmp_client import",
            "from services.official_tefas_product import",
        )
        nav_source = NAV.read_text(encoding="utf-8")
        for token in forbidden:
            self.assertNotIn(token, nav_source)
        with patch(
            "services.fmp_client.FMPClient.from_streamlit_secrets",
            side_effect=AssertionError("fmp_called"),
        ), patch(
            "services.official_tefas_product.default_tefas_fund_provider",
            side_effect=AssertionError("tefas_called"),
        ), patch(
            "services.official_kap_pdr_evidence.load_captured_pdr_holdings",
            side_effect=AssertionError("kap_called"),
        ), patch(
            "services.fund_intelligence_engine.evaluate_official_fund_intelligence",
            side_effect=AssertionError("fi_called"),
        ), patch(
            "services.wealth_new_money_allocation.allocate_new_money",
            side_effect=AssertionError("new_money_called"),
        ):
            for code in PILOT_TEFAS_FUND_CODES:
                apply_turkiye_fund_report_handoff({}, {}, code)
                build_turkiye_fund_report_handoff(code)
                list_turkiye_fund_nav_items()

    def test_snapshot_only_fund_report_handoff(self) -> None:
        for code, (score, state) in FROZEN_FI.items():
            allowed, reason = validate_fund_report_entry(code, tracked_row=None)
            self.assertTrue(allowed)
            self.assertIsNone(reason)
            view = build_fund_report_view(
                code,
                tracked_row=None,
                instrument="FUND",
                market="TR",
                canonical=turkiye_fund_report_canonical_from_read(self._canonical(code)),
            )
            self.assertTrue(view.entry_allowed)
            self.assertEqual(view.canonical.participation_status, PARTICIPATION_STATUS_UYGUN)
            self.assertEqual(view.canonical.fi_score, score)
            self.assertEqual(view.canonical.fi_state, state)
            self.assertEqual(view.canonical.eight_e, DECISION_WATCH)
            self.assertFalse(view.canonical.increase_allowed)
            self.assertEqual(view.canonical.instrument, "FUND")
            self.assertEqual(view.canonical.market, "TR")
        page = FUND_REPORT.read_text(encoding="utf-8")
        self.assertIn("load_turkiye_fund_canonical_from_client", page)
        self.assertIn("discard_us_etf_live_for_turkiye", page)
        self.assertIn("apply_turkiye_fund_report_handoff", DASHBOARD.read_text(encoding="utf-8"))
        self.assertNotIn("evaluate_official_fund_intelligence", REPORT.read_text(encoding="utf-8"))

    def test_ais_cash_like_but_instrument_fund(self) -> None:
        items = {item.fund_code: item for item in list_turkiye_fund_nav_items()}
        ais = items["AIS"]
        self.assertEqual(ais.exposure_label, LAYER_CASH_LIKE)
        self.assertEqual(ais.instrument, "FUND")
        self.assertNotEqual(ais.instrument, "CASH")
        self.assertFalse(nav_item_is_cash_instrument(ais))
        caption = format_turkiye_fund_nav_caption(ais)
        self.assertIn("nakit benzeri ekonomik maruziyet", caption)
        self.assertIn("enstrüman FUND", caption)
        self.assertNotIn("CASH", caption)
        view = build_fund_report_view(
            "AIS",
            tracked_row=None,
            instrument="FUND",
            market="TR",
            canonical=turkiye_fund_report_canonical_from_read(self._canonical("AIS")),
        )
        self.assertEqual(view.canonical.exposure, LAYER_CASH_LIKE)
        self.assertEqual(view.instrument, "FUND")
        self.assertEqual(view.fund_name, "Ak Portföy Para Piyasası Katılım Fonu")
        self.assertNotEqual(view.fund_name.upper(), "CASH")
        self.assertEqual(resolve_display_fund_name("AIS"), "Ak Portföy Para Piyasası Katılım Fonu")

    def test_missing_snapshot_fail_closed_no_live_refresh(self) -> None:
        view = build_fund_report_view(
            "AIS",
            tracked_row=None,
            live_result=sample_fund_result("AIS"),
            resolved=resolved_etf("AIS"),
            instrument="FUND",
            market="TR",
            canonical_unavailable_reason=REASON_STALE_FI,
        )
        self.assertTrue(view.entry_allowed)
        self.assertIsNone(view.canonical)
        self.assertIsNone(view.live_result)
        self.assertEqual(view.canonical_unavailable_reason, REASON_STALE_FI)
        self.assertIn(REASON_STALE_FI, " ".join(view.state_messages))
        self.assertIn("Live recompute is blocked", " ".join(view.state_messages))
        page = FUND_REPORT.read_text(encoding="utf-8")
        self.assertIn("disabled=turkiye_canonical", page)
        self.assertIn("if refresh_clicked and not turkiye_canonical", page)
        with self.assertRaises(SnapshotReadError):
            read_turkiye_fund_canonical(
                participation_repo=type("P", (), {"get_recent_history": lambda *_a, **_k: []})(),
                snapshot_repo=self.fi_repo,
                fund_code="AIS",
            )

    def test_sp_funds_navigation_unchanged(self) -> None:
        dashboard = DASHBOARD.read_text(encoding="utf-8")
        tracked = dashboard.split("def _render_tracked_funds_section")[1]
        self.assertIn("Analiz et / Güncelle", tracked)
        self.assertIn("Takipten çıkar", tracked)
        self.assertIn("📊 Fon Raporu", tracked)
        for symbol in PILOT_FUND_SYMBOLS:
            self.assertFalse(is_turkiye_fund_nav_identity(symbol))
            self.assertTrue(us_etf_live_handoff_allowed(symbol))
            allowed, _reason = validate_fund_report_entry(symbol, tracked_row=None)
            self.assertFalse(allowed)
        catalog_codes = {item.fund_code for item in list_turkiye_fund_nav_items()}
        self.assertTrue(set(PILOT_FUND_SYMBOLS).isdisjoint(catalog_codes))
        self.assertTrue(default_official_sp_funds_provider().supports("SPUS"))
        self.assertIn("us_etf_live_handoff_allowed", dashboard)

    def test_bist_and_us_equity_navigation_unchanged(self) -> None:
        dashboard = DASHBOARD.read_text(encoding="utf-8")
        self.assertIn("pages/4_Company_Report.py", dashboard)
        self.assertIn("company_report_candidate", dashboard)
        self.assertIn("analyze_security", dashboard)
        company = COMPANY.read_text(encoding="utf-8")
        self.assertIn("is_equity_candidate_surface_eligible", company)
        self.assertIn("pages/4_Company_Report.py", PORTFOLIO.read_text(encoding="utf-8"))
        from services.asset_capability_contract import route_report_page

        self.assertEqual(route_report_page("equity"), "company_report")
        self.assertFalse(is_turkiye_fund_nav_identity("ASELS", instrument="EQUITY", market="TR"))
        self.assertFalse(is_turkiye_fund_nav_identity("AAPL", instrument="EQUITY", market="US"))
        self.assertIn("ASELS", BIST.read_text(encoding="utf-8"))
        self.assertIn("persist_si", BIST_ORCH.read_text(encoding="utf-8"))
        self.assertNotIn("AIS", US_SI.read_text(encoding="utf-8"))

    def test_new_money_never_called(self) -> None:
        for path in (NAV, DASHBOARD, FUND_REPORT, REPORT):
            self.assertNotIn("allocate_new_money", path.read_text(encoding="utf-8"))
        self.assertFalse(HybridExposureAllocationPolicy().enabled)
        self.assertTrue(callable(allocate_new_money))
        self.assertNotIn("AIS", NEW_MONEY.read_text(encoding="utf-8"))
        with patch(
            "services.wealth_new_money_allocation.allocate_new_money",
            side_effect=AssertionError("new_money_called"),
        ) as mocked:
            apply_turkiye_fund_report_handoff({}, {}, "AIS")
            mocked.assert_not_called()

    def test_wrong_identity_cannot_build_handoff(self) -> None:
        with self.assertRaises(ValueError):
            build_turkiye_fund_report_handoff("SPUS")
        with self.assertRaises(ValueError):
            build_turkiye_fund_report_handoff("ASELS")


if __name__ == "__main__":
    unittest.main()
