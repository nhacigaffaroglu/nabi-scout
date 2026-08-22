from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

from components.wealth_goal_center_ui import (
    _render_goal_dashboard,
    _render_scenario_explorer,
    render_wealth_goal_center,
)
from services.portfolio_decision_intelligence import build_portfolio_decision
from services.wealth_contribution_intelligence import build_contribution_intelligence
from services.wealth_external_cash_flow import ContributionTrackingScope
from services.wealth_goal_center_presentation import (
    NABI_BELOW_REQUIRED_TEMPLATE,
    NABI_PARTIAL,
    PARTIAL_NOT_DECISION_GRADE,
    PLAN_STATUS_INDETERMINATE,
    PLAN_STATUS_SHORTFALL,
    PLAN_STATUS_TARGET_REACHED,
    SCENARIO_CARD_LEVELS,
    SCENARIO_EXPLORER_DISCLAIMER,
    build_goal_center_dashboard,
    contribution_tracking_starts_copy,
    format_money_display,
    plan_status_copy,
)
from services.wealth_goal_models import (
    ContributionPlan,
    CurrentWealthSnapshot,
    GoalEvidenceStatus,
    default_contribution_plan,
    default_wealth_goal_2031,
)
from services.wealth_goal_planning import build_what_if_projection, solve_required_starting_monthly
from services.wealth_goal_scenario_service import (
    BASE_RETURN_RATE,
    earliest_target_reach,
    project_scenario,
)
from services.wealth_planning_fx import (
    propose_planning_fx_continuation,
    schedule_from_mapping,
)
from services.wealth_projection_engine import project_wealth_goal_scenarios
from tests.test_portfolio_decision_intelligence import _complete_usd_view


AS_OF = date(2026, 8, 21)
TRACKING_START = date(2026, 9, 1)
CURRENT_WEALTH = Decimal("79508.4249")
PLANNING_FX_2031 = {2026: 51, 2027: 59, 2028: 66, 2029: 73, 2030: 80, 2031: 87}
UI = Path("components/wealth_goal_center_ui.py")
PRESENTATION = Path("services/wealth_goal_center_presentation.py")
PROVIDER_TOKENS = (
    "FMPClient",
    "fmp_client",
    "openai",
    "SECFinancialClient",
    "AlphaVantage",
    "alpha_vantage",
    "TwelveData",
    "twelve_data",
    "fx_rate_refresh",
    "fund_holdings_refresh",
    "BorsaIstanbul",
    "borsaistanbul",
)
WRITE_TOKENS = (
    "post_transaction",
    "register_asset",
    ".delete(",
    "create_account",
    "capture_portfolio_snapshot",
    "replace_schedule",
    "upsert_rate",
)


def _usd(amount=CURRENT_WEALTH, *, complete: bool = True, unvalued=()) -> CurrentWealthSnapshot:
    return CurrentWealthSnapshot(
        currency="USD",
        current_value_lower_bound=Decimal(str(amount)),
        valuation_complete=complete,
        unvalued_symbols=tuple(unvalued),
    )


def _plan() -> ContributionPlan:
    return default_contribution_plan()


def _fx_2031():
    return schedule_from_mapping(PLANNING_FX_2031)


def _fx_2036():
    proposal = propose_planning_fx_continuation(_fx_2031())
    merged = dict(PLANNING_FX_2031)
    merged.update(proposal.as_mapping())
    return schedule_from_mapping(merged)


def _intel(*, current=None, fx=None, as_of=AS_OF, tracking_start=TRACKING_START):
    snapshot = current or _usd()
    return build_contribution_intelligence(
        as_of_date=as_of,
        current=snapshot,
        transactions=[],
        account_ids=["acc-1"],
        plan=_plan(),
        goal=default_wealth_goal_2031(),
        contribution_tracking_start=tracking_start,
        fx_schedule=fx if fx is not None else _fx_2036(),
    )


def _dashboard(**kwargs):
    current = kwargs.pop("current", _usd())
    fx = kwargs.pop("fx_schedule", _fx_2036())
    as_of = kwargs.pop("as_of_date", AS_OF)
    tracking_start = kwargs.pop("tracking_start", TRACKING_START)
    plan = kwargs.pop("plan", _plan())
    goal = kwargs.pop("goal", default_wealth_goal_2031())
    intelligence = kwargs.pop("intelligence", None) or _intel(
        current=current, fx=fx, as_of=as_of, tracking_start=tracking_start
    )
    bands = kwargs.pop("bands", None)
    if bands is None:
        bands = project_wealth_goal_scenarios(
            goal=goal,
            as_of_date=as_of,
            current=current,
            contribution_plan=plan,
            fx_schedule=fx,
        )
    return build_goal_center_dashboard(
        as_of_date=as_of,
        goal=goal,
        plan=plan,
        snapshot=current,
        fx_schedule=fx,
        intelligence=intelligence,
        tracking_start=tracking_start,
        bands=bands,
        **kwargs,
    )


class _Box:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def markdown(self, *args, **kwargs):
        return None

    def metric(self, *args, **kwargs):
        return None

    def caption(self, *args, **kwargs):
        return None

    def info(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None

    def number_input(self, *args, **kwargs):
        return kwargs.get("value", 0.0)

    def text_input(self, *args, **kwargs):
        return kwargs.get("value", "")

    def date_input(self, *args, **kwargs):
        return kwargs.get("value")

    def selectbox(self, *args, **kwargs):
        options = kwargs.get("options") or []
        return options[0] if options else ""

    def button(self, *args, **kwargs):
        return False

    def dataframe(self, *args, **kwargs):
        return None

    def progress(self, *args, **kwargs):
        return None


class DummySt:
    def __init__(self):
        self.markdowns: list[str] = []
        self.infos: list[str] = []
        self.warnings: list[str] = []
        self.captions: list[str] = []
        self.session_state = {}

    def markdown(self, text, **kwargs):
        self.markdowns.append(str(text))

    def expander(self, *args, **kwargs):
        return _Box()

    def columns(self, count):
        size = count if isinstance(count, int) else len(count)
        return [_Box() for _ in range(size)]

    def number_input(self, *args, **kwargs):
        return kwargs.get("value", 0.0)

    def progress(self, *args, **kwargs):
        return None

    def caption(self, text, **kwargs):
        self.captions.append(str(text))

    def write(self, text, **kwargs):
        self.markdowns.append(str(text))

    def info(self, text):
        self.infos.append(str(text))

    def warning(self, text):
        self.warnings.append(str(text))

    def success(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None

    def button(self, *args, **kwargs):
        return False

    def text_input(self, *args, **kwargs):
        return kwargs.get("value", "")

    def date_input(self, *args, **kwargs):
        return kwargs.get("value")

    def selectbox(self, *args, **kwargs):
        options = kwargs.get("options") or args[1:]
        if options:
            return options[0]
        return ""

    def radio(self, *args, **kwargs):
        options = kwargs.get("options") or args[1] if len(args) > 1 else kwargs.get("options")
        if options:
            index = kwargs.get("index", 0)
            try:
                return options[index]
            except Exception:
                return options[0]
        return ""

    def container(self, *args, **kwargs):
        return _Box()

    def metric(self, *args, **kwargs):
        return None

    def dataframe(self, *args, **kwargs):
        return None

    def rerun(self):
        return None

    def html(self, *args, **kwargs):
        return None


def _patch_streamlit(dummy: DummySt):
    return (
        patch("components.wealth_goal_center_ui.st", dummy),
        patch("components.nabi_design_system._st", return_value=dummy),
        patch("components.wealth_new_money_allocation_ui.st", dummy),
    )


class CompleteValuationDashboardTests(unittest.TestCase):
    def test_header_uses_canonical_current_target_progress(self) -> None:
        dashboard = _dashboard()
        goal = default_wealth_goal_2031()
        base = dashboard.base_projection
        self.assertIsNotNone(base)
        self.assertTrue(dashboard.header.valuation_complete)
        self.assertEqual(
            dashboard.header.current_wealth_label,
            format_money_display(CURRENT_WEALTH, "USD"),
        )
        self.assertEqual(
            dashboard.header.target_wealth_label,
            format_money_display(goal.target_amount, "USD"),
        )
        self.assertEqual(dashboard.header.progress_pct, base.progress_pct_lower_bound)
        self.assertIn("%", dashboard.header.progress_caption)
        self.assertIn("tamamlandı", dashboard.header.progress_caption)

    def test_current_plan_matches_goal_engine(self) -> None:
        dashboard = _dashboard()
        expected = project_scenario(
            as_of_date=AS_OF,
            current=_usd(),
            contribution_plan=_plan(),
            annual_return_rate=BASE_RETURN_RATE,
            fx_schedule=_fx_2036(),
            goal=default_wealth_goal_2031(),
        )
        self.assertEqual(dashboard.baseline.projected_wealth, expected.projected_wealth)
        self.assertEqual(dashboard.current_plan.projected_wealth_label, format_money_display(expected.projected_wealth, "USD"))
        self.assertEqual(dashboard.current_plan.attainment_label, f"%{float(expected.attainment_pct):.1f}")
        self.assertFalse(dashboard.current_plan.gap_is_surplus)
        self.assertEqual(dashboard.current_plan.status, GoalEvidenceStatus.PROJECTED_SHORTFALL)
        self.assertEqual(dashboard.current_plan.status_copy, PLAN_STATUS_SHORTFALL)
        self.assertNotEqual(dashboard.current_plan.status_copy, PLAN_STATUS_TARGET_REACHED)

    def test_required_contribution_uses_solver(self) -> None:
        dashboard = _dashboard()
        solved = solve_required_starting_monthly(
            as_of_date=AS_OF,
            current=_usd(),
            contribution_currency="TRY",
            annual_increase_rate=Decimal("0.25"),
            annual_return_rate=BASE_RETURN_RATE,
            fx_schedule=_fx_2036(),
            goal=default_wealth_goal_2031(),
        )
        self.assertTrue(dashboard.required.available)
        self.assertEqual(dashboard.required.required_monthly, solved.starting_monthly)
        self.assertEqual(
            dashboard.required.required_label,
            format_money_display(solved.starting_monthly, "TRY"),
        )
        self.assertEqual(
            dashboard.required.current_label,
            format_money_display(_plan().starting_monthly, "TRY"),
        )
        self.assertIsNotNone(dashboard.required.pct_increase_label)

    def test_earliest_target_year_uses_extended_horizon(self) -> None:
        dashboard = _dashboard()
        reach = earliest_target_reach(
            as_of_date=AS_OF,
            current=_usd(),
            contribution_plan=_plan(),
            fx_schedule=_fx_2036(),
            goal=default_wealth_goal_2031(),
        )
        self.assertTrue(dashboard.target_date_alternative.available)
        self.assertEqual(dashboard.target_date_alternative.reach_year, reach.reach_year)
        self.assertEqual(dashboard.earliest_current_plan.reach_date, reach.reach_date)
        self.assertIsNotNone(dashboard.target_date_alternative.reach_year)

    def test_scenario_cards_are_engine_outputs(self) -> None:
        dashboard = _dashboard()
        self.assertEqual(
            [card.starting_monthly for card in dashboard.scenario_cards],
            list(SCENARIO_CARD_LEVELS),
        )
        for card in dashboard.scenario_cards:
            projected = project_scenario(
                as_of_date=AS_OF,
                current=_usd(),
                contribution_plan=_plan(),
                annual_return_rate=BASE_RETURN_RATE,
                fx_schedule=_fx_2036(),
                goal=default_wealth_goal_2031(),
                starting_monthly=card.starting_monthly,
            )
            reach = earliest_target_reach(
                as_of_date=AS_OF,
                current=_usd(),
                contribution_plan=_plan(),
                fx_schedule=_fx_2036(),
                goal=default_wealth_goal_2031(),
                starting_monthly=card.starting_monthly,
            )
            self.assertEqual(card.projected_wealth, projected.projected_wealth)
            self.assertEqual(card.attainment_pct, projected.attainment_pct)
            self.assertEqual(card.earliest_year, reach.reach_year)

    def test_nabi_evaluation_uses_canonical_required(self) -> None:
        view = _complete_usd_view(value=float(CURRENT_WEALTH))
        intelligence = _intel()
        decision = build_portfolio_decision(
            view,
            as_of_date=AS_OF,
            current_wealth=_usd(),
            contribution=intelligence,
            fx_schedule=_fx_2036(),
            contribution_tracking_start=TRACKING_START,
        )
        dashboard = _dashboard(decision=decision)
        self.assertTrue(dashboard.required.available)
        expected = NABI_BELOW_REQUIRED_TEMPLATE.format(required=dashboard.required.required_label)
        self.assertEqual(dashboard.nabi.copy, expected)
        self.assertEqual(dashboard.nabi.signal_id, "contribution_plan_below_required")

    def test_complete_valuation_has_no_technical_warning(self) -> None:
        dashboard = _dashboard()
        self.assertTrue(dashboard.data_quality.valuation_complete)
        self.assertTrue(dashboard.data_quality.decision_grade)
        self.assertIsNone(dashboard.data_quality.partial_warning)
        self.assertIsNone(dashboard.data_quality.fx_warning)
        self.assertFalse(dashboard.data_quality.show_technical_warnings)


class DataQualityAndTrackingTests(unittest.TestCase):
    def test_partial_valuation_is_not_decision_grade(self) -> None:
        current = _usd(complete=False, unvalued=("BIMAS",))
        dashboard = _dashboard(current=current)
        self.assertEqual(dashboard.data_quality.partial_warning, PARTIAL_NOT_DECISION_GRADE)
        self.assertFalse(dashboard.data_quality.decision_grade)
        self.assertEqual(dashboard.nabi.copy, NABI_PARTIAL)
        self.assertIn("en az", dashboard.header.progress_caption)

    def test_missing_planning_fx_is_surfaced(self) -> None:
        dashboard = _dashboard(fx_schedule=schedule_from_mapping({}))
        self.assertTrue(dashboard.data_quality.missing_fx_years)
        self.assertIsNotNone(dashboard.data_quality.fx_warning)
        self.assertFalse(dashboard.required.available)
        self.assertTrue(dashboard.target_date_alternative.blocked)
        self.assertEqual(dashboard.current_plan.status_copy, PLAN_STATUS_INDETERMINATE)

    def test_not_tracked_prestart_copy(self) -> None:
        dashboard = _dashboard()
        self.assertEqual(
            dashboard.monthly_tracking_scope,
            ContributionTrackingScope.NOT_TRACKED,
        )
        self.assertEqual(
            dashboard.tracking_prestart_copy,
            contribution_tracking_starts_copy(TRACKING_START),
        )
        self.assertEqual(
            dashboard.tracking_prestart_copy,
            "Katkı takibi 1 Eylül 2026 tarihinde başlayacak.",
        )

    def test_plan_status_does_not_infer_target_reached(self) -> None:
        self.assertEqual(
            plan_status_copy(GoalEvidenceStatus.PROJECTED_SHORTFALL),
            PLAN_STATUS_SHORTFALL,
        )
        self.assertEqual(
            plan_status_copy(GoalEvidenceStatus.INDETERMINATE),
            PLAN_STATUS_INDETERMINATE,
        )
        self.assertNotEqual(
            plan_status_copy(GoalEvidenceStatus.PROJECTED_SHORTFALL),
            PLAN_STATUS_TARGET_REACHED,
        )


class IsolationTests(unittest.TestCase):
    def test_scenario_explorer_does_not_persist(self) -> None:
        fx = _fx_2036()
        plan = _plan()
        before_plan = plan.starting_monthly
        before_fx = tuple((row.year, row.usdtry) for row in fx.rates)
        result = build_what_if_projection(
            as_of_date=AS_OF,
            current=_usd(),
            monthly_contribution=Decimal("150000"),
            contribution_currency=plan.currency,
            annual_increase_rate=plan.annual_increase_rate,
            annual_return_rate=Decimal("0.10"),
            target_date=default_wealth_goal_2031().target_date,
            fx_schedule=fx,
            goal=default_wealth_goal_2031(),
        )
        self.assertTrue(result.projection_complete)
        self.assertEqual(plan.starting_monthly, before_plan)
        self.assertEqual(tuple((row.year, row.usdtry) for row in fx.rates), before_fx)
        source = UI.read_text(encoding="utf-8")
        explorer = source.split("def _render_scenario_explorer")[1].split("def render_planning_fx")[0]
        self.assertIn(SCENARIO_EXPLORER_DISCLAIMER, source)
        self.assertNotIn("save_planning_fx_schedule", explorer)
        self.assertNotIn("set_contribution_tracking_start", explorer)
        self.assertNotIn("record_tracked_external_cash_flow", explorer)
        self.assertNotIn("default_contribution_plan =", explorer)

    def test_dashboard_build_does_not_change_inputs(self) -> None:
        fx = _fx_2036()
        plan = _plan()
        before_fx = tuple((row.year, row.usdtry) for row in fx.rates)
        dashboard = _dashboard(fx_schedule=fx, plan=plan)
        self.assertEqual(plan.starting_monthly, Decimal("60000"))
        self.assertEqual(tuple((row.year, row.usdtry) for row in fx.rates), before_fx)
        self.assertEqual(dashboard.plan.starting_monthly, plan.starting_monthly)


class RenderAndSafetyTests(unittest.TestCase):
    def test_complete_dashboard_renders_without_partial_warning(self) -> None:
        dummy = DummySt()
        patches = _patch_streamlit(dummy)
        with patches[0], patches[1]:
            _render_goal_dashboard(_dashboard())
        text = "\n".join(dummy.markdowns + dummy.infos + dummy.warnings + dummy.captions)
        self.assertIn("2031 Servet Hedefi", text)
        self.assertIn(PLAN_STATUS_SHORTFALL, text)
        self.assertNotIn(PLAN_STATUS_TARGET_REACHED, text)
        self.assertNotIn(PARTIAL_NOT_DECISION_GRADE, dummy.warnings)

    def test_partial_dashboard_warns(self) -> None:
        dummy = DummySt()
        patches = _patch_streamlit(dummy)
        with patches[0], patches[1]:
            _render_goal_dashboard(_dashboard(current=_usd(complete=False, unvalued=("BIMAS",))))
        self.assertTrue(any(PARTIAL_NOT_DECISION_GRADE in row for row in dummy.warnings))

    def test_missing_fx_dashboard_warns(self) -> None:
        dummy = DummySt()
        patches = _patch_streamlit(dummy)
        with patches[0], patches[1]:
            _render_goal_dashboard(_dashboard(fx_schedule=schedule_from_mapping({})))
        self.assertTrue(dummy.warnings)

    def test_explorer_render_does_not_write(self) -> None:
        dummy = DummySt()
        wealth = MagicMock()
        patches = _patch_streamlit(dummy)
        with patches[0], patches[1]:
            _render_scenario_explorer(
                as_of_date=AS_OF,
                current=_usd(),
                plan=_plan(),
                goal=default_wealth_goal_2031(),
                fx_schedule=_fx_2036(),
            )
        wealth.post_transaction.assert_not_called()
        self.assertTrue(
            any(SCENARIO_EXPLORER_DISCLAIMER in row for row in dummy.markdowns + dummy.captions)
        )

    def test_full_center_render_does_not_write_or_call_providers(self) -> None:
        dummy = DummySt()
        wealth = MagicMock()
        wealth.user_id = "user-1"
        wealth.client = None
        wealth.list_assets.return_value = []
        wealth.list_positions.return_value = []
        wealth.list_transactions.return_value = []
        view = _complete_usd_view(value=float(CURRENT_WEALTH))
        patches = _patch_streamlit(dummy)
        with patches[0], patches[1], patches[2], patch(
            "components.wealth_goal_center_ui.load_planning_fx_schedule",
            return_value=_fx_2036(),
        ), patch(
            "components.wealth_goal_center_ui.load_contribution_tracking_start",
            return_value=TRACKING_START,
        ), patch(
            "components.wealth_goal_center_ui.contribution_reconciliations_for_wealth",
            return_value=(),
        ), patch(
            "components.wealth_goal_center_ui._db_only_goal_view",
            return_value=view,
        ), patch(
            "services.current_market_data.fetch_fx_rate",
            side_effect=AssertionError("provider"),
        ), patch(
            "services.current_market_data.fetch_equity_quote",
            side_effect=AssertionError("provider"),
        ):
            render_wealth_goal_center(
                portfolio_view=view,
                wealth=wealth,
                accounts=[],
                as_of=AS_OF,
            )
        wealth.post_transaction.assert_not_called()
        text = "\n".join(dummy.markdowns + dummy.infos + dummy.captions)
        self.assertIn("Katkı takibi 1 Eylül 2026 tarihinde başlayacak.", dummy.infos)
        self.assertIn("NABI Değerlendirmesi", text)
        self.assertIn("Mevcut Plan", text)

    def test_ui_source_wiring(self) -> None:
        ui = UI.read_text(encoding="utf-8")
        pres = PRESENTATION.read_text(encoding="utf-8")
        self.assertIn("2031 Servet Hedefi", ui)
        self.assertIn("Mevcut Plan", ui)
        self.assertIn("Katkıyı değiştirmezsem?", ui)
        self.assertIn("Senaryo İncele", ui)
        self.assertIn("Gelişmiş Varsayımlar", ui)
        self.assertIn("NABI Değerlendirmesi", ui)
        self.assertIn("build_goal_center_dashboard", ui)
        self.assertIn("earliest_target_reach", pres)
        self.assertIn("solve_required_starting_monthly", pres)
        self.assertIn("project_scenario", pres)
        self.assertNotIn("60000", ui)
        self.assertNotIn("177933", ui)
        self.assertNotIn("249491", ui)

    def test_no_provider_or_write_tokens(self) -> None:
        for path in (UI, PRESENTATION):
            source = path.read_text(encoding="utf-8")
            lower = source.lower()
            for token in PROVIDER_TOKENS:
                with self.subTest(path=str(path), token=token):
                    self.assertNotIn(token.lower(), lower)
            for token in WRITE_TOKENS:
                with self.subTest(path=str(path), token=token):
                    self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
