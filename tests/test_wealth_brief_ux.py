from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

from components.portfolio_decision_center_ui import HEALTHY_MESSAGE, present_action_center
from components.wealth_brief_ui import compose_wealth_brief, render_wealth_brief
from services.portfolio_decision_intelligence import build_portfolio_decision
from services.wealth_brief_presentation import (
    BRIEF_TITLE,
    MAX_ALLOCATION_PREVIEW,
    SECTION_GOAL,
    SECTION_NEW_MONEY,
    SECTION_PERFORMANCE,
    SECTION_PRIORITY,
    SECTION_TODAY,
    VALUATION_PARTIAL_LABEL,
    build_wealth_brief,
)
from services.wealth_contribution_intelligence import build_contribution_intelligence
from services.wealth_external_cash_flow import ContributionReconciliation
from services.wealth_goal_center_presentation import (
    build_goal_center_dashboard,
    contribution_tracking_starts_copy,
    format_money_display,
)
from services.wealth_institution_center_presentation import present_institution_center
from services.wealth_purification_zakat import (
    BRIEF_READY,
    PurificationBasis,
    PurificationZakatScenario,
    ProductAssumption,
    calculate_purification_zakat,
)
from services.wealth_goal_models import (
    ContributionPlan,
    current_wealth_from_portfolio_view,
    default_contribution_plan,
    default_wealth_goal_2031,
)
from services.wealth_new_money_allocation import (
    AllocationPlan,
    AllocationRecommendation,
    allocate_new_money,
)
from services.wealth_performance_center_presentation import (
    INSUFFICIENT_COPY,
    PerformancePeriod,
    build_performance_center,
)
from services.wealth_planning_fx import required_planning_fx_years, schedule_from_mapping
from services.wealth_projection_engine import project_wealth_goal_scenarios
from tests.test_portfolio_decision_center_ui import (
    ACCOUNT,
    _healthy_view,
    _live_like_decision,
    _partial_bist_view,
    _deposit,
)
from tests.test_portfolio_decision_intelligence import _complete_usd_view
from tests.test_wealth_new_money_allocation import _candidate, _fx, _policy, _row, _view
from tests.test_wealth_performance_center_ux import _pos, _series, _snap

AS_OF = date(2026, 8, 21)
TRACKING_START = date(2026, 9, 1)
PRES = Path("services/wealth_brief_presentation.py")
UI = Path("components/wealth_brief_ui.py")
PROVIDER_TOKENS = (
    "FMPClient",
    "fmp_client",
    "openai",
    "SECFinancialClient",
    "AlphaVantage",
    "TwelveData",
    "fx_rate_refresh",
    "fund_holdings_refresh",
    "BorsaIstanbul",
)
WRITE_TOKENS = (
    "post_transaction",
    "register_asset",
    ".insert(",
    ".upsert(",
    ".delete(",
    "capture_portfolio_snapshot",
    "save_planning_fx_schedule",
    "save_policy",
)
MATH_TOKENS = (
    "def modified_dietz",
    "solve_required_starting_monthly",
    "end_price / start_price",
)


def _fx_complete(as_of=AS_OF):
    years = required_planning_fx_years(as_of, default_wealth_goal_2031().target_date)
    extra = {year: Decimal("34") for year in range(as_of.year, 2037)}
    extra.update({year: Decimal("34") for year in years})
    return schedule_from_mapping(extra)


def _recon(through="2026-08-21"):
    return (
        ContributionReconciliation(
            portfolio_id="pf-1",
            reconciled_through=date.fromisoformat(through),
        ),
    )


def _dashboard(*, view=None, as_of=AS_OF, tracking_start=TRACKING_START, current=None, decision=None):
    portfolio = view or _complete_usd_view(value=79508.4249)
    snapshot = current or current_wealth_from_portfolio_view(portfolio)
    fx = _fx_complete(as_of)
    plan = default_contribution_plan()
    goal = default_wealth_goal_2031()
    intelligence = build_contribution_intelligence(
        as_of_date=as_of,
        current=snapshot,
        transactions=[],
        account_ids=[ACCOUNT],
        plan=plan,
        goal=goal,
        contribution_tracking_start=tracking_start,
        fx_schedule=fx,
        contribution_reconciliations=_recon(as_of.isoformat()),
        portfolio_id="pf-1",
    )
    bands = project_wealth_goal_scenarios(
        goal=goal,
        as_of_date=as_of,
        current=snapshot,
        contribution_plan=plan,
        fx_schedule=fx,
    )
    return build_goal_center_dashboard(
        as_of_date=as_of,
        goal=goal,
        plan=plan,
        snapshot=snapshot,
        fx_schedule=fx,
        intelligence=intelligence,
        tracking_start=tracking_start,
        decision=decision,
        bands=bands,
    )


def _allocation_preview():
    plan = allocate_new_money(
        available_amount=default_contribution_plan().starting_monthly,
        amount_currency="TRY",
        portfolio_view=_view(
            [_row("SPUS", market_value=10000, weight_pct=100, price=100, asset_class="etf")]
        ),
        policy=_policy(equity=80, etf=20),
        candidates=[_candidate("MSFT", "GÜÇLÜ ADAY"), _candidate("AAPL", "ADAY"), _candidate("NVDA", "ADAY")],
        conversion=_fx(),
    )
    return plan


def _rec(symbol: str) -> AllocationRecommendation:
    return AllocationRecommendation(
        symbol=symbol,
        existing_or_new="new",
        layer="equity",
        decision="ADAY",
        price=Decimal("100"),
        price_currency="USD",
        quantity=Decimal("1"),
        allocated_amount=Decimal("100"),
        reason_code="CANDIDATE",
        reason_text="ADAY",
    )


class _Box:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def markdown(self, *args, **kwargs):
        return None

    def write(self, *args, **kwargs):
        return None

    def caption(self, *args, **kwargs):
        return None

    def metric(self, *args, **kwargs):
        return None

    def info(self, *args, **kwargs):
        return None

    def success(self, *args, **kwargs):
        return None


class DummySt:
    def __init__(self):
        self.markdowns: list[str] = []
        self.writes: list[str] = []
        self.captions: list[str] = []
        self.infos: list[str] = []
        self.successes: list[str] = []
        self.session_state = {}

    def markdown(self, text, **kwargs):
        self.markdowns.append(str(text))

    def write(self, text, **kwargs):
        self.writes.append(str(text))

    def caption(self, text, **kwargs):
        self.captions.append(str(text))

    def info(self, text, **kwargs):
        self.infos.append(str(text))

    def success(self, text, **kwargs):
        self.successes.append(str(text))

    def warning(self, text, **kwargs):
        self.infos.append(str(text))

    def columns(self, count):
        size = count if isinstance(count, int) else len(count)
        return [_Box() for _ in range(size)]

    def expander(self, *args, **kwargs):
        return _Box()

    def metric(self, *args, **kwargs):
        return None


def _blob(dummy: DummySt) -> str:
    return "\n".join(dummy.markdowns + dummy.writes + dummy.captions + dummy.infos + dummy.successes)


def _patch(dummy: DummySt):
    return (
        patch("components.wealth_brief_ui.st", dummy),
        patch("components.nabi_design_system._st", return_value=dummy),
    )


class BriefCompositionTests(unittest.TestCase):
    def test_complete_valuation_brief(self) -> None:
        view = _complete_usd_view(value=79508.4249)
        dashboard = _dashboard(view=view)
        decision = build_portfolio_decision(
            view,
            as_of_date=AS_OF,
            current_wealth=dashboard.snapshot,
            fx_schedule=_fx_complete(),
            contribution_tracking_start=TRACKING_START,
        )
        brief = build_wealth_brief(
            as_of_date=AS_OF,
            portfolio_view=view,
            dashboard=dashboard,
            decision=decision,
            allocation=_allocation_preview(),
            performance=build_performance_center(_series(), period=PerformancePeriod.MONTHLY),
        )
        self.assertEqual(brief.header.title, BRIEF_TITLE)
        self.assertEqual(brief.header.current_value_label, dashboard.header.current_wealth_label)
        self.assertTrue(brief.header.valuation_complete)
        self.assertIn(dashboard.header.progress_caption, " ".join(brief.today_lines))

    def test_incomplete_valuation_limitation(self) -> None:
        view = _partial_bist_view()
        dashboard = _dashboard(view=view, current=current_wealth_from_portfolio_view(view))
        brief = build_wealth_brief(
            as_of_date=AS_OF,
            portfolio_view=view,
            dashboard=dashboard,
            decision=_live_like_decision(),
        )
        self.assertFalse(brief.header.valuation_complete)
        self.assertEqual(brief.header.valuation_status, VALUATION_PARTIAL_LABEL)
        self.assertIn(VALUATION_PARTIAL_LABEL, brief.today_lines)
        self.assertTrue(any(VALUATION_PARTIAL_LABEL in row for row in brief.limitations))

    def test_highest_priority_di_signal(self) -> None:
        view = _partial_bist_view()
        dashboard = _dashboard(view=view, current=current_wealth_from_portfolio_view(view))
        decision = _live_like_decision()
        presented = present_action_center(decision)
        brief = build_wealth_brief(
            as_of_date=AS_OF,
            portfolio_view=view,
            dashboard=dashboard,
            decision=decision,
        )
        self.assertFalse(brief.priority.healthy)
        self.assertEqual(brief.priority.title, presented.visible_actions[0].title)
        self.assertEqual(brief.priority.title, "Portföy değerlemesini tamamla")
        self.assertEqual(brief.priority.severity_label, presented.visible_actions[0].priority_label)

    def test_no_action_di_state(self) -> None:
        view = _healthy_view()
        as_of = date(2026, 10, 1)
        dashboard = _dashboard(view=view, as_of=as_of, tracking_start=date(2026, 1, 1))
        decision = build_portfolio_decision(
            view,
            as_of_date=as_of,
            plan=ContributionPlan(
                starting_monthly=Decimal("20000"),
                currency="USD",
                annual_increase_rate=Decimal("0"),
            ),
            current_wealth=current_wealth_from_portfolio_view(view),
            transactions=[_deposit(20000)],
            account_ids=[ACCOUNT],
            contribution_reconciliations=_recon("2026-10-01"),
            contribution_tracking_start=date(2026, 1, 1),
            fx_schedule=_fx_complete(as_of),
        )
        brief = build_wealth_brief(
            as_of_date=as_of,
            portfolio_view=view,
            dashboard=dashboard,
            decision=decision,
        )
        self.assertTrue(present_action_center(decision).healthy)
        self.assertTrue(brief.priority.healthy)
        self.assertEqual(brief.priority.title, HEALTHY_MESSAGE)
        self.assertIn(HEALTHY_MESSAGE, brief.today_lines)

    def test_goal_summary_uses_canonical_outputs(self) -> None:
        view = _complete_usd_view(value=79508.4249)
        dashboard = _dashboard(view=view)
        brief = build_wealth_brief(
            as_of_date=AS_OF,
            portfolio_view=view,
            dashboard=dashboard,
            decision=build_portfolio_decision(view, as_of_date=AS_OF, fx_schedule=_fx_complete()),
        )
        self.assertEqual(brief.goal.target_label, dashboard.header.target_wealth_label)
        self.assertEqual(brief.goal.current_progress, dashboard.header.progress_caption)
        self.assertEqual(brief.goal.projected_wealth_label, dashboard.current_plan.projected_wealth_label)
        self.assertEqual(brief.goal.configured_monthly_label, dashboard.current_plan.starting_monthly_label)
        self.assertEqual(brief.goal.required_monthly_label, dashboard.required.required_label)
        self.assertEqual(
            brief.goal.required_monthly_label,
            format_money_display(dashboard.required.required_monthly, dashboard.plan.currency),
        )
        self.assertEqual(brief.goal.status_copy, dashboard.current_plan.status_copy)

    def test_new_money_preview_max_three_and_residual(self) -> None:
        view = _complete_usd_view()
        dashboard = _dashboard(view=view)
        fat = AllocationPlan(
            input_amount=Decimal("60000"),
            currency="TRY",
            recommendations=(_rec("AAA"), _rec("BBB"), _rec("CCC"), _rec("DDD")),
            total_allocated=Decimal("400"),
            residual_cash=Decimal("59600"),
            skipped=(),
        )
        brief = build_wealth_brief(
            as_of_date=AS_OF,
            portfolio_view=view,
            dashboard=dashboard,
            decision=build_portfolio_decision(view, as_of_date=AS_OF),
            allocation=fat,
        )
        self.assertEqual(brief.new_money.amount_label, format_money_display(Decimal("60000"), "TRY"))
        self.assertEqual(len(brief.new_money.recommendations), MAX_ALLOCATION_PREVIEW)
        self.assertEqual(MAX_ALLOCATION_PREVIEW, 3)
        self.assertNotIn("DDD", [row.symbol for row in brief.new_money.recommendations])
        self.assertIn("59,600", brief.new_money.residual_label)
        live = _allocation_preview()
        live_brief = build_wealth_brief(
            as_of_date=AS_OF,
            portfolio_view=view,
            dashboard=dashboard,
            decision=build_portfolio_decision(view, as_of_date=AS_OF),
            allocation=live,
        )
        self.assertEqual(
            live_brief.new_money.residual_label,
            format_money_display(live.residual_cash, live.currency),
        )
        self.assertLessEqual(len(live_brief.new_money.recommendations), 3)

    def test_performance_reused_and_insufficient(self) -> None:
        view = _complete_usd_view()
        dashboard = _dashboard(view=view)
        series = _series()
        performance = build_performance_center(
            series,
            period=PerformancePeriod.MONTHLY,
            account_ids=[ACCOUNT],
            contribution_reconciliations=_recon("2026-08-22"),
            portfolio_id="pf-1",
        )
        brief = build_wealth_brief(
            as_of_date=AS_OF,
            portfolio_view=view,
            dashboard=dashboard,
            decision=build_portfolio_decision(view, as_of_date=AS_OF),
            performance=performance,
        )
        self.assertEqual(brief.performance.period_label, PerformancePeriod.MONTHLY.value)
        if performance.sufficient and performance.history and performance.history.return_pct is not None:
            self.assertEqual(brief.performance.return_label, f"{float(performance.history.return_pct):.2f}%")
        if performance.best:
            self.assertIn(performance.best[0].symbol, brief.performance.best_label or "")
        empty = build_performance_center([_snap("s1", "2026-08-22T06:30:00+00:00", 10000.0)])
        missing = build_wealth_brief(
            as_of_date=AS_OF,
            portfolio_view=view,
            dashboard=dashboard,
            decision=build_portfolio_decision(view, as_of_date=AS_OF),
            performance=empty,
        )
        self.assertEqual(missing.performance.limitation, INSUFFICIENT_COPY)
        self.assertIsNone(missing.performance.return_label)

    def test_pre_tracking_start_copy(self) -> None:
        view = _complete_usd_view()
        dashboard = _dashboard(view=view, tracking_start=TRACKING_START)
        brief = build_wealth_brief(
            as_of_date=AS_OF,
            portfolio_view=view,
            dashboard=dashboard,
            decision=build_portfolio_decision(
                view,
                as_of_date=AS_OF,
                contribution_tracking_start=TRACKING_START,
                fx_schedule=_fx_complete(),
            ),
        )
        expected = contribution_tracking_starts_copy(TRACKING_START)
        self.assertEqual(brief.tracking_prestart_copy, expected)
        self.assertEqual(dashboard.tracking_prestart_copy, expected)
        blob = " ".join(brief.today_lines).lower()
        self.assertIn(expected, brief.today_lines)
        self.assertNotIn("kaçır", blob)
        self.assertNotIn("missed", blob)


class RenderAndSafetyTests(unittest.TestCase):
    def test_render_sections(self) -> None:
        view = _complete_usd_view()
        dashboard = _dashboard(view=view)
        brief = build_wealth_brief(
            as_of_date=AS_OF,
            portfolio_view=view,
            dashboard=dashboard,
            decision=_live_like_decision(),
            allocation=_allocation_preview(),
            performance=build_performance_center(_series(), period=PerformancePeriod.ALL),
        )
        dummy = DummySt()
        with _patch(dummy)[0], _patch(dummy)[1]:
            render_wealth_brief(brief=brief)
        text = _blob(dummy)
        self.assertIn(BRIEF_TITLE, text)
        self.assertIn(SECTION_TODAY, text)
        self.assertIn(SECTION_PRIORITY, text)
        self.assertIn(SECTION_GOAL, text)
        self.assertIn(SECTION_NEW_MONEY, text)
        self.assertIn(SECTION_PERFORMANCE, text)

    def test_compose_uses_canonical_engines(self) -> None:
        wealth = MagicMock()
        wealth.client = None
        wealth.user_id = "user-1"
        wealth.list_assets.return_value = []
        wealth.list_positions.return_value = []
        wealth.list_transactions.return_value = []
        view = _complete_usd_view()
        with patch(
            "components.wealth_brief_ui.load_planning_fx_schedule",
            return_value=_fx_complete(),
        ), patch(
            "components.wealth_brief_ui.load_contribution_tracking_start",
            return_value=TRACKING_START,
        ), patch(
            "components.wealth_brief_ui.contribution_reconciliations_for_wealth",
            return_value=_recon(),
        ):
            brief = compose_wealth_brief(
                portfolio_view=view,
                wealth=wealth,
                accounts=[{"id": ACCOUNT}],
                as_of=AS_OF,
                policy=_policy(equity=80, etf=20),
                candidates=[_candidate("MSFT", "GÜÇLÜ ADAY")],
                snapshots=_series(),
            )
        self.assertEqual(brief.header.title, BRIEF_TITLE)
        self.assertEqual(brief.new_money.amount_label, format_money_display(Decimal("60000"), "TRY"))
        wealth.post_transaction.assert_not_called()

    def test_no_providers_writes_or_new_math(self) -> None:
        for path in (PRES, UI):
            source = path.read_text(encoding="utf-8")
            lower = source.lower()
            for token in PROVIDER_TOKENS:
                self.assertNotIn(token.lower(), lower)
            for token in WRITE_TOKENS:
                self.assertNotIn(token, source)
        pres = PRES.read_text(encoding="utf-8")
        ui = UI.read_text(encoding="utf-8")
        for token in MATH_TOKENS:
            self.assertNotIn(token, pres)
            self.assertNotIn(token, ui)
        self.assertIn("build_goal_center_dashboard", ui)
        self.assertIn("allocate_new_money", ui)
        self.assertIn("build_performance_center", ui)
        self.assertIn("present_action_center", pres)
        self.assertIn("build_portfolio_decision", ui)
        self.assertIn("present_institution_center", ui)
        self.assertIn("render_wealth_brief", Path("pages/10_Wealth.py").read_text(encoding="utf-8"))

    def test_complete_brief_includes_institution_summary(self) -> None:
        view = _complete_usd_view(value=100000.0)
        accounts = [{"id": ACCOUNT, "name": "Broker", "institution": "Midas", "currency": "USD"}]
        center = present_institution_center(view, accounts)
        dashboard = _dashboard(view=view)
        brief = build_wealth_brief(
            as_of_date=AS_OF,
            portfolio_view=view,
            dashboard=dashboard,
            decision=build_portfolio_decision(view, as_of_date=AS_OF, fx_schedule=_fx_complete()),
            institution_center=center,
        )
        self.assertTrue(brief.header.valuation_complete)
        self.assertIsNotNone(center.brief_line)
        self.assertIn(center.brief_line, brief.today_lines)
        self.assertTrue(center.brief_line.startswith("Kurum dağılımı:"))

    def test_complete_brief_includes_purification_line_when_ready(self) -> None:
        view = _complete_usd_view(value=100000.0)
        result = calculate_purification_zakat(
            view,
            scenario=PurificationZakatScenario(
                basis=PurificationBasis.MARKET_VALUE,
                zakat_rate_pct=2.5,
                include_all_eligible_at_100=True,
                assumptions=tuple(
                    ProductAssumption(row.position_id, purification_ratio_pct=1.0)
                    for row in view.priced_positions
                ),
            ),
        )
        dashboard = _dashboard(view=view)
        brief = build_wealth_brief(
            as_of_date=AS_OF,
            portfolio_view=view,
            dashboard=dashboard,
            decision=build_portfolio_decision(view, as_of_date=AS_OF, fx_schedule=_fx_complete()),
            purification_zakat=result,
        )
        self.assertEqual(result.brief_line, BRIEF_READY)
        self.assertIn(BRIEF_READY, brief.today_lines)
        self.assertEqual(sum(1 for line in brief.today_lines if "Arındırma/Zekât" in line), 1)


if __name__ == "__main__":
    unittest.main()
