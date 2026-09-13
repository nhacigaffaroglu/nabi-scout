from __future__ import annotations

import json
import unittest

from services.ai_research_summary_prompt import build_ai_summary_payload
from services.ai_research_summary_service import (
    build_summary_constraints,
    compute_ci_semantic_fingerprint,
)
from services.ai_research_summary_valuation_semantics import (
    ValuationSemantics,
    authoritative_valuation_summary,
    derive_valuation_semantics,
    valuation_semantics_from_snapshot,
)
from services.ai_research_summary_validator import (
    AIResearchSummaryConstraints,
    parse_ai_summary_response,
    validate_ai_research_summary,
)
from services.company_intelligence_contract import (
    CompanyIntelligenceView,
    DataQualitySection,
    IntelligenceProvenance,
    ValuationMetric,
    ValuationSection,
)
from services.unified_research_contract import (
    ParticipationResearchContext,
    UnifiedResearchContext,
)
from services.unified_research_serializer import serialize_company_intelligence_for_adviser


def _historical_unified() -> UnifiedResearchContext:
    metrics = [
        {
            "code": "price_to_sales",
            "label": "P/S",
            "current_value": 6.25,
            "historical_median": 5.0,
            "premium_to_median_pct": 25.0,
            "position": "ABOVE_HISTORICAL_RANGE",
            "source_provider": "sec+fmp",
            "confidence": "MEDIUM",
            "historical_sample_count": 5,
            "historical_method": "sec_annual_fiscal_price",
        },
        {
            "code": "price_to_fcf",
            "label": "P/FCF",
            "current_value": 25.0,
            "historical_median": 20.0,
            "premium_to_median_pct": 25.0,
            "position": "ABOVE_HISTORICAL_MEDIAN",
            "source_provider": "sec+fmp",
            "confidence": "MEDIUM",
            "historical_sample_count": 5,
            "historical_method": "sec_annual_fiscal_price",
        },
    ]
    dq = {
        "financial_history_available": True,
        "quarterly_comparison_available": False,
        "earnings_expectations_available": False,
        "valuation_available": True,
        "historical_valuation_available": True,
        "peer_data_available": False,
        "news_available": False,
        "catalyst_data_available": False,
    }
    return UnifiedResearchContext(
        symbol="CRM",
        company_name="CRM Inc.",
        schema_version="unified-research-v1",
        generated_at="2026-09-13T00:00:00+00:00",
        company_intelligence={
            "symbol": "CRM",
            "valuation_metrics": metrics,
            "data_quality": dict(dq),
        },
        investment_thesis={
            "symbol": "CRM",
            "thesis_status": "MIXED",
            "confidence": "MEDIUM",
            "valuation_context": "VALUATION_DEMANDING",
        },
        nabi_context=None,
        participation_context=ParticipationResearchContext(
            status="Uygun",
            confidence="MEDIUM",
            assessed_at="2026-09-13T00:00:00Z",
            limitations=(),
        ),
        wealth_exposure_context=None,
        portfolio_fit=(),
        investor_profile={},
        active_goals=(),
        monitoring_plan=(),
        thesis_change_summary=(),
        data_quality=dict(dq),
        provenance=(),
        focus_symbol="CRM",
    )


def _summary_json(valuation_summary: str) -> str:
    return json.dumps(
        {
            "financial_outlook": "Finansal görünüm izleniyor.",
            "valuation_summary": valuation_summary,
            "key_strengths": [],
            "key_weaknesses": [],
            "risks_to_watch": [],
            "missing_evidence": [],
            "monitoring_points": [],
            "limitations": [],
            "evidence_level": "LIMITED",
        },
        ensure_ascii=False,
    )


class HistoricalValuationTruthfulnessTests(unittest.TestCase):
    def test_unified_serializer_preserves_historical_metric_fields(self) -> None:
        metric = ValuationMetric(
            code="price_to_sales",
            label="P/S",
            current_value=6.25,
            historical_median=5.0,
            premium_to_median_pct=25.0,
            position="ABOVE_HISTORICAL_RANGE",
            source_provider="sec+fmp",
            confidence="MEDIUM",
            components=(("historical_sample_count", 5), ("historical_method", "sec_annual_fiscal_price")),
        )
        view = CompanyIntelligenceView(
            symbol="CRM",
            company_name="CRM Inc.",
            as_of="2026-09-13T00:00:00Z",
            business_snapshot=None,
            financial_trends=None,
            earnings=None,
            valuation=ValuationSection(
                metrics=(metric,),
                observations=(),
                provenance=IntelligenceProvenance(
                    provider="sec+fmp",
                    data_family="sec_annual_market_hybrid",
                    retrieved_at="2026-09-13T00:00:00Z",
                ),
            ),
            peers=None,
            news=None,
            data_quality=DataQualitySection(
                company_profile_available=True,
                financial_history_available=True,
                quarterly_comparison_available=False,
                earnings_expectations_available=False,
                valuation_available=True,
                historical_valuation_available=True,
                peer_data_available=False,
                news_available=False,
                catalyst_data_available=False,
                warnings=(),
                provider_failures=(),
                partial_sections=(),
                as_of="2026-09-13T00:00:00Z",
            ),
        )
        payload = serialize_company_intelligence_for_adviser(view)
        assert payload is not None
        serialized = payload["valuation_metrics"][0]
        self.assertEqual(serialized["historical_median"], 5.0)
        self.assertEqual(serialized["premium_to_median_pct"], 25.0)
        self.assertEqual(serialized["position"], "ABOVE_HISTORICAL_RANGE")
        self.assertEqual(serialized["source_provider"], "sec+fmp")
        self.assertEqual(serialized["confidence"], "MEDIUM")
        self.assertEqual(serialized["historical_sample_count"], 5)
        self.assertEqual(serialized["historical_method"], "sec_annual_fiscal_price")

    def test_semantics_preserve_historical_context_and_build_safe_relative_summary(self) -> None:
        semantics = derive_valuation_semantics(_historical_unified())
        self.assertTrue(semantics.historical_median_available)
        metric = semantics.available_metrics[0]
        self.assertEqual(metric["historical_median"], 5.0)
        self.assertEqual(metric["premium_to_median_pct"], 25.0)
        self.assertEqual(metric["position"], "ABOVE_HISTORICAL_RANGE")
        self.assertEqual(metric["source_provider"], "sec+fmp")
        self.assertEqual(metric["confidence"], "MEDIUM")
        self.assertEqual(metric["historical_sample_count"], 5)
        self.assertEqual(metric["historical_method"], "sec_annual_fiscal_price")
        summary = authoritative_valuation_summary(semantics)
        assert summary is not None
        self.assertIn("P/S", summary)
        self.assertIn("6.25", summary)
        self.assertIn("5", summary)
        self.assertIn("%25 daha yüksek", summary)
        self.assertIn("tarihsel bandın üzerinde", summary)
        self.assertIn("Benzer şirket karşılaştırması mevcut değil", summary)
        self.assertNotIn("ucuz", summary.lower())
        self.assertNotIn("pahalı", summary.lower())

    def test_ci_semantic_fingerprint_tracks_historical_evidence_identity(self) -> None:
        def build(sample_count: int, provider: str) -> CompanyIntelligenceView:
            metric = ValuationMetric(
                code="price_to_sales",
                label="P/S",
                current_value=6.25,
                historical_median=5.0,
                premium_to_median_pct=25.0,
                position="ABOVE_HISTORICAL_RANGE",
                source_provider=provider,
                confidence="MEDIUM",
                components=(("historical_sample_count", sample_count),),
            )
            return CompanyIntelligenceView(
                symbol="CRM",
                company_name="CRM Inc.",
                as_of="2026-09-13T00:00:00Z",
                business_snapshot=None,
                financial_trends=None,
                earnings=None,
                valuation=ValuationSection(
                    metrics=(metric,),
                    observations=(),
                    provenance=IntelligenceProvenance(
                        provider=provider,
                        data_family="sec_annual_market_hybrid",
                    ),
                ),
                peers=None,
                news=None,
                data_quality=None,
            )

        base = compute_ci_semantic_fingerprint(build(5, "sec+fmp"))
        different_count = compute_ci_semantic_fingerprint(build(4, "sec+fmp"))
        different_provider = compute_ci_semantic_fingerprint(build(5, "alternate"))
        self.assertNotEqual(base, different_count)
        self.assertNotEqual(base, different_provider)

    def test_history_flag_without_metric_median_fails_closed(self) -> None:
        unified = _historical_unified()
        assert unified.company_intelligence is not None
        unified.company_intelligence["valuation_metrics"] = [
            {
                "code": "price_to_sales",
                "label": "P/S",
                "current_value": 6.25,
                "historical_median": None,
                "premium_to_median_pct": None,
                "position": "INSUFFICIENT_DATA",
            }
        ]
        semantics = derive_valuation_semantics(unified)
        self.assertFalse(semantics.historical_median_available)
        self.assertTrue(semantics.relative_valuation_context_limited)
        framing = authoritative_valuation_summary(semantics)
        assert framing is not None
        self.assertIn("tarihsel medyan", framing.lower())
        self.assertIn("mevcut değil", framing.lower())

    def test_snapshot_history_flag_without_metric_median_fails_closed(self) -> None:
        semantics = valuation_semantics_from_snapshot(
            {
                "current_valuation_metrics_available": True,
                "historical_valuation_median_available": True,
                "peer_valuation_comparison_available": False,
                "relative_valuation_context_limited": True,
                "thesis_valuation_context_code": "VALUATION_UNAVAILABLE",
                "available_valuation_metrics": [
                    {
                        "code": "price_to_sales",
                        "label": "P/S",
                        "current_value": 6.25,
                    }
                ],
            }
        )
        assert semantics is not None
        self.assertFalse(semantics.historical_median_available)

    def test_peer_only_context_is_not_described_as_peer_missing(self) -> None:
        semantics = ValuationSemantics(
            current_metrics_available=True,
            historical_median_available=False,
            peer_comparison_available=True,
            relative_valuation_context_limited=True,
            thesis_valuation_context_code="VALUATION_UNAVAILABLE",
            available_metrics=(
                {"code": "price_to_sales", "label": "P/S", "current_value": 6.25},
            ),
        )
        summary = authoritative_valuation_summary(semantics)
        assert summary is not None
        self.assertIn("benzer şirket değerleme karşılaştırması mevcut", summary.lower())
        self.assertIn("tarihsel medyan mevcut değil", summary)
        self.assertNotIn("Benzer şirket karşılaştırması mevcut değil", summary)

    def test_full_historical_and_peer_context_does_not_force_deterministic_override(self) -> None:
        semantics = ValuationSemantics(
            current_metrics_available=True,
            historical_median_available=True,
            peer_comparison_available=True,
            relative_valuation_context_limited=False,
            thesis_valuation_context_code="VALUATION_NEUTRAL",
            available_metrics=(
                {
                    "code": "price_to_sales",
                    "label": "P/S",
                    "current_value": 6.25,
                    "historical_median": 5.0,
                    "premium_to_median_pct": 25.0,
                    "position": "ABOVE_HISTORICAL_RANGE",
                },
            ),
        )
        self.assertIsNone(authoritative_valuation_summary(semantics))

    def test_prompt_allows_relative_history_but_never_absolute_attractiveness(self) -> None:
        payload = build_ai_summary_payload(
            _historical_unified(),
            evidence_level="LIMITED",
            financial_trends_source="sec_annual",
        )
        constraints = payload["authoritative_constraints"]
        self.assertFalse(constraints["valuation_attractiveness_claims_allowed"])
        self.assertTrue(constraints["historical_relative_valuation_claims_allowed"])
        self.assertFalse(constraints["peer_relative_valuation_claims_allowed"])

    def test_historical_relative_statement_is_allowed(self) -> None:
        constraints = AIResearchSummaryConstraints(
            symbol="CRM",
            participation_status="Uygun",
            thesis_status="MIXED",
            thesis_confidence="MEDIUM",
            evidence_level="LIMITED",
            earnings_available=False,
            news_available=False,
            peers_available=False,
            historical_valuation_available=True,
            allowed_symbols=("CRM",),
        )
        parsed = parse_ai_summary_response(
            _summary_json("P/S tarihsel medyanın %25 üzerinde.")
        )
        result = validate_ai_research_summary(parsed, constraints)
        self.assertTrue(result.valid, result.reasons)

    def test_absolute_cheap_expensive_language_stays_blocked_with_history(self) -> None:
        constraints = AIResearchSummaryConstraints(
            symbol="CRM",
            participation_status="Uygun",
            thesis_status="MIXED",
            thesis_confidence="MEDIUM",
            evidence_level="LIMITED",
            earnings_available=False,
            news_available=False,
            peers_available=False,
            historical_valuation_available=True,
            allowed_symbols=("CRM",),
        )
        for text in ("Hisse pahalı görünüyor.", "Hisse ucuz görünüyor."):
            parsed = parse_ai_summary_response(_summary_json(text))
            result = validate_ai_research_summary(parsed, constraints)
            self.assertFalse(result.valid, text)
            self.assertIn("unsupported_valuation_attractiveness", result.reasons)

    def test_limited_evidence_disclaimer_cannot_bypass_absolute_guard(self) -> None:
        constraints = AIResearchSummaryConstraints(
            symbol="CRM",
            participation_status="Uygun",
            thesis_status="MIXED",
            thesis_confidence="MEDIUM",
            evidence_level="LIMITED",
            earnings_available=False,
            news_available=False,
            peers_available=True,
            historical_valuation_available=True,
            allowed_symbols=("CRM",),
        )
        parsed = parse_ai_summary_response(
            _summary_json("Hisse pahalı görünüyor; ancak kanıt sınırlı.")
        )
        result = validate_ai_research_summary(parsed, constraints)
        self.assertFalse(result.valid)
        self.assertIn("unsupported_valuation_attractiveness", result.reasons)

    def test_explicit_denial_of_absolute_claim_is_allowed(self) -> None:
        constraints = AIResearchSummaryConstraints(
            symbol="CRM",
            participation_status="Uygun",
            thesis_status="MIXED",
            thesis_confidence="MEDIUM",
            evidence_level="LIMITED",
            earnings_available=False,
            news_available=False,
            peers_available=True,
            historical_valuation_available=True,
            allowed_symbols=("CRM",),
        )
        parsed = parse_ai_summary_response(
            _summary_json("Bu verilerle hissenin pahalı olduğu söylenemez.")
        )
        result = validate_ai_research_summary(parsed, constraints)
        self.assertTrue(result.valid, result.reasons)


    def test_build_constraints_fail_closed_on_broad_flags_without_usable_evidence(self) -> None:
        unified = _historical_unified()
        assert unified.company_intelligence is not None
        unified.company_intelligence["valuation_metrics"] = [
            {
                "code": "price_to_sales",
                "label": "P/S",
                "current_value": 6.25,
                "historical_median": None,
                "premium_to_median_pct": None,
                "position": "INSUFFICIENT_DATA",
            }
        ]
        unified.company_intelligence["peer_comparisons"] = []
        unified.company_intelligence["data_quality"]["historical_valuation_available"] = True
        unified.company_intelligence["data_quality"]["peer_data_available"] = True
        unified.data_quality["historical_valuation_available"] = True
        unified.data_quality["peer_data_available"] = True

        constraints = build_summary_constraints(unified, evidence_level="LIMITED")
        self.assertFalse(constraints.historical_valuation_available)
        self.assertFalse(constraints.peers_available)

    def test_historical_relative_statement_is_rejected_without_history(self) -> None:
        constraints = AIResearchSummaryConstraints(
            symbol="CRM",
            participation_status="Uygun",
            thesis_status="MIXED",
            thesis_confidence="MEDIUM",
            evidence_level="LIMITED",
            earnings_available=False,
            news_available=False,
            peers_available=False,
            historical_valuation_available=False,
            allowed_symbols=("CRM",),
        )
        parsed = parse_ai_summary_response(
            _summary_json("P/S tarihsel medyanın %25 üzerinde.")
        )
        result = validate_ai_research_summary(parsed, constraints)
        self.assertFalse(result.valid)
        self.assertIn("unsupported_historical_valuation_comparison", result.reasons)

    def test_peer_relative_statement_is_allowed_with_peer_context(self) -> None:
        constraints = AIResearchSummaryConstraints(
            symbol="CRM",
            participation_status="Uygun",
            thesis_status="MIXED",
            thesis_confidence="MEDIUM",
            evidence_level="LIMITED",
            earnings_available=False,
            news_available=False,
            peers_available=True,
            historical_valuation_available=False,
            allowed_symbols=("CRM",),
        )
        parsed = parse_ai_summary_response(
            _summary_json("P/S benzer şirket medyanının altında.")
        )
        result = validate_ai_research_summary(parsed, constraints)
        self.assertTrue(result.valid, result.reasons)

    def test_peer_relative_statement_is_rejected_without_peer_context(self) -> None:
        constraints = AIResearchSummaryConstraints(
            symbol="CRM",
            participation_status="Uygun",
            thesis_status="MIXED",
            thesis_confidence="MEDIUM",
            evidence_level="LIMITED",
            earnings_available=False,
            news_available=False,
            peers_available=False,
            historical_valuation_available=True,
            allowed_symbols=("CRM",),
        )
        parsed = parse_ai_summary_response(
            _summary_json("P/S benzer şirket medyanının altında.")
        )
        result = validate_ai_research_summary(parsed, constraints)
        self.assertFalse(result.valid)
        self.assertIn("unsupported_peer_valuation_comparison", result.reasons)


if __name__ == "__main__":
    unittest.main()
