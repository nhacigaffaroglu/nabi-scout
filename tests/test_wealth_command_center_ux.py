from __future__ import annotations

import unittest
from pathlib import Path

from components.portfolio_decision_center_ui import CONTRIBUTION_PLAN_TITLE, HEALTHY_MESSAGE
from services.canonical_current_valuation import (
    canonical_current_snapshot,
    canonical_total_wealth_usd,
)
from services.fx_conversion_engine import apply_fx_to_position_rows
from services.nabi_dashboard_presentation import (
    MAX_DASHBOARD_ACTIONS,
    DashboardActionItem,
    DashboardPrioritySection,
    present_current_try_equivalent,
    present_wealth_section,
)
from services.portfolio_cockpit_presentation import (
    COST_MISSING_COPY,
    allocation_sums_to_total,
)
from services.wealth_brief_presentation import BriefPerformance
from services.wealth_command_center_presentation import (
    COMMENTARY_TITLE,
    CONTRIBUTION_NOT_RETURN,
    COST_EXCLUDED_COPY,
    DETAILS_TITLE,
    FULL_HOLDINGS_LABEL,
    GAIN_KPI_CAPTION,
    GAIN_KPI_LABEL,
    HERO_LABEL,
    HISTORY_DETAIL_TITLE,
    INCOMPARABLE_HISTORY,
    INCOMPARABLE_SCOPE,
    MAX_PRIORITY,
    MAX_TOP_HOLDINGS,
    MONTHLY_UNIT,
    NO_CONCENTRATION_COPY,
    ONE_POINT_HISTORY,
    OTHER_HOLDINGS_TEMPLATE,
    PERIOD_CHIP_LABELS,
    PLAN_GAP_INSIGHT,
    PRIMARY_PRIORITY_LIMIT,
    PRIORITY_OVERFLOW_TEMPLATE,
    PRIORITY_TITLE,
    REQUIRED_MONTHLY_CAPTION,
    SYNTHESIS_PLAN_GAP,
    SYNTHESIS_PREFIX,
    TECHNICAL_HISTORY_TITLE,
    TREEMAP_COLOR_LEGEND,
    TREEMAP_SIZE_LEGEND,
    UNREALIZED_NOTE,
    _journey,
    _priority_focus,
    build_performance_strip,
    build_portfolio_commentary,
    build_wealth_command_center,
    format_history_point_date,
    format_holdings_table_rows,
    list_comparable_periods,
    list_supported_periods,
    present_wealth_curve,
    select_latest_complete_segment,
    treemap_sums_to_total,
)
from services.wealth_goal_models import current_wealth_from_portfolio_view
from services.wealth_history_service import (
    WealthHistoryPoint,
    WealthHistoryState,
    build_wealth_history,
)
from services.wealth_institution_center_presentation import present_institution_center
from services.wealth_performance_center_presentation import (
    INSUFFICIENT_COPY,
    PerformancePeriod,
    build_performance_center,
)
from tests.test_portfolio_cockpit_ux import (
    _accounts,
    _canonical_view,
    _fx_missing,
    _fx_ok,
    _priced,
)
from tests.test_portfolio_decision_center_ui import _view
from tests.test_wealth_goal_center_ux import _dashboard
from tests.test_wealth_performance_center_ux import _snap

PAGE = Path("pages/10_Wealth.py")
PRES = Path("services/wealth_command_center_presentation.py")
UI = Path("components/wealth_command_center_ui.py")
CHARTS = Path("services/portfolio_intelligence_charts.py")
PROVIDER_TOKENS = (
    "FMPClient",
    "WealthPriceService",
    "openai",
    "SECFinancialClient",
    "AlphaVantage",
    "TwelveData",
)
WRITE_TOKENS = (
    "post_transaction",
    "register_asset",
    ".insert(",
    ".upsert(",
    ".delete(",
    "capture_portfolio_snapshot",
    "save_planning_fx_schedule",
)
PLANNING_TOKENS = (
    "from services.wealth_planning_fx",
    "usdtry_for_year",
    "PlanningFxSchedule",
)


class CommandCenterWiringTests(unittest.TestCase):
    def test_wealth_ozet_is_single_command_center(self) -> None:
        source = PAGE.read_text(encoding="utf-8")
        self.assertIn("render_wealth_command_center", source)
        self.assertIn("build_canonical_current_view", source)
        self.assertNotIn("render_portfolio_cockpit(", source)
        self.assertNotIn("render_wealth_brief(", source)
        self.assertNotIn("Portföy ayrıntıları", source)
        self.assertNotIn("col1.metric(\"Portföy\"", source)

    def test_no_provider_or_write_on_command_center(self) -> None:
        for path in (PRES, UI):
            source = path.read_text(encoding="utf-8")
            for token in PROVIDER_TOKENS:
                self.assertNotIn(token, source)
            for token in WRITE_TOKENS:
                self.assertNotIn(token, source)
            for token in PLANNING_TOKENS:
                self.assertNotIn(token, source)

    def test_turkish_primary_labels(self) -> None:
        combined = UI.read_text(encoding="utf-8") + PRES.read_text(encoding="utf-8")
        for label in (
            HERO_LABEL,
            PRIORITY_TITLE,
            "PORTFÖYÜM NEREDE?",
            "PORTFÖY HARİTASI",
            "KAZANANLAR",
            "KAYBEDENLER",
            "SERVET GELİŞİMİ",
            "2031 YOLCULUĞU",
            "EN BÜYÜK POZİSYONLAR",
            "2031 İLERLEME",
            FULL_HOLDINGS_LABEL,
            "Detaylar",
            GAIN_KPI_LABEL,
            COMMENTARY_TITLE,
        ):
            self.assertIn(label, combined)
        self.assertNotIn("TOPLAM K/Z", combined)
        self.assertIn(UNREALIZED_NOTE, combined)
        self.assertIn(GAIN_KPI_CAPTION, combined)
        self.assertIn(ONE_POINT_HISTORY, combined)
        self.assertIn(INCOMPARABLE_SCOPE, combined)
        self.assertIn(TECHNICAL_HISTORY_TITLE, combined)
        self.assertIn(REQUIRED_MONTHLY_CAPTION, combined)
        self.assertIn(CONTRIBUTION_NOT_RETURN, combined)
        self.assertIn(INCOMPARABLE_HISTORY, combined)
        self.assertIn(TREEMAP_SIZE_LEGEND, combined)
        self.assertIn(TREEMAP_COLOR_LEGEND, combined)
        self.assertNotIn("3M", combined)
        self.assertNotIn("YTD", combined)


class CanonicalIdentityTests(unittest.TestCase):
    def test_dashboard_command_goal_usd_match(self) -> None:
        view = _canonical_view()
        usd = canonical_total_wealth_usd(view)
        command = build_wealth_command_center(view, fx_service=_fx_ok(usd), accounts=_accounts())
        dashboard = present_wealth_section(
            __import__("services.canonical_current_valuation", fromlist=["canonical_wealth_metrics"]).canonical_wealth_metrics(view),
            coverage_pct=100.0,
            fx_service=_fx_ok(usd),
            performance=BriefPerformance("Aylık", None, None, None, INSUFFICIENT_COPY),
        )
        goal = current_wealth_from_portfolio_view(view)
        self.assertAlmostEqual(command.usd_total, usd)
        self.assertAlmostEqual(dashboard.usd_amount or 0.0, usd)
        self.assertAlmostEqual(float(goal.current_value_lower_bound), usd)
        self.assertAlmostEqual(command.cockpit.usd_total, usd)

    def test_try_uses_current_fx_only(self) -> None:
        usd = canonical_total_wealth_usd(_canonical_view())
        fx = _fx_ok(usd, rate=41.28)
        shown = present_current_try_equivalent(usd, fx)
        command = build_wealth_command_center(_canonical_view(), fx_service=fx)
        self.assertTrue(shown.available)
        self.assertEqual(command.cockpit.try_equivalent.amount, shown.amount)
        self.assertNotAlmostEqual(shown.amount or 0.0, usd * 51.0, places=0)

    def test_missing_fx_omits_try(self) -> None:
        command = build_wealth_command_center(_canonical_view(), fx_service=_fx_missing(79613.0))
        self.assertIsNone(command.cockpit.hero.try_label)
        self.assertTrue(command.cockpit.hero.try_limitation)


class AllocationAndTreemapTests(unittest.TestCase):
    def test_allocations_and_treemap_reconcile(self) -> None:
        view = _canonical_view()
        command = build_wealth_command_center(view, fx_service=_fx_ok(79613.0), accounts=_accounts())
        self.assertTrue(allocation_sums_to_total(command.cockpit.asset_allocation, command.usd_total))
        self.assertTrue(treemap_sums_to_total(command.treemap, command.usd_total))
        inst = present_institution_center(view, _accounts())
        self.assertAlmostEqual(inst.totals.total_value, command.usd_total)
        self.assertIn("build_holdings_treemap", CHARTS.read_text(encoding="utf-8"))


class GainAndHistoryTests(unittest.TestCase):
    def test_mixed_cost_omits_total_kz_keeps_reliable_winners(self) -> None:
        good = _priced(
            "AAPL",
            market_value=800.0,
            weight_pct=80.0,
            cost_basis=500.0,
            unrealized_pl=300.0,
        )
        missing = _priced(
            "CASH",
            market_value=200.0,
            weight_pct=20.0,
            cost_basis=0.0,
            unrealized_pl=0.0,
            asset_class="cash",
        )
        command = build_wealth_command_center(_view(priced=[good, missing]))
        self.assertIsNone(command.cockpit.hero.gain_usd_label)
        self.assertTrue(command.gain_available)
        self.assertEqual([row.symbol for row in command.winners], ["AAPL"])
        self.assertEqual(command.excluded_cost_count, 1)

    def test_missing_cost_excludes_winners(self) -> None:
        row = _priced(
            "CASH",
            market_value=1000.0,
            weight_pct=100.0,
            cost_basis=0.0,
            unrealized_pl=0.0,
            asset_class="cash",
        )
        view = _view(priced=[row])
        command = build_wealth_command_center(view)
        self.assertFalse(command.gain_available)
        self.assertEqual(command.gain_limitation, COST_MISSING_COPY)
        self.assertEqual(command.excluded_cost_count, 1)
        self.assertFalse(command.winners)
        self.assertIsNone(command.cockpit.hero.gain_usd_label)

    def test_partial_history_does_not_fabricate_return(self) -> None:
        snaps = [
            _snap("s1", "2026-07-01T00:00:00+00:00", 70000.0, complete=False),
            _snap("s2", "2026-08-01T00:00:00+00:00", 79613.0, complete=False),
        ]
        history = build_wealth_history(snaps)
        self.assertNotEqual(history.history_state, WealthHistoryState.COMPARABLE)
        self.assertIsNone(history.return_pct)
        center = build_performance_center(snaps, period=PerformancePeriod.MONTHLY)
        command = build_wealth_command_center(_canonical_view(), performance=center)
        self.assertFalse(center.sufficient)
        self.assertIsNone(command.cockpit.hero.period_label)


class PriorityCapTests(unittest.TestCase):
    def test_priority_capped_at_three(self) -> None:
        self.assertEqual(MAX_PRIORITY, 3)
        self.assertEqual(MAX_DASHBOARD_ACTIONS, 3)
        self.assertEqual(HEALTHY_MESSAGE, "Şu anda müdahale gerektiren kritik bir konu görünmüyor.")
        command = build_wealth_command_center(_canonical_view())
        self.assertLessEqual(len(command.priority.items), 3)

    def test_first_viewport_shows_one_primary_and_overflow(self) -> None:
        items = tuple(
            DashboardActionItem(f"Konu {index}", "Yüksek", "Açıklama.", ("İncele",), ())
            for index in range(1, 4)
        )
        focus = _priority_focus(DashboardPrioritySection(False, items, HEALTHY_MESSAGE))
        self.assertEqual(PRIMARY_PRIORITY_LIMIT, 1)
        self.assertEqual(focus.primary.title, "Konu 1")
        self.assertEqual(focus.overflow_count, 2)
        self.assertIn("PRIORITY_OVERFLOW_TEMPLATE", UI.read_text(encoding="utf-8"))
        self.assertIn("diğer konu", PRES.read_text(encoding="utf-8"))


class ViewportAndPolishTests(unittest.TestCase):
    def test_first_viewport_kpi_set(self) -> None:
        command = build_wealth_command_center(_canonical_view(), fx_service=_fx_ok(79613.0))
        kpi = command.viewport
        self.assertEqual(kpi.wealth_usd, command.cockpit.hero.usd_label)
        self.assertTrue(kpi.wealth_try)
        self.assertEqual(kpi.valuation_chip, "Değerleme tamam")
        self.assertTrue(kpi.largest_symbol)
        self.assertIn("2031 İLERLEME", UI.read_text(encoding="utf-8"))
        self.assertIn("render_command_viewport", UI.read_text(encoding="utf-8"))

    def test_supported_period_chips_only(self) -> None:
        snaps = [
            _snap("s1", "2026-08-22T00:00:00+00:00", 79000.0),
            _snap("s2", "2026-08-23T00:00:00+00:00", 79613.0),
        ]
        periods = list_supported_periods(snaps)
        self.assertIn(PerformancePeriod.DAILY, periods)
        self.assertNotIn("3M", PERIOD_CHIP_LABELS.values())
        labels = {PERIOD_CHIP_LABELS[period] for period in periods}
        self.assertTrue(labels.issubset({"1D", "1W", "1M", "1Y", "ALL"}))

    def test_incomparable_history_has_no_fake_return(self) -> None:
        snaps = [
            _snap("s1", "2026-07-01T00:00:00+00:00", 70000.0, complete=False),
            _snap("s2", "2026-08-01T00:00:00+00:00", 79613.0, complete=False),
        ]
        strip = build_performance_strip(build_performance_center(snaps, period=PerformancePeriod.MONTHLY))
        self.assertFalse(strip.comparable)
        self.assertIsNone(strip.period_return)
        self.assertEqual(strip.limitation, INCOMPARABLE_HISTORY)

    def test_top_holdings_limited_to_five(self) -> None:
        self.assertEqual(MAX_TOP_HOLDINGS, 5)
        command = build_wealth_command_center(_canonical_view())
        self.assertLessEqual(len(command.top_holdings), 5)
        self.assertIn(OTHER_HOLDINGS_TEMPLATE, PRES.read_text(encoding="utf-8"))
        self.assertGreaterEqual(command.other_holdings_count, 0)
        self.assertIn("toplam %", OTHER_HOLDINGS_TEMPLATE)

    def test_holdings_table_is_turkish_and_clean(self) -> None:
        command = build_wealth_command_center(_canonical_view(), accounts=_accounts())
        rows = format_holdings_table_rows(command.cockpit.holdings_table)
        self.assertEqual(
            list(rows[0].keys()),
            [
                "Sembol",
                "Varlık",
                "Kurum",
                "Adet",
                "Güncel Fiyat",
                "Piyasa Değeri",
                "Portföy Payı",
                "Maliyet",
                "K/Z",
                "K/Z %",
                "NABI Score",
                "Karar",
            ],
        )
        for row in rows:
            for value in row.values():
                self.assertIsNotNone(value)
                self.assertNotIn(str(value).lower(), {"none", "nan", "<na>"})

    def test_journey_values_come_from_goal_engine(self) -> None:
        source = PRES.read_text(encoding="utf-8")
        self.assertNotIn("2035", source)
        self.assertNotIn("500000", source)
        dashboard = _dashboard(current=canonical_current_snapshot(_canonical_view()))
        journey = _journey(dashboard)
        self.assertEqual(journey.current_label, dashboard.header.current_wealth_label)
        self.assertEqual(journey.projected_label, dashboard.current_plan.projected_wealth_label)
        self.assertEqual(journey.target_label, dashboard.header.target_wealth_label)
        if dashboard.target_date_alternative.reach_year is not None:
            self.assertEqual(journey.earliest_label, str(dashboard.target_date_alternative.reach_year))
        self.assertEqual(journey.interpretation, dashboard.nabi.copy)
        self.assertAlmostEqual(journey.current_amount or 0.0, 79613.0)

    def test_treemap_and_winners_copy(self) -> None:
        charts = CHARTS.read_text(encoding="utf-8")
        self.assertIn("tooltip", charts)
        self.assertIn("symbol", charts)
        self.assertIn("MUTED", charts)
        self.assertIn(COST_EXCLUDED_COPY, PRES.read_text(encoding="utf-8"))
        command = build_wealth_command_center(
            _view(
                priced=[
                    _priced("AAPL", market_value=800.0, weight_pct=80.0, cost_basis=500.0, unrealized_pl=300.0),
                    _priced(
                        "CASH",
                        market_value=200.0,
                        weight_pct=20.0,
                        cost_basis=0.0,
                        unrealized_pl=0.0,
                        asset_class="cash",
                    ),
                ]
            )
        )
        self.assertTrue(any(cell.cost_missing for cell in command.treemap))
        self.assertEqual([row.symbol for row in command.winners], ["AAPL"])


class HistoryComparabilityTests(unittest.TestCase):
    def test_partial_to_complete_jump_is_not_comparable_curve(self) -> None:
        points = (
            WealthHistoryPoint("2026-08-17T00:00:00+00:00", 58500.0, True),
            WealthHistoryPoint("2026-08-22T00:00:00+00:00", 58500.0, True),
            WealthHistoryPoint("2026-08-23T00:00:00+00:00", 79613.0, False),
        )
        curve = present_wealth_curve(points)
        self.assertEqual([point.priced_market_value for point in curve.comparable_points], [79613.0])
        self.assertEqual(curve.mode, "one_point")
        self.assertFalse(curve.show_chart)
        self.assertEqual(curve.compact_copy, ONE_POINT_HISTORY)
        self.assertEqual(len(curve.technical_points), 2)
        self.assertNotIn(58500.0, [point.priced_market_value for point in curve.comparable_points])

    def test_no_continuous_line_across_incomparable_scopes(self) -> None:
        points = (
            WealthHistoryPoint("2026-08-17T00:00:00+00:00", 58500.0, True),
            WealthHistoryPoint("2026-08-23T00:00:00+00:00", 79613.0, False),
        )
        comparable = select_latest_complete_segment(points)
        self.assertEqual(len(comparable), 1)
        self.assertFalse(any(point.is_partial for point in comparable))
        charts = CHARTS.read_text(encoding="utf-8")
        self.assertIn("not getattr(point, \"is_partial\", False)", charts)
        self.assertIn("curve.comparable_points", UI.read_text(encoding="utf-8"))
        self.assertNotIn("hist.curve_points,", UI.read_text(encoding="utf-8"))

    def test_one_point_comparable_history_is_compact(self) -> None:
        points = (WealthHistoryPoint("2026-08-23T12:00:00+00:00", 79613.0, False),)
        curve = present_wealth_curve(points)
        self.assertEqual(curve.mode, "one_point")
        self.assertFalse(curve.show_chart)
        self.assertEqual(curve.compact_copy, ONE_POINT_HISTORY)
        self.assertEqual(curve.latest_complete.priced_market_value, 79613.0)
        ui = UI.read_text(encoding="utf-8")
        self.assertIn("curve.compact_copy", ui)
        self.assertIn("nabi-history-compact", ui)
        self.assertIn(ONE_POINT_HISTORY, PRES.read_text(encoding="utf-8"))

    def test_two_complete_points_draw_curve(self) -> None:
        points = (
            WealthHistoryPoint("2026-08-22T00:00:00+00:00", 79000.0, False),
            WealthHistoryPoint("2026-08-23T00:00:00+00:00", 79613.0, False),
        )
        curve = present_wealth_curve(points)
        self.assertEqual(curve.mode, "curve")
        self.assertTrue(curve.show_chart)
        self.assertEqual(len(curve.comparable_points), 2)

    def test_partial_snapshots_remain_in_technical_history(self) -> None:
        points = (
            WealthHistoryPoint("2026-08-17T00:00:00+00:00", 58500.0, True),
            WealthHistoryPoint("2026-08-23T00:00:00+00:00", 79613.0, False),
        )
        curve = present_wealth_curve(points)
        self.assertEqual(curve.technical_points[0].priced_market_value, 58500.0)
        self.assertTrue(curve.technical_points[0].is_partial)
        ui = UI.read_text(encoding="utf-8")
        self.assertIn("TECHNICAL_HISTORY_TITLE", ui)
        self.assertIn("INCOMPARABLE_SCOPE", ui)
        self.assertIn("DETAILS_TITLE", ui)
        self.assertNotIn("st.expander(HISTORY_DETAIL_TITLE", ui)
        self.assertIn(TECHNICAL_HISTORY_TITLE, PRES.read_text(encoding="utf-8"))


class KpiSemanticsTests(unittest.TestCase):
    def test_primary_kz_label_is_unrealized(self) -> None:
        combined = UI.read_text(encoding="utf-8") + PRES.read_text(encoding="utf-8")
        self.assertIn(GAIN_KPI_LABEL, combined)
        self.assertIn(GAIN_KPI_CAPTION, combined)
        self.assertNotIn("TOPLAM K/Z", combined)
        command = build_wealth_command_center(_canonical_view(), fx_service=_fx_ok(79613.0))
        self.assertEqual(command.viewport.gain_usd, command.cockpit.hero.gain_usd_label)
        self.assertEqual(command.viewport.gain_pct, command.cockpit.hero.gain_pct_label)


class CompactPriorityTests(unittest.TestCase):
    def test_priority_card_is_compact_and_single_primary(self) -> None:
        items = (
            DashboardActionItem(
                CONTRIBUTION_PLAN_TITLE,
                "Yüksek",
                "2031 hedefi mevcut katkı planıyla yakalanamıyor. Uzun açıklama.",
                ("A) Aylık katkıyı artır", "B) Hedef tarihini uzat", "C) Senaryo karşılaştır"),
                ("Mevcut aylık katkı: 60,000 TL / ay", "Gerekli başlangıç aylık katkı: 177,946 TL / ay"),
            ),
            DashboardActionItem("İkinci konu", "Orta", "Açıklama.", ("İncele",), ()),
        )
        focus = _priority_focus(DashboardPrioritySection(False, items, HEALTHY_MESSAGE))
        self.assertEqual(focus.primary.title, CONTRIBUTION_PLAN_TITLE)
        self.assertEqual(focus.overflow_count, 1)
        self.assertEqual(focus.current_metric, "60,000 TL / ay")
        self.assertEqual(focus.required_metric, "177,946 TL / ay")
        self.assertEqual(focus.action_labels, ("Katkıyı artır", "Hedef tarihini uzat", "Senaryo karşılaştır"))
        ui = UI.read_text(encoding="utf-8")
        self.assertIn("render_compact_priority_card", ui)
        self.assertIn("PRIORITY_OVERFLOW_TEMPLATE", ui)
        self.assertNotIn("st.caption(item.explanation)", ui)


class PortfolioCommentaryTests(unittest.TestCase):
    def test_commentary_is_synthesis_not_raw_fact_dump(self) -> None:
        command = build_wealth_command_center(_canonical_view(), fx_service=_fx_ok(79613.0))
        commentary = build_portfolio_commentary(
            largest_symbol="TSLA",
            largest_weight_pct=14.1,
            gain_pct_label=command.cockpit.hero.gain_pct_label,
            winners=command.winners,
            losers=command.losers,
            journey=_journey(_dashboard(current=canonical_current_snapshot(_canonical_view()))),
            priority=DashboardPrioritySection(
                False,
                (DashboardActionItem(CONTRIBUTION_PLAN_TITLE, "Yüksek", "gap", (), ()),),
                HEALTHY_MESSAGE,
            ),
            decision_available=True,
            gain_available=True,
        )
        self.assertGreaterEqual(len(commentary.insights), 2)
        self.assertLessEqual(len(commentary.insights), 4)
        blob = " ".join(commentary.insights)
        self.assertNotIn("hisselerde", blob)
        self.assertNotIn("Türkiye ağırlığı", blob)
        self.assertIn(NO_CONCENTRATION_COPY, commentary.insights)
        self.assertIn(PLAN_GAP_INSIGHT, commentary.insights)
        self.assertTrue(any("taşıyor" in line for line in commentary.insights))
        self.assertLessEqual(len(commentary.chips), 3)
        self.assertTrue(any("TSLA" in chip for chip in commentary.chips))
        if command.cockpit.hero.gain_pct_label:
            self.assertTrue(any(command.cockpit.hero.gain_pct_label in chip for chip in commentary.chips))
        self.assertNotIn("2035", PRES.read_text(encoding="utf-8"))
        self.assertEqual(commentary.synthesis, SYNTHESIS_PLAN_GAP)

    def test_commentary_omits_unsupported_facts(self) -> None:
        commentary = build_portfolio_commentary(decision_available=False, gain_available=False)
        self.assertEqual(commentary.insights, ())
        self.assertIsNone(commentary.synthesis)

    def test_concentration_language_follows_di_threshold(self) -> None:
        below = build_portfolio_commentary(
            largest_symbol="TSLA",
            largest_weight_pct=14.1,
            decision_available=True,
            priority=DashboardPrioritySection(True, (), HEALTHY_MESSAGE),
        )
        self.assertIn(NO_CONCENTRATION_COPY, below.insights)
        above = build_portfolio_commentary(
            largest_symbol="TUPRS",
            largest_weight_pct=30.1,
            decision_available=True,
            priority=DashboardPrioritySection(
                False,
                (DashboardActionItem("Yoğunlaşmayı gözden geçir", "Orta", "flag", (), ()),),
                HEALTHY_MESSAGE,
            ),
        )
        self.assertTrue(any("yoğunlaşma inceleme eşiğine ulaştı" in line for line in above.insights))
        self.assertIn("yoğunlaşma incelemesi", above.synthesis or "")

    def test_goal_reach_year_comes_from_goal_engine(self) -> None:
        dashboard = _dashboard(current=canonical_current_snapshot(_canonical_view()))
        journey = _journey(dashboard)
        commentary = build_portfolio_commentary(journey=journey, decision_available=False)
        if journey.earliest_label:
            self.assertTrue(any(str(journey.earliest_label) in chip for chip in commentary.chips))
            self.assertFalse(any(str(journey.earliest_label) in line for line in commentary.insights))
        self.assertNotIn("2035", PRES.read_text(encoding="utf-8"))


class HoldingsGainTests(unittest.TestCase):
    def test_top_holdings_kz_only_when_cost_safe(self) -> None:
        command = build_wealth_command_center(
            _view(
                priced=[
                    _priced("TSLA", market_value=11236.0, weight_pct=14.1, cost_basis=10870.0, unrealized_pl=366.0),
                    _priced(
                        "CASH",
                        market_value=200.0,
                        weight_pct=2.0,
                        cost_basis=0.0,
                        unrealized_pl=0.0,
                        asset_class="cash",
                    ),
                ]
            )
        )
        by_symbol = {row.symbol: row for row in command.top_holdings}
        self.assertIsNotNone(by_symbol["TSLA"].gain_pct)
        self.assertAlmostEqual(by_symbol["TSLA"].gain_pct or 0.0, 366.0 / 10870.0 * 100.0, places=4)
        self.assertIsNone(by_symbol["CASH"].gain_pct)
        charts = CHARTS.read_text(encoding="utf-8")
        self.assertIn("gain_pct", charts)
        self.assertIn("{gain_pct:+.1f}%", charts)


class PeriodControlAndLabelTests(unittest.TestCase):
    def test_fewer_than_two_complete_snapshots_hides_period_controls(self) -> None:
        snaps = [
            _snap("s1", "2026-08-17T00:00:00+00:00", 58500.0, complete=False),
            _snap("s2", "2026-08-23T00:00:00+00:00", 79613.0, complete=True),
        ]
        command = build_wealth_command_center(_canonical_view(), snapshots=snaps)
        self.assertFalse(command.show_period_controls)
        self.assertEqual(command.supported_periods, ())
        self.assertEqual(list_comparable_periods(snaps), ())
        ui = UI.read_text(encoding="utf-8")
        self.assertIn("show_period_controls", ui)
        self.assertIn("if view.show_period_controls", ui)

    def test_two_complete_snapshots_enable_period_controls(self) -> None:
        snaps = [
            _snap("s1", "2026-08-22T00:00:00+00:00", 79000.0, complete=True),
            _snap("s2", "2026-08-23T00:00:00+00:00", 79613.0, complete=True),
        ]
        command = build_wealth_command_center(_canonical_view(), snapshots=snaps)
        self.assertTrue(command.show_period_controls)
        self.assertTrue(command.supported_periods)
        self.assertIn(PerformancePeriod.DAILY, list_comparable_periods(snaps))

    def test_winners_visible_labels_omit_weight(self) -> None:
        charts = CHARTS.read_text(encoding="utf-8")
        self.assertIn('caption = f"{gain:+,.0f}"', charts)
        self.assertIn('f"{caption} · {pct:+.1f}%"', charts)
        self.assertNotIn('·  %{weight:.1f}', charts)
        self.assertIn('title="Portföy payı"', charts)
        self.assertIn('title="Piyasa değeri"', charts)

    def test_required_monthly_label_is_unambiguous(self) -> None:
        combined = UI.read_text(encoding="utf-8") + PRES.read_text(encoding="utf-8")
        self.assertIn(REQUIRED_MONTHLY_CAPTION, combined)
        self.assertNotIn("Gerekli başlangıç", UI.read_text(encoding="utf-8"))
        dashboard = _dashboard(current=canonical_current_snapshot(_canonical_view()))
        journey = _journey(dashboard)
        self.assertIn(MONTHLY_UNIT, journey.configured_monthly_label)
        self.assertIn(MONTHLY_UNIT, journey.required_monthly_label)

    def test_other_holdings_include_aggregate_weight(self) -> None:
        command = build_wealth_command_center(_canonical_view())
        shown = sum(row.weight_pct for row in command.top_holdings)
        self.assertEqual(len(command.top_holdings), min(5, len(command.cockpit.holding_weights)))
        self.assertAlmostEqual(shown + command.other_holdings_weight, 100.0, places=0)
        self.assertIn("{weight:.1f}", OTHER_HOLDINGS_TEMPLATE)

    def test_history_point_date_is_full_turkish_month(self) -> None:
        self.assertEqual(format_history_point_date("2026-08-23T12:00:00+00:00"), "23 Ağustos 2026")


class RedundancyTests(unittest.TestCase):
    def test_no_duplicate_primary_2031_warning(self) -> None:
        ui = UI.read_text(encoding="utf-8")
        self.assertNotIn("journey.interpretation", ui)
        self.assertIn("journey.summary_line", ui)
        self.assertIn("render_compact_priority_card", ui)
        self.assertEqual(ui.count("2031 hedefi mevcut katkı planıyla"), 0)


class BistCostDisplayGuardTests(unittest.TestCase):
    def test_bist_cost_converts_with_same_fx_as_market_value(self) -> None:
        from dataclasses import replace

        from tests.test_current_valuation_integrity import _fx_service
        from tests.test_wave4_wealth_os import _position_row

        rows = []
        for symbol, native_mv, native_cost in (
            ("TUPRS", 24000.0 * 48.0, 18000.0 * 48.0),
            ("ASELS", 17000.0 * 48.0, 14000.0 * 48.0),
            ("BIMAS", 17358.0 * 48.0, 19000.0 * 48.0),
        ):
            native = _position_row(symbol=symbol, currency="TRY", market_value=native_mv, included=False)
            rows.append(
                replace(
                    native,
                    cost_basis=native_cost,
                    unrealized_pl=native_mv - native_cost,
                )
            )
        adjusted, _ = apply_fx_to_position_rows(rows, base_currency="USD", fx_service=_fx_service(48.0))
        by_symbol = {row.symbol: row for row in adjusted}
        for symbol, native_mv, native_cost in (
            ("TUPRS", 24000.0 * 48.0, 18000.0 * 48.0),
            ("ASELS", 17000.0 * 48.0, 14000.0 * 48.0),
            ("BIMAS", 17358.0 * 48.0, 19000.0 * 48.0),
        ):
            row = by_symbol[symbol]
            self.assertTrue(row.fx_converted)
            self.assertAlmostEqual(row.market_value, native_mv / 48.0, places=4)
            self.assertAlmostEqual(row.cost_basis, native_cost / 48.0, places=4)
            self.assertAlmostEqual(row.unrealized_pl, row.market_value - row.cost_basis, places=4)
            self.assertLess(abs(row.cost_basis), abs(native_cost))


if __name__ == "__main__":
    unittest.main()
