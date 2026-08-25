from __future__ import annotations

import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from components.portfolio_decision_center_ui import (
    CONTRIBUTION_PLAN_TITLE,
    ActionCenterPresentation,
    PresentedAction,
)
from services.company_intelligence_contract import (
    CatalystItem,
    CompanyIntelligenceView,
    DataQualitySection,
    EarningsExpectations,
    EarningsSection,
    FinancialTrendsSection,
    IntelligenceObservation,
    IntelligenceProvenance,
    ValuationMetric,
    ValuationSection,
)
from services.investment_thesis_builder import build_investment_thesis_view
from services.nabi_decision_contract import (
    ACTION_BLOCKED_PARTICIPATION,
    ACTION_CONSIDER_NEW_POSITION,
    ACTION_CONSIDER_TOP_UP,
    ACTION_RESEARCH_FIRST,
    ACTION_WAIT,
    ACTION_WATCH,
    DECISION_PRECEDENCE,
    INVESTMENT_ACTIONS,
    TIMING_FAVORABLE,
    TIMING_WAIT,
)
from services.nabi_decision_orchestrator import (
    build_nabi_decision_v3,
    derive_timing_state,
    evaluate_candidate_investment,
)
from services.nabi_opportunity_comparison import best_deploy_comparison
from services.nabi_portfolio_fit import FIT_GOOD, FIT_POOR
from services.nabi_recommendation import (
    ACTION_REVIEW_GOAL_PLAN,
    build_nabi_recommendation,
)
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
)
from services.portfolio_decision_intelligence import (
    DecisionAction,
    DecisionActionStatus,
    DecisionCategory,
    DecisionPriority,
    PortfolioDecisionView,
)
from services.research_intelligence_contract import ResearchEvidenceRef
from services.research_intelligence_service import build_research_intelligence
from services.wealth_new_money_allocation import (
    REASON_EXISTING_HOLDING_TOPUP,
    REASON_STRONG_CANDIDATE,
    AllocationPlan,
    AllocationRecommendation,
)

NOW = datetime(2026, 8, 25, 7, 0, tzinfo=timezone.utc)
ENGINE = Path("services/nabi_recommendation.py")
SCORE = Path("services/nabi_score_v4.py")
HOME = Path("components/nabi_home_dashboard.py")
CENTER_UI = Path("components/opportunity_center_ui.py")
LIVE = ("ADBE", "ADSK", "BIIB", "CRM", "JNJ", "MU")


def _obs(code: str, statement: str = "canonical observation") -> IntelligenceObservation:
    return IntelligenceObservation(
        code=code,
        status="FACT",
        statement=statement,
        evidence=(("code", code),),
        source="test",
        confidence="HIGH",
    )


def _thesis(symbol: str, *, expensive: bool = False):
    position = "ABOVE_HISTORICAL_MEDIAN" if expensive else "BELOW_HISTORICAL_MEDIAN"
    current, median = (40.0, 20.0) if expensive else (18.0, 22.0)
    metric = ValuationMetric(
        code="pe_ratio",
        label="F/K",
        current_value=current,
        historical_median=median,
        premium_to_median_pct=100.0 if expensive else -18.0,
        position=position,
        meaningful=True,
    )
    view = CompanyIntelligenceView(
        symbol=symbol,
        company_name=symbol,
        as_of="2026-08-01",
        business_snapshot=None,
        financial_trends=FinancialTrendsSection(
            trends=(),
            observations=(_obs("GROSS_MARGIN_EXPANSION", "Gross margin expanded."),),
            provenance=IntelligenceProvenance(provider="fmp", data_family="financials"),
        ),
        earnings=EarningsSection(
            period="2024-Q1",
            comparison_type="YoY",
            observations=(_obs("FCF_CHANGE", "Free cash flow improved."),),
            expectations=EarningsExpectations(expectations_available=False),
            provenance=IntelligenceProvenance(provider="fmp", data_family="earnings"),
        ),
        valuation=ValuationSection(
            metrics=(metric,),
            observations=(),
            provenance=IntelligenceProvenance(provider="fmp", data_family="valuation"),
        ),
        peers=None,
        news=None,
        catalysts=(
            CatalystItem(
                code="EARNINGS",
                catalyst_type="EARNINGS",
                date="2026-08-20",
                description="Reported quarterly results already in Research.",
                source="company_intelligence",
                confidence="HIGH",
                status="OBSERVED",
            ),
        ),
        factual_risks=(),
        data_quality=DataQualitySection(
            company_profile_available=True,
            financial_history_available=True,
            quarterly_comparison_available=True,
            earnings_expectations_available=False,
            valuation_available=True,
            historical_valuation_available=True,
            peer_data_available=False,
            news_available=False,
            catalyst_data_available=True,
            warnings=(),
            provider_failures=(),
            partial_sections=(),
            as_of="2026-08-01",
        ),
        provenance=(),
    )
    return build_investment_thesis_view(view)


def _candidate(
    symbol: str,
    *,
    decision: str = "GÜÇLÜ ADAY",
    participation: str = PARTICIPATION_STATUS_UYGUN,
    score: float = 90.0,
    research: str = "TAMAMLANDI",
    confidence: str = "YÜKSEK",
) -> dict:
    return {
        "symbol": symbol,
        "company_name": symbol,
        "decision": decision,
        "participation_status": participation,
        "research_status": research,
        "research_confidence_level": confidence,
        "nabi_score": score,
        "current_price": 120.0,
        "data_completeness": 90.0 if confidence == "YÜKSEK" else 20.0,
        "data_source": "scanner",
        "main_reason": "Kaliteli büyüme",
        "thesis_strengths": ["Canonical growth evidence exists."],
        "growth_catalysts": "Reported quarter already in Research.",
        "critical_risk": "Customer concentration is already flagged.",
        "last_scanned_at": "2026-08-20T10:00:00+00:00",
    }


def _rec(symbol: str, *, reason: str, existing_or_new: str) -> AllocationRecommendation:
    return AllocationRecommendation(
        symbol=symbol,
        existing_or_new=existing_or_new,
        layer="equity",
        decision="GÜÇLÜ ADAY",
        price=Decimal("100"),
        price_currency="TRY",
        quantity=Decimal("1"),
        allocated_amount=Decimal("20000"),
        reason_code=reason,
        reason_text=reason,
    )


def _plan(*rows: AllocationRecommendation) -> AllocationPlan:
    allocated = sum((row.allocated_amount for row in rows), Decimal("0"))
    return AllocationPlan(
        input_amount=Decimal("60000"),
        currency="TRY",
        recommendations=rows,
        total_allocated=allocated,
        residual_cash=Decimal("60000") - allocated,
        skipped=(),
    )


def _monitor_decision() -> PortfolioDecisionView:
    action = DecisionAction(
        id="continue_observation",
        category=DecisionCategory.MONITOR,
        priority=DecisionPriority.INFO,
        title="Gözlem",
        explanation="Gözlem",
        evidence=(),
        status=DecisionActionStatus.OPEN,
    )
    return PortfolioDecisionView(
        actions=(action,),
        primary_action=action,
        evidence_complete=True,
        limitations=(),
        generated_from=("test",),
    )


def _plan_gap_presented() -> ActionCenterPresentation:
    return ActionCenterPresentation(
        heading="NABI Karar Merkezi",
        healthy=False,
        healthy_message=None,
        disclaimer="",
        visible_actions=(
            PresentedAction(
                id="contribution_plan_below_required",
                category_label="Hedef",
                priority_label="Yüksek",
                priority_tone="warning",
                title=CONTRIBUTION_PLAN_TITLE,
                explanation=CONTRIBUTION_PLAN_TITLE,
                evidence_lines=(),
                limitation=None,
                direction=None,
                options=(),
            ),
        ),
        hidden_count=0,
        evidence_summary=(),
        action_ids=("contribution_plan_below_required",),
        status_summary="konular",
        actionable_count=1,
        highest_severity_label="Yüksek",
    )


class PrecedenceAndTimingTests(unittest.TestCase):
    def test_precedence_is_explicit(self) -> None:
        self.assertEqual(
            DECISION_PRECEDENCE,
            (
                "PARTICIPATION",
                "EVIDENCE_COMPLETENESS",
                "COMPANY_ATTRACTIVENESS",
                "TIMING",
                "PORTFOLIO_FIT",
                "WEALTH_NEW_MONEY",
                "FINAL_RECOMMENDATION",
            ),
        )
        view = build_nabi_decision_v3(candidates=[], now=NOW)
        self.assertEqual(view.decision_precedence, DECISION_PRECEDENCE)
        self.assertFalse(view.persisted)
        self.assertFalse(view.audit.persisted)

    def test_timing_from_research_intelligence_only(self) -> None:
        favorable = build_research_intelligence(
            candidate=_candidate("CRM"),
            thesis=_thesis("CRM"),
            now=NOW,
        )
        self.assertEqual(derive_timing_state(favorable), TIMING_FAVORABLE)
        waiting = build_research_intelligence(
            candidate=_candidate("CRM"),
            thesis=_thesis("CRM", expensive=True),
            now=NOW,
        )
        self.assertEqual(derive_timing_state(waiting), TIMING_WAIT)
        unknown = build_research_intelligence(
            candidate={"symbol": "CRM", "participation_status": PARTICIPATION_STATUS_UYGUN},
            now=NOW,
        )
        self.assertEqual(derive_timing_state(unknown), "UNKNOWN")

    def test_no_buy_sell_vocabulary(self) -> None:
        self.assertNotIn("BUY", INVESTMENT_ACTIONS)
        self.assertNotIn("SELL", INVESTMENT_ACTIONS)
        self.assertNotIn("STRONG BUY", INVESTMENT_ACTIONS)


class AdversarialAcceptanceTests(unittest.TestCase):
    def test_a_kontrol_et_blocked(self) -> None:
        row = _candidate(
            "META",
            participation=PARTICIPATION_STATUS_KONTROL_ET,
            score=99,
        )
        extra = (
            ResearchEvidenceRef(
                source_type="x",
                source_reference="@acct",
                observed_at="2026-08-25",
                evidence_type="CATALYST",
                statement="Strong catalyst",
            ),
        )
        item = evaluate_candidate_investment(
            row,
            extra_evidence=extra,
            allocation=_plan(_rec("META", reason=REASON_STRONG_CANDIDATE, existing_or_new="new")),
            now=NOW,
        )
        self.assertEqual(item.final_action, ACTION_BLOCKED_PARTICIPATION)
        self.assertNotEqual(item.timing_state, TIMING_FAVORABLE)
        self.assertNotIn(item.final_action, {ACTION_CONSIDER_NEW_POSITION, ACTION_CONSIDER_TOP_UP})

    def test_b_low_research_is_research_first(self) -> None:
        item = evaluate_candidate_investment(
            _candidate("CRM", score=95, confidence="DÜŞÜK", research="TAMAMLANDI"),
            allocation=_plan(_rec("CRM", reason=REASON_STRONG_CANDIDATE, existing_or_new="new")),
            now=NOW,
        )
        self.assertEqual(item.final_action, ACTION_RESEARCH_FIRST)
        self.assertNotEqual(item.final_action, ACTION_CONSIDER_NEW_POSITION)

    def test_c_wait_timing(self) -> None:
        item = evaluate_candidate_investment(
            _candidate("CRM"),
            thesis=_thesis("CRM", expensive=True),
            allocation=_plan(_rec("CRM", reason=REASON_STRONG_CANDIDATE, existing_or_new="new")),
            now=NOW,
        )
        self.assertEqual(item.timing_state, TIMING_WAIT)
        self.assertEqual(item.final_action, ACTION_WAIT)

    def test_d_poor_fit_is_not_unsafe_deployment(self) -> None:
        portfolio = SimpleNamespace(
            priced_positions=(SimpleNamespace(symbol="MU", weight_pct=25.0),)
        )
        item = evaluate_candidate_investment(
            _candidate("MU"),
            thesis=_thesis("MU"),
            portfolio_view=portfolio,
            allocation=_plan(_rec("MU", reason=REASON_STRONG_CANDIDATE, existing_or_new="new")),
            now=NOW,
        )
        self.assertEqual(item.portfolio_fit, FIT_POOR)
        self.assertNotIn(item.final_action, {ACTION_CONSIDER_NEW_POSITION, ACTION_CONSIDER_TOP_UP})
        self.assertEqual(item.final_action, ACTION_WAIT)

    def test_e_consider_new_position(self) -> None:
        item = evaluate_candidate_investment(
            _candidate("CRM"),
            thesis=_thesis("CRM"),
            allocation=_plan(_rec("CRM", reason=REASON_STRONG_CANDIDATE, existing_or_new="new")),
            now=NOW,
        )
        self.assertEqual(item.final_action, ACTION_CONSIDER_NEW_POSITION)
        self.assertEqual(item.timing_state, TIMING_FAVORABLE)
        self.assertEqual(item.portfolio_fit, FIT_GOOD)

    def test_f_consider_top_up(self) -> None:
        portfolio = SimpleNamespace(
            priced_positions=(SimpleNamespace(symbol="MU", weight_pct=8.0),)
        )
        item = evaluate_candidate_investment(
            _candidate("MU"),
            thesis=_thesis("MU"),
            portfolio_view=portfolio,
            allocation=_plan(
                _rec("MU", reason=REASON_EXISTING_HOLDING_TOPUP, existing_or_new="existing")
            ),
            now=NOW,
        )
        self.assertEqual(item.final_action, ACTION_CONSIDER_TOP_UP)
        self.assertTrue(item.reason_codes)

    def test_g_opportunity_vs_deployment(self) -> None:
        mu = _candidate("MU", score=92)
        crm = _candidate("CRM", score=88)
        portfolio = SimpleNamespace(
            priced_positions=(SimpleNamespace(symbol="MU", weight_pct=25.0),)
        )
        plan = _plan(_rec("CRM", reason=REASON_STRONG_CANDIDATE, existing_or_new="new"))
        view = build_nabi_decision_v3(
            candidates=[mu, crm],
            theses={"MU": _thesis("MU"), "CRM": _thesis("CRM")},
            portfolio_view=portfolio,
            allocation=plan,
            decision=_monitor_decision(),
            valuation_complete=True,
            now=NOW,
        )
        self.assertEqual(view.opportunity_ranking[0], "MU")
        self.assertEqual(view.opportunity_leader, "MU")
        rec = build_nabi_recommendation(
            candidates=[mu, crm],
            portfolio_view=portfolio,
            allocation=plan,
            valuation_complete=True,
        )
        self.assertEqual([item.symbol for item in rec.comparisons], ["MU", "CRM"])
        deploy = best_deploy_comparison(rec.comparisons)
        self.assertEqual(deploy.symbol, "CRM")
        self.assertEqual(view.deployment_symbol, "CRM")
        self.assertEqual(view.final_action, ACTION_CONSIDER_NEW_POSITION)

    def test_h_wealth_priority_stays_dashboard_primary(self) -> None:
        view = build_nabi_decision_v3(
            candidates=[_candidate("CRM")],
            theses={"CRM": _thesis("CRM")},
            allocation=_plan(_rec("CRM", reason=REASON_STRONG_CANDIDATE, existing_or_new="new")),
            presented_actions=_plan_gap_presented(),
            decision=_monitor_decision(),
            valuation_complete=True,
            now=NOW,
        )
        self.assertEqual(view.dashboard_primary, ACTION_REVIEW_GOAL_PLAN)
        self.assertEqual(view.wealth_action, ACTION_REVIEW_GOAL_PLAN)
        self.assertEqual(view.final_action, ACTION_CONSIDER_NEW_POSITION)
        self.assertIn("WEALTH_PRIORITY", view.audit.reason_codes)


class FirewallAndCompatibilityTests(unittest.TestCase):
    def test_izle_is_watch_not_promoted(self) -> None:
        item = evaluate_candidate_investment(
            _candidate("CRM", decision="İZLE"),
            thesis=_thesis("CRM"),
            allocation=_plan(_rec("CRM", reason=REASON_STRONG_CANDIDATE, existing_or_new="new")),
            now=NOW,
        )
        self.assertEqual(item.final_action, ACTION_WATCH)

    def test_external_signal_cannot_set_consider(self) -> None:
        item = evaluate_candidate_investment(
            _candidate("NEWCO", participation=PARTICIPATION_STATUS_KONTROL_ET),
            extra_evidence=(
                ResearchEvidenceRef(
                    source_type="x",
                    source_reference="@acct",
                    observed_at="2026-08-25",
                    evidence_type="CATALYST",
                    statement="Buy now",
                ),
            ),
            now=NOW,
        )
        self.assertEqual(item.final_action, ACTION_BLOCKED_PARTICIPATION)
        self.assertIn("EXTERNAL_SIGNAL_NOT_AUTHORITY", item.reason_codes)

    def test_audit_fields_present(self) -> None:
        view = build_nabi_decision_v3(
            candidates=[_candidate("CRM")],
            theses={"CRM": _thesis("CRM")},
            allocation=_plan(_rec("CRM", reason=REASON_STRONG_CANDIDATE, existing_or_new="new")),
            valuation_complete=True,
            now=NOW,
        )
        payload = view.audit.to_dict()
        for key in (
            "recommendation_id",
            "generated_at",
            "symbol",
            "final_action",
            "participation_status",
            "research_completeness",
            "decision_class",
            "nabi_score",
            "timing_state",
            "portfolio_fit",
            "wealth_action",
            "reason_codes",
            "evidence_references",
            "persisted",
        ):
            self.assertIn(key, payload)
        self.assertFalse(payload["persisted"])
        self.assertTrue(payload["reason_codes"])

    def test_v1_recommendation_untouched(self) -> None:
        rec = build_nabi_recommendation(
            candidates=[_candidate("ADSK", research="YENI")],
            decision=_monitor_decision(),
            valuation_complete=True,
        )
        self.assertIn(rec.action_code, {"RESEARCH_OPPORTUNITY", "CONSIDER_NEW_POSITION", "NO_ACTION"})
        self.assertNotIn("build_nabi_decision_v3", ENGINE.read_text(encoding="utf-8"))
        self.assertTrue(SCORE.exists())

    def test_live_approved_names_are_research_first(self) -> None:
        rows = [
            {"symbol": symbol, "participation_status": PARTICIPATION_STATUS_UYGUN}
            for symbol in LIVE
        ]
        view = build_nabi_decision_v3(candidates=rows, now=NOW)
        self.assertEqual(view.final_action, ACTION_RESEARCH_FIRST)
        for item in view.candidate_decisions:
            self.assertEqual(item.final_action, ACTION_RESEARCH_FIRST)
        self.assertEqual(view.opportunity_ranking, ())

    def test_ui_has_compact_decision_copy(self) -> None:
        home = HOME.read_text(encoding="utf-8")
        firsat = CENTER_UI.read_text(encoding="utf-8")
        self.assertIn("Final action:", home)
        self.assertIn("Timing:", home)
        self.assertIn("Why / reason:", home)
        self.assertIn("Final action:", firsat)
        self.assertIn("NABI ÖNERİSİ", ENGINE.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
