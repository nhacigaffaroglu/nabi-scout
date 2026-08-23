from __future__ import annotations

import unittest
from pathlib import Path

from services.candidate_pipeline_presentation import (
    NO_OPPORTUNITY_COPY,
    display_nabi_score,
    is_actionable_opportunity,
    nabi_score_is_displayable,
)
from services.opportunity_center_presentation import (
    ALL_CANDIDATES_LABEL,
    ALL_RESEARCH_LABEL,
    ALL_WATCHLIST_LABEL,
    CANDIDATE_POOL_PAGE,
    COMPANY_REPORT_PAGE,
    DISCOVERY_NEW,
    DISCOVERY_WAITING,
    FIRSATLAR_PAGE,
    HIDDEN_PRIMARY_LABELS,
    INSPECT_LABEL,
    KPI_DISCOVERED,
    KPI_RESEARCH,
    KPI_STRONG,
    KPI_WATCHLIST,
    MAX_TODAY_OPPORTUNITIES,
    PRIMARY_NAV_LABELS,
    RESEARCH_PAGE,
    WATCHLIST_PAGE,
    build_opportunity_center,
    discovery_user_label,
    opportunity_teaser_copy,
    present_today_opportunity_cards,
    select_today_opportunity_candidates,
)
from services.universe_expansion_contract import (
    EXPANSION_STATUS_PENDING,
    EXPANSION_STATUS_RETRYABLE,
)
from services.ui import HIDDEN_NAV_PAGE_HREFS, PRIMARY_NAV

UI = Path("services/ui.py")
HOME = Path("components/nabi_home_dashboard.py")
WEALTH = Path("pages/10_Wealth.py")
FIRSATLAR = Path("pages/5_Firsatlar.py")
PRES = Path("services/opportunity_center_presentation.py")
CENTER_UI = Path("components/opportunity_center_ui.py")
FAIRNESS = Path("tests/test_universe_expansion_queue_fairness.py")
QUEUE_REPO = Path("repositories/universe_expansion_repository.py")

INTERNAL_PAGES = (
    "pages/2_Aday_Havuzu.py",
    "pages/2_Evren_Motoru.py",
    "pages/2_Scout_Tarama.py",
    "pages/3_Research_Monitor.py",
    "pages/4_Company_Report.py",
    "pages/6_Izleme_Listesi.py",
)

PROVIDER_TOKENS = (
    "FMPClient",
    "fmp_client",
    "openai",
    "SECFinancialClient",
    "AlphaVantage",
    "TwelveData",
    "BorsaIstanbul",
)
WRITE_TOKENS = (
    "post_transaction",
    "register_asset",
    "capture_portfolio_snapshot",
    "save_planning_fx_schedule",
    "save_policy",
)
TECHNICAL_UX = (
    "PENDING",
    "RETRYABLE",
    "queue fairness",
    "backoff",
    "onboarding upsert",
    "pipeline stage",
)


def _candidate(
    symbol: str,
    *,
    decision: str = "GÜÇLÜ ADAY",
    participation: str = "Uygun",
    research: str = "YENI",
    score: float = 82.0,
    price: float | None = 120.0,
    completeness: float | None = 88.0,
    source: str = "scanner",
    thesis: str = "Kaliteli büyüme",
    risk: str = "Tek müşteri riski",
    company: str | None = None,
) -> dict:
    return {
        "symbol": symbol,
        "company_name": company or symbol,
        "decision": decision,
        "participation_status": participation,
        "research_status": research,
        "nabi_score": score,
        "current_price": price,
        "currency": "USD",
        "data_completeness": completeness,
        "data_source": source,
        "main_reason": thesis,
        "critical_risk": risk,
        "last_scanned_at": "2026-08-20T10:00:00+00:00" if completeness is not None else None,
    }


class PrimaryNavigationTests(unittest.TestCase):
    def test_visible_primary_navigation_is_three_destinations(self) -> None:
        source = UI.read_text(encoding="utf-8")
        labels = [label for _path, label, _icon in PRIMARY_NAV]
        self.assertEqual(tuple(labels), PRIMARY_NAV_LABELS)
        self.assertEqual(
            [path for path, _label, _icon in PRIMARY_NAV],
            ["pages/1_Dashboard.py", "pages/10_Wealth.py", "pages/5_Firsatlar.py"],
        )
        self.assertIn("PRIMARY_NAV", source)
        self.assertIn("Dashboard", source)
        self.assertIn("Wealth", source)
        self.assertIn("Fırsatlar", source)

    def test_technical_pages_are_not_primary_nav(self) -> None:
        source = UI.read_text(encoding="utf-8")
        for label in HIDDEN_PRIMARY_LABELS:
            self.assertNotIn(f'label="{label}"', source)
        self.assertNotIn("pages/2_Aday_Havuzu.py", source)
        self.assertNotIn("pages/2_Evren_Motoru.py", source)
        self.assertNotIn("pages/2_Scout_Tarama.py", source)
        self.assertNotIn("pages/3_Research_Monitor.py", source)
        self.assertNotIn("pages/4_Company_Report.py", source)
        self.assertNotIn("pages/6_Izleme_Listesi.py", source)
        for href in (
            "Aday_Havuzu",
            "Evren_Motoru",
            "Scout_Tarama",
            "Research_Monitor",
            "Company_Report",
            "Izleme_Listesi",
        ):
            self.assertIn(href, HIDDEN_NAV_PAGE_HREFS)

    def test_internal_pages_remain_routable(self) -> None:
        self.assertTrue(FIRSATLAR.exists())
        firsatlar = FIRSATLAR.read_text(encoding="utf-8")
        self.assertIn("prepare_protected_page", firsatlar)
        routed = PRES.read_text(encoding="utf-8") + CENTER_UI.read_text(encoding="utf-8")
        for path in INTERNAL_PAGES:
            self.assertTrue(Path(path).exists(), path)
            self.assertIn("prepare_protected_page", Path(path).read_text(encoding="utf-8"))
            self.assertIn(path, routed)


class TodayOpportunityEligibilityTests(unittest.TestCase):
    def test_incomplete_candidates_cannot_become_today_opportunities(self) -> None:
        incomplete = _candidate(
            "AA",
            decision="VERİ EKSİK",
            participation="Kontrol Et",
            score=91.0,
            completeness=10.0,
            source="universe_expansion",
        )
        self.assertFalse(is_actionable_opportunity(incomplete))
        self.assertFalse(nabi_score_is_displayable(incomplete))
        self.assertIsNone(display_nabi_score(incomplete))
        cards = present_today_opportunity_cards([incomplete])
        self.assertEqual(cards, ())

    def test_valid_aday_and_guclu_aday_can_appear(self) -> None:
        rows = [
            _candidate("MSFT", decision="GÜÇLÜ ADAY", score=88, company="Microsoft"),
            _candidate("AAPL", decision="ADAY", score=70, completeness=75, company="Apple"),
            _candidate("TRAP", decision="VERİ EKSİK", participation="Kontrol Et", score=99),
        ]
        selected = select_today_opportunity_candidates(rows)
        self.assertEqual([row["symbol"] for row in selected], ["MSFT", "AAPL"])
        cards = present_today_opportunity_cards(rows)
        self.assertEqual([card.symbol for card in cards], ["MSFT", "AAPL"])
        self.assertEqual(cards[0].decision, "GÜÇLÜ ADAY")
        self.assertEqual(cards[1].decision, "ADAY")
        self.assertEqual(cards[0].nabi_score, 88.0)
        self.assertEqual(len(cards), 2)
        self.assertLessEqual(len(cards), MAX_TODAY_OPPORTUNITIES)

    def test_discovered_and_kontrol_et_excluded(self) -> None:
        discovered = _candidate(
            "NEW",
            decision="VERİ EKSİK",
            participation="Kontrol Et",
            completeness=None,
            price=None,
            source="universe_expansion",
        )
        discovered.pop("last_scanned_at")
        kontrol = _candidate("META", participation="Kontrol Et")
        self.assertEqual(present_today_opportunity_cards([discovered, kontrol]), ())


class OpportunityCenterCompositionTests(unittest.TestCase):
    def test_hero_omits_unavailable_watchlist_and_discovery(self) -> None:
        view = build_opportunity_center(
            candidates=[_candidate("MSFT")],
            watchlist_entries=None,
            expansion_rows=None,
        )
        labels = [kpi.label for kpi in view.hero.kpis]
        self.assertIn(KPI_STRONG, labels)
        self.assertIn(KPI_RESEARCH, labels)
        self.assertNotIn(KPI_WATCHLIST, labels)
        self.assertNotIn(KPI_DISCOVERED, labels)
        self.assertIn("MSFT", view.hero.recommendation)

    def test_research_and_watchlist_and_discoveries(self) -> None:
        brief = {
            "today_actions": [
                {
                    "symbol": "NVDA",
                    "company_name": "NVIDIA",
                    "action_label": "Araştırma bekliyor",
                }
            ],
            "data_quality_updates": [
                {"symbol": "IBM", "company_name": "IBM", "summary": "Veri eksik"}
            ],
        }
        watch = [
            {
                "candidate_id": "1",
                "candidate": {
                    "id": "1",
                    "symbol": "TSLA",
                    "company_name": "Tesla",
                    "decision": "ADAY",
                },
            }
        ]
        priority = {
            "1": {
                "recent_change": {
                    "has_meaningful_change": True,
                    "changes": [{"message": "Karar ADAY oldu"}],
                }
            }
        }
        expansion = [
            {"symbol": "BIST1", "status": EXPANSION_STATUS_PENDING},
            {"symbol": "BIST2", "status": EXPANSION_STATUS_RETRYABLE},
        ]
        view = build_opportunity_center(
            candidates=[
                _candidate("MSFT", research="YENI"),
                _candidate("IBM", decision="VERİ EKSİK", completeness=20, research="TAMAMLANDI"),
            ],
            watchlist_entries=watch,
            watchlist_priority=priority,
            expansion_rows=expansion,
            brief=brief,
        )
        self.assertEqual(view.research.items[0].symbol, "NVDA")
        self.assertTrue(view.research.items[1].exceptional)
        self.assertEqual(view.watchlist.items[0].symbol, "TSLA")
        self.assertEqual(view.discoveries.items[0].status_label, DISCOVERY_NEW)
        self.assertEqual(view.discoveries.items[1].status_label, DISCOVERY_WAITING)
        self.assertEqual(discovery_user_label(EXPANSION_STATUS_PENDING), DISCOVERY_NEW)
        self.assertNotEqual(discovery_user_label(EXPANSION_STATUS_RETRYABLE), "RETRYABLE")

    def test_empty_today_uses_canonical_copy(self) -> None:
        view = build_opportunity_center(candidates=[])
        self.assertEqual(view.today, ())
        self.assertEqual(view.today_empty, NO_OPPORTUNITY_COPY)
        self.assertEqual(
            opportunity_teaser_copy(strong_count=0, qualified_count=0, empty_copy=NO_OPPORTUNITY_COPY),
            NO_OPPORTUNITY_COPY,
        )
        self.assertEqual(
            opportunity_teaser_copy(strong_count=2, qualified_count=2, empty_copy=NO_OPPORTUNITY_COPY),
            "2 güçlü yatırım fırsatı var.",
        )


class RoutingAndLanguageTests(unittest.TestCase):
    def test_company_report_drill_down(self) -> None:
        ui = CENTER_UI.read_text(encoding="utf-8")
        pres = PRES.read_text(encoding="utf-8")
        cards = Path("components/candidate_cards.py").read_text(encoding="utf-8")
        self.assertIn("INSPECT_LABEL", ui)
        self.assertIn("COMPANY_REPORT_PAGE", ui)
        self.assertIn("st.switch_page", ui)
        self.assertIn(INSPECT_LABEL, pres)
        self.assertIn(COMPANY_REPORT_PAGE, pres)
        self.assertIn(INSPECT_LABEL, cards)
        self.assertIn(COMPANY_REPORT_PAGE, cards)
        self.assertNotIn('st.page_link("pages/4_Company_Report.py"', UI.read_text(encoding="utf-8"))

    def test_secondary_views_and_advanced_tools(self) -> None:
        ui = CENTER_UI.read_text(encoding="utf-8")
        pres = PRES.read_text(encoding="utf-8")
        self.assertIn("ALL_CANDIDATES_LABEL", ui)
        self.assertIn("ALL_RESEARCH_LABEL", ui)
        self.assertIn("ALL_WATCHLIST_LABEL", ui)
        self.assertIn(ALL_CANDIDATES_LABEL, pres)
        self.assertIn(ALL_RESEARCH_LABEL, pres)
        self.assertIn(ALL_WATCHLIST_LABEL, pres)
        self.assertIn(RESEARCH_PAGE, pres)
        self.assertIn(WATCHLIST_PAGE, pres)
        self.assertIn(CANDIDATE_POOL_PAGE, pres)
        self.assertIn("expanded=False", ui)
        self.assertIn("apply_display_headers", ui)

    def test_primary_ux_avoids_technical_vocabulary(self) -> None:
        ui = CENTER_UI.read_text(encoding="utf-8")
        for token in TECHNICAL_UX:
            self.assertNotIn(token, ui)

    def test_dashboard_teaser_not_candidate_hub(self) -> None:
        home = HOME.read_text(encoding="utf-8")
        self.assertIn(FIRSATLAR_PAGE, home)
        self.assertIn("Fırsatları Gör", home)
        self.assertNotIn("pages/2_Aday_Havuzu.py", home)
        dashboard = Path("pages/1_Dashboard.py").read_text(encoding="utf-8")
        self.assertNotIn("build_daily_brief(", dashboard)
        self.assertIn("build_daily_brief(", FIRSATLAR.read_text(encoding="utf-8"))


class FreezeAndSafetyTests(unittest.TestCase):
    def test_queue_fairness_module_untouched_by_hub(self) -> None:
        self.assertTrue(FAIRNESS.exists())
        repo = QUEUE_REPO.read_text(encoding="utf-8")
        self.assertIn("PENDING always precedes due RETRYABLE", repo)
        self.assertNotIn("opportunity_center", repo)

    def test_wealth_freeze_untouched(self) -> None:
        source = WEALTH.read_text(encoding="utf-8")
        self.assertIn("render_wealth_command_center", source)
        self.assertIn("build_canonical_current_view", source)
        self.assertNotIn("opportunity_center", source)
        self.assertNotIn("5_Firsatlar", source)

    def test_no_providers_or_writes_in_hub(self) -> None:
        for path in (PRES, CENTER_UI):
            source = path.read_text(encoding="utf-8")
            for token in PROVIDER_TOKENS:
                self.assertNotIn(token, source)
            for token in WRITE_TOKENS:
                self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
