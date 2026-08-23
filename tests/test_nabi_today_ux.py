from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from components.portfolio_decision_center_ui import (
    CONTRIBUTION_PLAN_TITLE,
    HEALTHY_MESSAGE,
    ActionCenterPresentation,
    PresentedAction,
)
from services.candidate_pipeline_presentation import (
    NO_OPPORTUNITY_COPY,
    is_actionable_opportunity,
)
from services.fx_rate_contract import FxConversionResult
from services.nabi_dashboard_presentation import present_wealth_section
from services.nabi_today_presentation import (
    ACTION_FINISH_RESEARCH,
    ACTION_REVIEW_ALLOCATION,
    ACTION_REVIEW_PLAN,
    ACTION_WAIT_HISTORY,
    FIRSATLARI_GOR_LABEL,
    KPI_GAIN,
    KPI_OPPORTUNITIES,
    KPI_PROGRESS,
    KPI_WEALTH,
    MAX_TODAY_ACTIONS,
    NEW_MONEY_ADVISORY,
    NEW_MONEY_READY_TEMPLATE,
    WEALTH_OPEN_LABEL,
    WEALTH_PAGE,
    WHY_PLAN_GAP,
    build_nabi_today_executive,
    build_today_actions,
    build_today_synthesis,
    count_qualified_opportunities,
    present_new_money_preview,
    present_performance_preview,
)
from services.opportunity_center_presentation import FIRSATLAR_PAGE
from services.total_wealth_service import TotalWealthMetrics
from services.wealth_brief_presentation import BriefNewMoney
from services.wealth_command_center_presentation import (
    NO_CONCENTRATION_COPY,
    ONE_POINT_HISTORY,
    PLAN_GAP_INSIGHT,
    PRIMARY_PRIORITY_LIMIT,
)
from services.wealth_performance_center_presentation import INSUFFICIENT_COPY

PRES = Path("services/nabi_today_presentation.py")
HOME = Path("components/nabi_home_dashboard.py")
DASHBOARD = Path("pages/1_Dashboard.py")
WEALTH = Path("pages/10_Wealth.py")
FIRSATLAR = Path("pages/5_Firsatlar.py")
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
    "RETRYABLE",
    "research_status",
    "decision_code",
    "completeness",
)


def _candidate(
    symbol: str,
    *,
    decision: str = "GÜÇLÜ ADAY",
    participation: str = "Uygun",
    score: float = 82.0,
    price: float | None = 120.0,
    completeness: float | None = 88.0,
    thesis: str = "Kaliteli büyüme",
) -> dict:
    return {
        "symbol": symbol,
        "company_name": symbol,
        "decision": decision,
        "participation_status": participation,
        "research_status": "YENI",
        "nabi_score": score,
        "current_price": price,
        "data_completeness": completeness,
        "data_source": "scanner",
        "main_reason": thesis,
        "last_scanned_at": "2026-08-20T10:00:00+00:00" if completeness is not None else None,
    }


def _metrics() -> TotalWealthMetrics:
    return TotalWealthMetrics(
        base_currency="USD",
        total_wealth=79613.0,
        invested_assets=79613.0,
        cash=0.0,
        equity=79613.0,
        funds_etfs=0.0,
        other_assets=0.0,
        unconverted_value=0.0,
        unpriced_count=0,
        participation_covered_pct=100.0,
        research_covered_pct=100.0,
        fx_conversion_coverage_pct=100.0,
        partial_total=False,
        limitation="",
    )


def _fx_ok() -> FxConversionResult:
    return FxConversionResult(
        native_amount=79613,
        native_currency="USD",
        converted_amount=79613 * 48.1,
        base_currency="TRY",
        rate_used=48.1,
        rate_date="2026-08-22",
        converted=True,
        unavailable=False,
        stale=False,
        limitation="",
    )


def _wealth_section():
    fx = MagicMock()
    fx.convert_amount.return_value = _fx_ok()
    performance = SimpleNamespace(return_label=None, period_label="Aylık")
    return present_wealth_section(
        _metrics(),
        coverage_pct=100.0,
        fx_service=fx,
        performance=performance,
    )


def _cockpit(*, gain_usd="$14,894", gain_pct="+23.0%", symbol="TSLA", weight=14.1):
    return SimpleNamespace(
        hero=SimpleNamespace(
            largest_symbol=symbol,
            largest_weight_label=f"%{weight:.1f}",
            largest_weight_pct=weight,
            gain_usd_label=gain_usd,
            gain_pct_label=gain_pct,
        ),
        holding_weights=(SimpleNamespace(symbol=symbol, weight_pct=weight),),
        winners=(),
        losers=(),
        gain_available=True,
    )


def _goal():
    return SimpleNamespace(
        target_date_alternative=SimpleNamespace(
            available=True,
            reach_year=2035,
            reach_date_label="31 Ekim 2035",
        ),
        baseline=SimpleNamespace(projected_wealth=249464, attainment_pct=49.9),
        snapshot=SimpleNamespace(current_value_lower_bound=79613),
        header=SimpleNamespace(
            progress_pct=15.9,
            current_wealth_label="$79,613",
            target_wealth_label="$500,000",
            progress_caption="%15.9",
        ),
        current_plan=SimpleNamespace(
            projected_wealth_label="$249,464",
            attainment_label="%49.9",
            starting_monthly_label="60,000 TL",
        ),
        required=SimpleNamespace(required_label="177,946 TL"),
        goal=SimpleNamespace(target_amount=500000),
        nabi=SimpleNamespace(copy="2031 hedefi mevcut katkı planıyla yakalanamıyor."),
    )


def _action(title: str = CONTRIBUTION_PLAN_TITLE) -> PresentedAction:
    return PresentedAction(
        id="contrib",
        category_label="Hedef",
        priority_label="Yüksek",
        priority_tone="warning",
        title=title,
        explanation="2031 hedefi mevcut katkı planıyla yakalanamıyor.",
        evidence_lines=(
            "Mevcut aylık katkı: 60,000 TL",
            "Gerekli başlangıç aylık katkı: 177,946 TL",
        ),
        limitation=None,
        direction=None,
        options=("A) Aylık katkıyı artır", "B) Hedef tarihini uzat"),
    )


def _presented(*actions: PresentedAction, healthy: bool = False) -> ActionCenterPresentation:
    return ActionCenterPresentation(
        heading="NABI Karar Merkezi",
        healthy=healthy,
        healthy_message=HEALTHY_MESSAGE if healthy else None,
        disclaimer="",
        visible_actions=actions,
        hidden_count=0,
        evidence_summary=(),
        action_ids=tuple(row.id for row in actions),
        status_summary=HEALTHY_MESSAGE if healthy else "konular",
        actionable_count=0 if healthy else len(actions),
        highest_severity_label=None if healthy else "Yüksek",
    )


def _money(*, ready: bool = True) -> BriefNewMoney:
    if not ready:
        return BriefNewMoney(
            amount_label="60,000 TL",
            allocated_label="0 TL",
            residual_label="60,000 TL",
            recommendations=(),
            unavailable_reason="Kayıtlı hedef dağılım yok; dağılım önerisi üretilemedi.",
        )
    return BriefNewMoney(
        amount_label="60,000 TL",
        allocated_label="45,000 TL",
        residual_label="15,000 TL",
        recommendations=(
            SimpleNamespace(symbol="AAPL"),
            SimpleNamespace(symbol="MSFT"),
            SimpleNamespace(symbol="NVDA"),
        ),
        unavailable_reason=None,
    )


class EligibilityAndLimitsTests(unittest.TestCase):
    def test_incomplete_candidates_excluded_from_count(self) -> None:
        incomplete = _candidate(
            "TRAP",
            decision="VERİ EKSİK",
            participation="Kontrol Et",
            completeness=10.0,
        )
        valid = _candidate("MSFT")
        aday = _candidate("AAPL", decision="ADAY", completeness=75)
        extra = [_candidate(f"X{index}", decision="ADAY") for index in range(4)]
        self.assertFalse(is_actionable_opportunity(incomplete))
        self.assertEqual(count_qualified_opportunities([incomplete, valid, aday, *extra]), 6)
        today = build_nabi_today_executive(
            wealth=_wealth_section(),
            cockpit=_cockpit(),
            goal_dashboard=_goal(),
            presented_actions=_presented(_action(), healthy=False),
            candidates=[incomplete, valid, aday, *extra],
            new_money=_money(),
            performance=None,
        )
        self.assertEqual(today.opportunities.qualified_count, 6)
        self.assertEqual(len(today.opportunities.cards), 3)
        self.assertNotIn("TRAP", [card.symbol for card in today.opportunities.cards])
        self.assertLessEqual(len(today.actions), MAX_TODAY_ACTIONS)

    def test_primary_priority_is_one(self) -> None:
        extras = [
            PresentedAction(
                id=f"a{index}",
                category_label="x",
                priority_label="Orta",
                priority_tone="info",
                title=f"Konu {index}",
                explanation="x",
                evidence_lines=(),
                limitation=None,
                direction=None,
                options=(),
            )
            for index in range(2)
        ]
        today = build_nabi_today_executive(
            wealth=_wealth_section(),
            cockpit=_cockpit(),
            goal_dashboard=_goal(),
            presented_actions=_presented(_action(), *extras),
            candidates=[],
            new_money=_money(ready=False),
            performance=None,
        )
        self.assertEqual(PRIMARY_PRIORITY_LIMIT, 1)
        self.assertFalse(today.priority.healthy)
        self.assertEqual(today.priority.title, CONTRIBUTION_PLAN_TITLE)
        self.assertEqual(today.priority.current_metric, "60,000 TL / ay")
        self.assertEqual(today.priority.required_metric, "177,946 TL / ay")
        self.assertEqual(today.priority.overflow_label, "+2 diğer konu")

    def test_actions_route_to_wealth_or_firsatlar(self) -> None:
        actions = build_today_actions(
            focus=SimpleNamespace(
                primary=SimpleNamespace(title=CONTRIBUTION_PLAN_TITLE),
                overflow_count=0,
            ),
            qualified_count=2,
            strong_count=2,
            waiting_research=29,
            new_money=present_new_money_preview(_money()),
            performance=present_performance_preview(None),
        )
        self.assertLessEqual(len(actions), MAX_TODAY_ACTIONS)
        titles = [row.title for row in actions]
        self.assertIn(ACTION_REVIEW_PLAN, titles)
        self.assertIn(ACTION_REVIEW_ALLOCATION, titles)
        pages = {row.destination_page for row in actions}
        self.assertTrue(pages <= {WEALTH_PAGE, FIRSATLAR_PAGE})
        self.assertEqual(actions[0].why, WHY_PLAN_GAP)


class SynthesisAndPreviewTests(unittest.TestCase):
    def test_synthesis_uses_canonical_copy(self) -> None:
        text = build_today_synthesis(
            commentary_insights=(NO_CONCENTRATION_COPY, PLAN_GAP_INSIGHT),
            commentary_synthesis=None,
            opportunity_teaser=NO_OPPORTUNITY_COPY,
        )
        self.assertIn("kritik tekil pozisyon yoğunlaşması görünmüyor", text)
        self.assertIn("ana konu 2031 hedefi için katkı hızında", text)
        self.assertIn(NO_OPPORTUNITY_COPY, text)

    def test_wealth_kpi_matches_canonical_usd(self) -> None:
        today = build_nabi_today_executive(
            wealth=_wealth_section(),
            cockpit=_cockpit(),
            goal_dashboard=_goal(),
            presented_actions=_presented(healthy=True),
            candidates=[],
            new_money=_money(ready=False),
            performance=None,
        )
        labels = {kpi.label: kpi for kpi in today.kpis}
        self.assertEqual(labels[KPI_WEALTH].value, "$79,613")
        self.assertEqual(today.wealth_usd, "$79,613")
        self.assertEqual(labels[KPI_GAIN].value, "$14,894")
        self.assertEqual(labels[KPI_PROGRESS].value, "%15.9")
        self.assertEqual(labels[KPI_OPPORTUNITIES].value, "0")
        self.assertEqual(today.priority.empty_copy, HEALTHY_MESSAGE)
        self.assertEqual(today.performance.copy, ONE_POINT_HISTORY)
        self.assertFalse(today.performance.comparable)
        self.assertNotEqual(today.performance.copy, "0%")

    def test_new_money_is_advisory_only(self) -> None:
        preview = present_new_money_preview(_money())
        self.assertTrue(preview.ready)
        self.assertEqual(
            preview.line,
            NEW_MONEY_READY_TEMPLATE.format(amount="60,000 TL"),
        )
        self.assertEqual(preview.symbols, ("AAPL", "MSFT"))
        home = HOME.read_text(encoding="utf-8")
        self.assertIn("NEW_MONEY_ADVISORY", home)
        self.assertIn("switch_page", home)
        self.assertNotIn("allocate_new_money(", home)
        self.assertIn(NEW_MONEY_ADVISORY, PRES.read_text(encoding="utf-8"))


class RoutingAndSafetyTests(unittest.TestCase):
    def test_primary_ui_avoids_technical_vocabulary(self) -> None:
        ui = HOME.read_text(encoding="utf-8")
        for token in TECHNICAL_UX:
            self.assertNotIn(token, ui)
        self.assertIn("FIRSATLARI_GOR_LABEL", PRES.read_text(encoding="utf-8"))
        self.assertIn("WEALTH_OPEN_LABEL", PRES.read_text(encoding="utf-8"))
        self.assertIn("FIRSATLAR_PAGE", ui)
        self.assertIn("WEALTH_PAGE", ui)
        self.assertIn("filter_equity_candidate_surface", ui)

    def test_legacy_tools_collapsed(self) -> None:
        source = DASHBOARD.read_text(encoding="utf-8")
        self.assertIn('st.expander("Gelişmiş Araçlar", expanded=False)', source)
        self.assertIn("Bir sembol analiz et", source)
        self.assertLess(
            source.index("render_nabi_home_executive"),
            source.index("Gelişmiş Araçlar"),
        )

    def test_no_providers_or_writes(self) -> None:
        for path in (PRES, HOME):
            source = path.read_text(encoding="utf-8")
            for token in PROVIDER_TOKENS:
                self.assertNotIn(token, source)
            for token in WRITE_TOKENS:
                self.assertNotIn(token, source)

    def test_wealth_and_firsatlar_freeze(self) -> None:
        wealth = WEALTH.read_text(encoding="utf-8")
        firsatlar = FIRSATLAR.read_text(encoding="utf-8")
        self.assertIn("render_wealth_command_center", wealth)
        self.assertNotIn("nabi_today_presentation", wealth)
        self.assertIn("render_opportunity_center", firsatlar)
        self.assertNotIn("nabi_today_presentation", firsatlar)

    def test_research_wait_action_when_no_qualified(self) -> None:
        actions = build_today_actions(
            focus=SimpleNamespace(primary=None, overflow_count=0),
            qualified_count=0,
            strong_count=0,
            waiting_research=29,
            new_money=present_new_money_preview(_money(ready=False)),
            performance=present_performance_preview(None),
        )
        self.assertEqual(actions[0].title, ACTION_FINISH_RESEARCH)
        self.assertEqual(actions[0].destination_page, FIRSATLAR_PAGE)
        self.assertIn(ACTION_WAIT_HISTORY, [row.title for row in actions])


if __name__ == "__main__":
    unittest.main()
