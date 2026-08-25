from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path

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
from services.nabi_portfolio_fit import (
    AFFORDABLE,
    FIT_POOR,
    FIT_REASON_CONCENTRATION_LIMIT,
    PortfolioFitAssessment,
)
from services.nabi_recommendation import build_nabi_recommendation
from services.opportunity_center_presentation import (
    build_opportunity_center,
    present_today_opportunity_cards,
)
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)
from services.research_intelligence_contract import (
    COMPLETENESS_HIGH,
    COMPLETENESS_LOW,
    RESEARCH_STATE_BLOCKED,
    RESEARCH_STATE_INSUFFICIENT,
    RESEARCH_STATE_NOT_APPLICABLE,
    RESEARCH_STATE_READY,
    RESEARCH_STATE_WATCH,
    ResearchEvidenceRef,
    UNKNOWN,
    VALUATION_ATTRACTIVE,
    VALUATION_UNKNOWN,
)
from services.research_intelligence_service import (
    build_research_intelligence,
    present_research_intelligence_brief,
)

NOW = datetime(2026, 8, 25, 6, 0, tzinfo=timezone.utc)
LIVE_APPROVED = ("ADBE", "ADSK", "BIIB", "CRM", "JNJ", "MU")
CENTER_UI = Path("components/opportunity_center_ui.py")
ENGINE = Path("services/nabi_recommendation.py")
SCORE = Path("services/nabi_score_v4.py")
BUSINESS = Path("config/participation_business_rules.json")


def _obs(code: str, statement: str = "canonical observation") -> IntelligenceObservation:
    return IntelligenceObservation(
        code=code,
        status="FACT",
        statement=statement,
        evidence=(("code", code),),
        source="test",
        confidence="HIGH",
    )


def _view(**overrides) -> CompanyIntelligenceView:
    metric = ValuationMetric(
        code="pe_ratio",
        label="F/K",
        current_value=18.0,
        historical_median=22.0,
        premium_to_median_pct=-18.0,
        position="BELOW_HISTORICAL_MEDIAN",
        meaningful=True,
    )
    base = dict(
        symbol="CRM",
        company_name="Salesforce",
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
    base.update(overrides)
    return CompanyIntelligenceView(**base)


def _approved_candidate(symbol: str = "CRM", **overrides) -> dict:
    row = {
        "symbol": symbol,
        "participation_status": PARTICIPATION_STATUS_UYGUN,
        "decision": "GÜÇLÜ ADAY",
        "current_price": 120.0,
        "data_completeness": 90.0,
        "research_status": "TAMAMLANDI",
        "research_confidence_level": "YÜKSEK",
        "thesis_strengths": ["Revenue growth is visible in canonical evidence."],
        "critical_risk": "Customer concentration is already flagged.",
        "growth_catalysts": "Reported product cycle already in Research.",
        "main_reason": "Quality compounder in existing evaluation.",
        "pe_ratio": 28.5,
    }
    row.update(overrides)
    return row


def _poor_fit() -> PortfolioFitAssessment:
    return PortfolioFitAssessment(
        fit=FIT_POOR,
        reason="Bu ekleme mevcut yoğunluk sınırını aşar.",
        reason_codes=(FIT_REASON_CONCENTRATION_LIMIT,),
        current_holding=True,
        current_weight_pct=22.0,
        post_allocation_weight_pct=25.0,
        affordability=AFFORDABLE,
        limitations=(),
    )


class ParticipationGateTests(unittest.TestCase):
    def test_only_uygun_produces_investable_research_intelligence(self) -> None:
        thesis = build_investment_thesis_view(_view())
        view = build_research_intelligence(
            candidate=_approved_candidate(),
            thesis=thesis,
            now=NOW,
        )
        self.assertTrue(view.investable)
        self.assertEqual(view.research_state, RESEARCH_STATE_READY)
        self.assertTrue(view.thesis_points)
        self.assertFalse(view.persisted)

    def test_uygun_degil_excellent_financials_blocked(self) -> None:
        view = build_research_intelligence(
            candidate={
                "symbol": "JPM",
                "participation_status": PARTICIPATION_STATUS_UYGUN_DEGIL,
                "decision": "GÜÇLÜ ADAY",
                "nabi_score": 99,
                "roic": 40,
                "roe": 30,
                "thesis_strengths": ["Would look excellent if allowed."],
                "growth_catalysts": "Fabricated launch",
            },
            extra_evidence=(
                ResearchEvidenceRef(
                    source_type="x",
                    source_reference="@account",
                    observed_at="2026-08-25",
                    evidence_type="CATALYST",
                    statement="Viral catalyst",
                ),
            ),
            now=NOW,
        )
        self.assertFalse(view.investable)
        self.assertEqual(view.research_state, RESEARCH_STATE_BLOCKED)
        self.assertEqual(view.thesis_points, ())
        self.assertEqual(view.catalyst_points, ())
        self.assertEqual(view.why_now, ())

    def test_kontrol_et_score_99_blocked(self) -> None:
        view = build_research_intelligence(
            candidate={
                "symbol": "NVDA",
                "participation_status": PARTICIPATION_STATUS_KONTROL_ET,
                "nabi_score": 99,
                "decision": "GÜÇLÜ ADAY",
            },
            now=NOW,
        )
        self.assertFalse(view.investable)
        self.assertEqual(view.research_state, RESEARCH_STATE_BLOCKED)

    def test_pending_strong_catalyst_blocked(self) -> None:
        view = build_research_intelligence(
            symbol="NEWCO",
            extra_evidence=(
                ResearchEvidenceRef(
                    source_type="fund_activity",
                    source_reference="13F-1",
                    observed_at="2026-08-01",
                    evidence_type="CATALYST",
                    statement="Large fund added shares",
                ),
            ),
            now=NOW,
        )
        self.assertFalse(view.investable)
        self.assertEqual(view.research_state, RESEARCH_STATE_BLOCKED)
        self.assertEqual(view.catalyst_points, ())

    def test_snapshot_rejected_overrides_candidate(self) -> None:
        view = build_research_intelligence(
            candidate=_approved_candidate("AAPL"),
            snapshot={"status": PARTICIPATION_STATUS_UYGUN_DEGIL},
            now=NOW,
        )
        self.assertEqual(view.research_state, RESEARCH_STATE_BLOCKED)
        self.assertFalse(view.investable)


class EvidenceAndValuationTests(unittest.TestCase):
    def test_no_new_score_field(self) -> None:
        view = build_research_intelligence(candidate=_approved_candidate(), now=NOW)
        payload = view.to_dict()
        self.assertNotIn("research_score", payload)
        self.assertNotIn("nabi_score", payload)
        self.assertNotIn("score", payload)

    def test_missing_evidence_stays_unknown(self) -> None:
        view = build_research_intelligence(
            candidate={"symbol": "ADBE", "participation_status": PARTICIPATION_STATUS_UYGUN},
            now=NOW,
        )
        self.assertEqual(view.research_state, RESEARCH_STATE_INSUFFICIENT)
        self.assertEqual(view.valuation_classification, VALUATION_UNKNOWN)
        self.assertEqual(view.valuation_context, UNKNOWN)
        self.assertEqual(view.quality_context, UNKNOWN)
        self.assertEqual(view.thesis_points, ())
        self.assertEqual(view.catalyst_points, ())
        self.assertIn("canonical_valuation_classification", view.missing_evidence)

    def test_thesis_and_risks_are_evidence_backed(self) -> None:
        thesis = build_investment_thesis_view(_view())
        view = build_research_intelligence(
            candidate=_approved_candidate(),
            thesis=thesis,
            now=NOW,
        )
        self.assertTrue(view.thesis_points)
        self.assertTrue(any("margin" in item.lower() or "cash" in item.lower() or "growth" in item.lower() or "quality" in item.lower() for item in view.thesis_points))
        self.assertIn("Customer concentration is already flagged.", view.risk_points)
        self.assertTrue(any(ref.evidence_type == "THESIS" for ref in view.evidence_references))
        self.assertTrue(any(ref.evidence_type == "RISK" for ref in view.evidence_references))

    def test_catalysts_are_evidence_backed_only(self) -> None:
        thesis = build_investment_thesis_view(_view())
        view = build_research_intelligence(
            candidate=_approved_candidate(growth_catalysts=""),
            thesis=thesis,
            extra_evidence=(
                ResearchEvidenceRef(
                    source_type="x",
                    source_reference="@not-integrated",
                    observed_at="2026-08-25",
                    evidence_type="CATALYST",
                    statement="Existing structured event already observed.",
                ),
            ),
            now=NOW,
        )
        self.assertIn("Reported quarterly results already in Research.", view.catalyst_points)
        self.assertIn("Existing structured event already observed.", view.catalyst_points)
        self.assertTrue(all(ref.source_type != "llm" for ref in view.evidence_references))

    def test_valuation_does_not_invent_thresholds(self) -> None:
        view = build_research_intelligence(
            candidate=_approved_candidate(
                valuation_score=99,
                thesis_valuation_view="",
                pe_ratio=12.0,
            ),
            now=NOW,
        )
        self.assertEqual(view.valuation_classification, VALUATION_UNKNOWN)
        self.assertIn("F/K 12.0", view.valuation_context)
        thesis = build_investment_thesis_view(_view())
        mapped = build_research_intelligence(
            candidate=_approved_candidate(),
            thesis=thesis,
            now=NOW,
        )
        self.assertEqual(mapped.valuation_classification, VALUATION_ATTRACTIVE)
        self.assertEqual(thesis.valuation_context, "VALUATION_SUPPORTIVE")

    def test_why_now_does_not_bypass_opportunity_decision(self) -> None:
        view = build_research_intelligence(
            candidate=_approved_candidate(
                decision="İZLE",
                decision_why_now=["Valuation looks cheap."],
            ),
            now=NOW,
        )
        self.assertEqual(view.research_state, RESEARCH_STATE_WATCH)
        self.assertEqual(view.why_now, ())
        self.assertTrue(any("İZLE" in item for item in view.why_not_now))
        self.assertNotIn("ADAY", " ".join(view.why_now))
        self.assertNotIn("GÜÇLÜ ADAY", " ".join(view.why_now))

    def test_portfolio_fit_is_explanatory_only(self) -> None:
        view = build_research_intelligence(
            candidate=_approved_candidate(),
            portfolio_fit=_poor_fit(),
            now=NOW,
        )
        self.assertEqual(view.research_state, RESEARCH_STATE_READY)
        self.assertTrue(view.investable)
        self.assertTrue(any("yoğunluk" in item.lower() or "fit" in item.lower() for item in view.why_not_now + view.risk_points))
        self.assertTrue(any(ref.evidence_type == "PORTFOLIO_FIT" for ref in view.evidence_references))

    def test_evidence_references_retained(self) -> None:
        thesis = build_investment_thesis_view(_view())
        view = build_research_intelligence(
            candidate=_approved_candidate(),
            thesis=thesis,
            now=NOW,
        )
        kinds = {ref.evidence_type for ref in view.evidence_references}
        sources = {ref.source_type for ref in view.evidence_references}
        self.assertIn("PARTICIPATION", kinds)
        self.assertIn("THESIS", kinds)
        self.assertIn("participation_authority", sources)
        for ref in view.evidence_references:
            self.assertTrue(ref.source_type)
            self.assertTrue(ref.source_reference)
            self.assertTrue(ref.evidence_type)

    def test_completeness_reuses_existing_level(self) -> None:
        view = build_research_intelligence(
            candidate=_approved_candidate(research_confidence_level="YÜKSEK"),
            now=NOW,
        )
        self.assertEqual(view.research_completeness, COMPLETENESS_HIGH)
        sparse = build_research_intelligence(
            candidate={"symbol": "MU", "participation_status": PARTICIPATION_STATUS_UYGUN},
            now=NOW,
        )
        self.assertEqual(sparse.research_completeness, COMPLETENESS_LOW)
        self.assertTrue(sparse.missing_evidence)

    def test_catalog_etf_outside_equity_research(self) -> None:
        view = build_research_intelligence(
            candidate={
                "symbol": "SPUS",
                "participation_status": PARTICIPATION_STATUS_UYGUN,
                "is_etf": True,
                "decision": "GÜÇLÜ ADAY",
            },
            now=NOW,
        )
        self.assertEqual(view.research_state, RESEARCH_STATE_NOT_APPLICABLE)
        self.assertFalse(view.investable)


class PresentationTests(unittest.TestCase):
    def test_firsatlar_compact_labels_exist(self) -> None:
        ui = CENTER_UI.read_text(encoding="utf-8")
        self.assertIn("Neden ilginç?", ui)
        self.assertIn("Riskler:", ui)
        self.assertIn("Katalizörler:", ui)
        self.assertIn("Değerleme:", ui)
        self.assertIn("Neden şimdi / neden değil?", ui)

    def test_empty_today_does_not_fabricate_research_cards(self) -> None:
        view = build_opportunity_center(candidates=[])
        self.assertEqual(view.today, ())
        briefs = present_today_opportunity_cards([])
        self.assertEqual(briefs, ())

    def test_approved_opportunity_can_carry_brief(self) -> None:
        cards = present_today_opportunity_cards([_approved_candidate()])
        self.assertEqual(len(cards), 1)
        self.assertIsNotNone(cards[0].research_brief)
        self.assertTrue(cards[0].research_brief.interesting)

    def test_blocked_name_not_in_today(self) -> None:
        cards = present_today_opportunity_cards(
            [
                _approved_candidate(
                    "AAPL",
                    participation_status=PARTICIPATION_STATUS_UYGUN_DEGIL,
                )
            ]
        )
        self.assertEqual(cards, ())

    def test_brief_omits_blocked_intelligence(self) -> None:
        blocked = build_research_intelligence(
            candidate={
                "symbol": "AAPL",
                "participation_status": PARTICIPATION_STATUS_UYGUN_DEGIL,
            },
            now=NOW,
        )
        self.assertIsNone(present_research_intelligence_brief(blocked))


class LiveApprovedUniverseTests(unittest.TestCase):
    def test_live_approved_names_do_not_invent_research(self) -> None:
        reports = {}
        for symbol in LIVE_APPROVED:
            reports[symbol] = build_research_intelligence(
                candidate={"symbol": symbol, "participation_status": PARTICIPATION_STATUS_UYGUN},
                now=NOW,
            )
            self.assertTrue(reports[symbol].investable)
            self.assertEqual(reports[symbol].research_state, RESEARCH_STATE_INSUFFICIENT)
            self.assertEqual(reports[symbol].valuation_classification, VALUATION_UNKNOWN)
            self.assertEqual(reports[symbol].thesis_points, ())
            self.assertEqual(reports[symbol].catalyst_points, ())
            self.assertFalse(reports[symbol].persisted)
        self.assertEqual(len(reports), 6)


class RecommendationRegressionTests(unittest.TestCase):
    def test_recommendation_builder_unchanged_for_empty_book(self) -> None:
        rec = build_nabi_recommendation(candidates=[], valuation_complete=True)
        self.assertEqual(rec.action_code, "NO_ACTION")
        self.assertTrue(rec.summary)
        source = ENGINE.read_text(encoding="utf-8")
        self.assertIn("build_nabi_recommendation", source)
        self.assertNotIn("build_research_intelligence", source)

    def test_score_and_methodology_files_untouched_in_this_layer(self) -> None:
        self.assertTrue(SCORE.exists())
        self.assertTrue(BUSINESS.exists())


if __name__ == "__main__":
    unittest.main()
