from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from components.portfolio_decision_center_ui import (
    CONTRIBUTION_PLAN_TITLE,
    EVIDENCE_EXPANDER_LABEL,
    HEADING,
    HEALTHY_MESSAGE,
    PLAN_OPTIONS,
    flatten_presentation_text,
    present_action_center,
)
from services.portfolio_decision_intelligence import (
    DecisionAction,
    DecisionActionStatus,
    DecisionCategory,
    DecisionPriority,
    PortfolioDecisionView,
    build_portfolio_decision,
)
from services.wealth_contribution_intelligence import build_contribution_intelligence
from services.wealth_external_cash_flow import ContributionReconciliation
from services.wealth_goal_center_presentation import (
    build_goal_center_dashboard,
    format_money_display,
)
from services.wealth_goal_models import (
    ContributionPlan,
    current_wealth_from_portfolio_view,
    default_contribution_plan,
    default_wealth_goal_2031,
)
from services.wealth_planning_fx import required_planning_fx_years, schedule_from_mapping
from tests.test_portfolio_decision_center_ui import (
    ACCOUNT,
    AS_OF,
    PROVIDER_TOKENS,
    UI,
    WRITE_TOKENS,
    _healthy_view,
    _live_like_decision,
    _partial_bist_view,
    _deposit,
)
from tests.test_portfolio_decision_intelligence import _complete_usd_view


TRACKING_START = date(2026, 1, 1)


def _recon():
    return (ContributionReconciliation(portfolio_id="pf-1", reconciled_through=AS_OF),)


def _fx_complete():
    years = required_planning_fx_years(AS_OF, default_wealth_goal_2031().target_date)
    return schedule_from_mapping({year: Decimal("34") for year in years})


def _below_required_bundle():
    portfolio = _complete_usd_view(value=10000.0)
    current = current_wealth_from_portfolio_view(portfolio)
    fx = _fx_complete()
    plan = default_contribution_plan()
    intelligence = build_contribution_intelligence(
        as_of_date=AS_OF,
        current=current,
        transactions=[_deposit(50000)],
        account_ids=[ACCOUNT],
        plan=plan,
        contribution_reconciliations=_recon(),
        contribution_tracking_start=TRACKING_START,
        fx_schedule=fx,
    )
    decision = build_portfolio_decision(
        portfolio,
        as_of_date=AS_OF,
        plan=plan,
        current_wealth=current,
        contribution=intelligence,
        transactions=[_deposit(50000)],
        account_ids=[ACCOUNT],
        contribution_reconciliations=_recon(),
        contribution_tracking_start=TRACKING_START,
        fx_schedule=fx,
    )
    dashboard = build_goal_center_dashboard(
        as_of_date=AS_OF,
        goal=default_wealth_goal_2031(),
        plan=plan,
        snapshot=current,
        fx_schedule=fx,
        intelligence=intelligence,
        tracking_start=TRACKING_START,
    )
    return decision, dashboard


def _action(priority: DecisionPriority) -> DecisionAction:
    return DecisionAction(
        id=f"sample_{priority.value.lower()}",
        category=DecisionCategory.PLAN,
        priority=priority,
        title=priority.value,
        explanation="fixture",
        evidence=(),
        status=DecisionActionStatus.OPEN,
    )


class NoSignalTests(unittest.TestCase):
    def test_healthy_state_uses_engine_only(self) -> None:
        decision = build_portfolio_decision(
            _healthy_view(),
            as_of_date=AS_OF,
            plan=ContributionPlan(
                starting_monthly=Decimal("20000"),
                currency="USD",
                annual_increase_rate=Decimal("0"),
            ),
            transactions=[_deposit(20000)],
            account_ids=[ACCOUNT],
            contribution_reconciliations=_recon(),
            contribution_tracking_start=TRACKING_START,
        )
        presented = present_action_center(decision)
        self.assertTrue(presented.healthy)
        self.assertEqual(presented.heading, "NABI Karar Merkezi")
        self.assertEqual(presented.heading, HEADING)
        self.assertEqual(presented.status_summary, HEALTHY_MESSAGE)
        self.assertEqual(presented.actionable_count, 0)
        self.assertIsNone(presented.highest_severity_label)
        self.assertEqual(presented.visible_actions[0].id, "continue_observation")


class ContributionPlanCardTests(unittest.TestCase):
    def test_below_required_card_uses_canonical_evidence(self) -> None:
        decision, dashboard = _below_required_bundle()
        self.assertIn("contribution_plan_below_required", [row.id for row in decision.actions])
        presented = present_action_center(decision)
        card = next(
            row for row in presented.visible_actions if row.id == "contribution_plan_below_required"
        )
        self.assertEqual(card.title, CONTRIBUTION_PLAN_TITLE)
        self.assertEqual(card.priority_label, "Yüksek")
        self.assertEqual(card.options, PLAN_OPTIONS)
        self.assertIn("Mevcut aylık katkı", " ".join(card.evidence_lines))
        self.assertIn("Gerekli başlangıç aylık katkı", " ".join(card.evidence_lines))
        self.assertIn("Fark", " ".join(card.evidence_lines))
        self.assertIn("Hedef yılı: 2031", " ".join(card.evidence_lines))
        self.assertNotIn("contribution_plan_below_required", card.title)
        self.assertNotIn("contribution_plan_below_required", card.explanation)
        self.assertGreater(presented.actionable_count, 0)
        self.assertEqual(presented.highest_severity_label, "Yüksek")
        self.assertIn(dashboard.required.required_label, " ".join(card.evidence_lines))
        self.assertIn(dashboard.required.current_label, " ".join(card.evidence_lines))

    def test_required_matches_goal_center(self) -> None:
        decision, dashboard = _below_required_bundle()
        action = next(
            row for row in decision.actions if row.id == "contribution_plan_below_required"
        )
        presented = present_action_center(decision)
        card = next(
            row for row in presented.visible_actions if row.id == "contribution_plan_below_required"
        )
        self.assertEqual(
            Decimal(str(action.context["required_starting_monthly"])),
            dashboard.required.required_monthly,
        )
        self.assertEqual(
            format_money_display(dashboard.required.required_monthly, "TRY"),
            dashboard.required.required_label,
        )
        self.assertIn(dashboard.required.required_label, flatten_presentation_text(presented))
        expected_gap = format_money_display(
            dashboard.required.required_monthly - dashboard.plan.starting_monthly,
            "TRY",
        )
        self.assertIn(expected_gap, " ".join(card.evidence_lines))


class SeverityAndMappingTests(unittest.TestCase):
    def test_severity_labels_are_translations_only(self) -> None:
        presented = present_action_center(
            PortfolioDecisionView(
                actions=(
                    _action(DecisionPriority.HIGH),
                    _action(DecisionPriority.MEDIUM),
                    _action(DecisionPriority.LOW),
                ),
                primary_action=_action(DecisionPriority.HIGH),
                evidence_complete=True,
                limitations=(),
                generated_from="test",
            )
        )
        labels = [row.priority_label for row in presented.visible_actions]
        self.assertEqual(labels, ["Yüksek", "Orta", "Düşük"])
        self.assertEqual(presented.highest_severity_label, "Yüksek")
        self.assertEqual(presented.actionable_count, 3)

    def test_incomplete_valuation_mapping(self) -> None:
        presented = present_action_center(_live_like_decision())
        card = presented.visible_actions[0]
        self.assertEqual(card.id, "incomplete_valuation")
        self.assertEqual(card.title, "Portföy değerlemesini tamamla")
        self.assertIn("alt sınır", card.explanation)
        self.assertTrue(card.options)
        self.assertNotIn("incomplete_valuation", card.title)

    def test_missing_planning_fx_mapping(self) -> None:
        presented = present_action_center(_live_like_decision())
        card = next(row for row in presented.visible_actions if row.id == "missing_planning_fx")
        self.assertEqual(card.title, "2031 planı için kur varsayımı gerekli")
        self.assertIn("planlama kur varsayımları", card.explanation)
        self.assertEqual(card.options, ("Planlama kur varsayımlarını gir",))

    def test_concentration_mapping(self) -> None:
        decision = build_portfolio_decision(
            _partial_bist_view(top_weight=40.0),
            as_of_date=AS_OF,
        )
        presented = present_action_center(decision)
        card = next(row for row in presented.visible_actions if row.id == "concentration_review")
        self.assertEqual(card.title, "Yoğunlaşmayı gözden geçir")
        self.assertIn("fiyatlı / gözlemlenebilir", card.explanation)
        self.assertIn("satış önerisi değildir", card.explanation)
        self.assertEqual(card.options, ("Yoğunlaşmayı izlemeye devam et",))
        self.assertNotIn("concentration_review", card.title)

    def test_details_preserve_raw_evidence(self) -> None:
        presented = present_action_center(_live_like_decision())
        summary = "\n".join(presented.evidence_summary)
        self.assertEqual(EVIDENCE_EXPANDER_LABEL, "Detaylar")
        self.assertIn("Değerleme: kısmi", summary)
        self.assertIn("Katkı kanıtı", summary)
        decision, dashboard = _below_required_bundle()
        card = next(
            row
            for row in present_action_center(decision).visible_actions
            if row.id == "contribution_plan_below_required"
        )
        self.assertTrue(card.details_lines)
        self.assertTrue(any("Gerekli başlangıç aylık (kanıt)" in line for line in card.details_lines))
        self.assertIn(str(dashboard.required.required_monthly), " ".join(card.details_lines))


class SafetyTests(unittest.TestCase):
    def test_no_writes_or_providers_in_ui(self) -> None:
        source = UI.read_text(encoding="utf-8")
        lower = source.lower()
        for token in PROVIDER_TOKENS:
            self.assertNotIn(token.lower(), lower)
        for token in WRITE_TOKENS:
            self.assertNotIn(token, source)
        self.assertNotIn("save_planning_fx_schedule", source)
        self.assertNotIn("set_contribution_tracking_start", source)
        self.assertIn("build_portfolio_decision", source)
        self.assertIn("format_money_display", source)
        self.assertIn("Katkı planını uygulamak için dağılım senaryosunu görüntüle", source)


if __name__ == "__main__":
    unittest.main()
