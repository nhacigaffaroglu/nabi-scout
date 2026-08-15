from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from services.ai_research_summary_contract import AIResearchSummaryView
from services.ai_research_summary_prompt import (
    build_ai_summary_payload,
    validate_ai_summary_payload_shape,
)
from services.ai_research_summary_service import (
    AIResearchSummaryService,
    compute_ci_semantic_fingerprint,
    compute_context_semantic_identity,
    compute_evidence_level,
)
from services.ai_research_summary_validator import (
    AIResearchSummaryConstraints,
    parse_ai_summary_response,
    validate_ai_research_summary,
)
from services.company_intelligence_contract import CompanyIntelligenceView
from services.company_intelligence_contract import (
    CompanyIntelligenceView,
    DataQualitySection,
    FinancialTrendsSection,
    IntelligenceProvenance,
    MetricTrendPoint,
    ValuationMetric,
    ValuationSection,
)
from services.investment_thesis_contract import InvestmentThesisView, THESIS_VERSION
from services.research_eligibility_contract import (
    RESEARCH_STATUS_FAIL,
    RESEARCH_STATUS_INSUFFICIENT_DATA,
    RESEARCH_STATUS_PASS,
    RESEARCH_STATUS_UNKNOWN,
    ResearchEligibilityResult,
)
from services.research_eligibility_service import research_eligibility_pass_fixture
from services.unified_research_contract import (
    ParticipationResearchContext,
    UnifiedResearchContext,
)
from services.wealth_adviser_config import AdviserLlmConfig
from tests.test_company_intelligence_valuation_fallback import (
    _crm_live_like_sec_financials,
    _jnj_live_like_sec_financials,
)


def _eligible_eligibility(symbol: str = "CRM") -> ResearchEligibilityResult:
    return research_eligibility_pass_fixture(symbol)


def _blocked_eligibility(symbol: str, *, status: str) -> ResearchEligibilityResult:
    mapping = {
        "FAIL": RESEARCH_STATUS_FAIL,
        "INSUFFICIENT_DATA": RESEARCH_STATUS_INSUFFICIENT_DATA,
        "UNKNOWN": RESEARCH_STATUS_UNKNOWN,
    }
    return ResearchEligibilityResult(
        symbol=symbol,
        status=mapping[status],
        research_allowed=False,
        participation_status="Uygun Değil" if status == "FAIL" else "Kontrol Et",
        reason_codes=("blocked",),
        limitations=("Blocked for test.",),
        provenance=(("gate", "participation_assessment"),),
    )


def _limited_unified(symbol: str = "CRM") -> UnifiedResearchContext:
    return UnifiedResearchContext(
        symbol=symbol,
        company_name=f"{symbol} Inc.",
        schema_version="unified-research-v1",
        generated_at=datetime.now(timezone.utc).isoformat(),
        company_intelligence={
            "symbol": symbol,
            "financial_observations": [
                {
                    "code": "REVENUE_GROWTH",
                    "statement": "Gelir yıllık bazda artıyor.",
                    "direction": "IMPROVING",
                }
            ],
            "valuation_metrics": [
                {
                    "code": "price_to_sales",
                    "label": "P/S",
                    "current_value": 3.87,
                    "position": "INSUFFICIENT_DATA",
                },
                {
                    "code": "price_to_fcf",
                    "label": "P/FCF",
                    "current_value": 11.16,
                    "position": "INSUFFICIENT_DATA",
                },
                {
                    "code": "ev_ebit",
                    "label": "EV/EBIT",
                    "current_value": 20.14,
                    "position": "INSUFFICIENT_DATA",
                },
            ],
            "material_news": [],
            "peer_observations": [],
            "data_quality": {
                "financial_history_available": True,
                "quarterly_comparison_available": False,
                "earnings_expectations_available": False,
                "valuation_available": True,
                "historical_valuation_available": False,
                "peer_data_available": False,
                "news_available": False,
                "catalyst_data_available": False,
            },
        },
        investment_thesis={
            "symbol": symbol,
            "thesis_status": "INSUFFICIENT_DATA",
            "confidence": "LOW",
            "valuation_context": "VALUATION_UNAVAILABLE",
            "earnings_context": "EARNINGS_UNAVAILABLE",
        },
        nabi_context=None,
        participation_context=ParticipationResearchContext(
            status="Uygun",
            confidence="MEDIUM",
            assessed_at="2026-08-15T00:00:00Z",
            limitations=(),
        ),
        wealth_exposure_context=None,
        portfolio_fit=(),
        investor_profile={},
        active_goals=(),
        monitoring_plan=(),
        thesis_change_summary=(),
        data_quality={
            "financial_history_available": True,
            "quarterly_comparison_available": False,
            "earnings_expectations_available": False,
            "historical_valuation_available": False,
            "peer_data_available": False,
            "news_available": False,
        },
        provenance=(),
        focus_symbol=symbol,
    )


def _ci_view(symbol: str = "CRM") -> CompanyIntelligenceView:
    return CompanyIntelligenceView(
        symbol=symbol,
        company_name=f"{symbol} Inc.",
        as_of="2026-08-15T00:00:00Z",
        business_snapshot=None,
        financial_trends=FinancialTrendsSection(
            trends=(
                MetricTrendPoint(
                    metric="revenue",
                    latest_value=41_525_000_000.0,
                    previous_value=37_895_000_000.0,
                    absolute_change=3_630_000_000.0,
                    pct_change=9.58,
                    direction="IMPROVING",
                    period="2026-01-31",
                ),
            ),
            observations=(),
            provenance=IntelligenceProvenance(
                provider="sec",
                data_family="financial_statements_annual",
                retrieved_at="2026-08-15T00:00:00Z",
                source_period="2026-01-31",
            ),
        ),
        earnings=None,
        valuation=ValuationSection(
            metrics=(
                ValuationMetric(
                    code="price_to_sales",
                    label="P/S",
                    current_value=3.87,
                    historical_median=None,
                    premium_to_median_pct=None,
                    position="INSUFFICIENT_DATA",
                ),
                ValuationMetric(
                    code="price_to_fcf",
                    label="P/FCF",
                    current_value=11.16,
                    historical_median=None,
                    premium_to_median_pct=None,
                    position="INSUFFICIENT_DATA",
                ),
                ValuationMetric(
                    code="ev_ebit",
                    label="EV/EBIT",
                    current_value=20.14,
                    historical_median=None,
                    premium_to_median_pct=None,
                    position="INSUFFICIENT_DATA",
                ),
            ),
            observations=(),
            provenance=IntelligenceProvenance(
                provider="sec+fmp",
                data_family="sec_annual_market_hybrid",
                retrieved_at="2026-08-15T00:00:00Z",
            ),
        ),
        peers=None,
        news=None,
        catalysts=(),
        factual_risks=(),
        data_quality=DataQualitySection(
            company_profile_available=True,
            financial_history_available=True,
            quarterly_comparison_available=False,
            earnings_expectations_available=False,
            valuation_available=True,
            historical_valuation_available=False,
            peer_data_available=False,
            news_available=False,
            catalyst_data_available=False,
            warnings=("SEC yıllık fallback kullanıldı.",),
            provider_failures=(),
            provider_diagnostic_details=(),
            partial_sections=("earnings", "news", "peers"),
            as_of="2026-08-15T00:00:00Z",
        ),
    )


def _thesis_view(symbol: str = "CRM") -> InvestmentThesisView:
    return InvestmentThesisView(
        symbol=symbol,
        company_name=f"{symbol} Inc.",
        as_of="2026-08-15T00:00:00Z",
        thesis_version=THESIS_VERSION,
        thesis_status="INSUFFICIENT_DATA",
        confidence="LOW",
        thesis_summary="Veri kapsamı sınırlı.",
        key_question="Kapsam genişletilebilir mi?",
        valuation_context="VALUATION_UNAVAILABLE",
        earnings_context="EARNINGS_UNAVAILABLE",
        peer_context="PEERS_UNAVAILABLE",
        news_context="NEWS_UNAVAILABLE",
        participation_context="PARTICIPATION_COMPLIANT",
        nabi_context=None,
        supporting_evidence=(),
        weakening_evidence=(),
        risks=(),
        catalysts=(),
        invalidation_conditions=(),
        assumptions=(),
        expectation_tensions=(),
        change_summary=(),
        monitoring_plan=(),
        decision_intelligence=None,
        evidence_coverage=None,
    )


def _valid_summary_json(*, evidence_level: str = "LIMITED") -> str:
    return json.dumps(
        {
            "financial_outlook": "Son yıllık finansallara göre gelir artışı görülüyor.",
            "valuation_summary": (
                "P/S, P/FCF ve EV/EBIT hesaplanabiliyor; tarihsel karşılaştırma kanıtı yok."
            ),
            "key_strengths": ["Gelir ve faaliyet kârı yıllık bazda iyileşiyor."],
            "key_weaknesses": ["Veri kapsamı sınırlı."],
            "risks_to_watch": ["Eksik earnings ve haber kanıtı."],
            "missing_evidence": [
                "Güncel earnings sürprizleri doğrulanamadı.",
                "Haber verisi mevcut değil.",
            ],
            "monitoring_points": ["SEC yıllık finansal trendleri izlenmeli."],
            "limitations": ["Bu özet yatırım talimatı değildir."],
            "evidence_level": evidence_level,
        },
        ensure_ascii=False,
    )


def _enabled_config() -> AdviserLlmConfig:
    return AdviserLlmConfig(
        enabled=True,
        provider="openai",
        model="gpt-test",
        timeout_seconds=10,
        max_output_tokens=800,
        temperature=0.2,
        api_key="test-key",
    )


class AIResearchSummaryContractTests(unittest.TestCase):
    def test_json_safe_contract(self) -> None:
        view = AIResearchSummaryView(
            symbol="CRM",
            status="AVAILABLE",
            evidence_level="LIMITED",
            financial_outlook="Test",
            generated_at="2026-08-15T00:00:00Z",
        )
        serialized = json.dumps(view.to_dict())
        self.assertNotIn("api_key", serialized.lower())
        self.assertIn("LIMITED", serialized)


class AIResearchSummaryPromptTests(unittest.TestCase):
    def test_payload_is_json_safe_without_secrets(self) -> None:
        unified = _limited_unified("CRM")
        payload = build_ai_summary_payload(
            unified,
            evidence_level="LIMITED",
            financial_trends_source="sec_annual",
        )
        self.assertTrue(validate_ai_summary_payload_shape(payload))
        serialized = json.dumps(payload).lower()
        self.assertNotIn("api_key", serialized)
        self.assertNotIn("authorization", serialized)
        self.assertNotIn("raw", serialized)
        constraints = payload["authoritative_constraints"]
        self.assertFalse(constraints["valuation_attractiveness_claims_allowed"])
        self.assertNotIn("forbidden_when_historical_valuation_missing", constraints)

    def test_hybrid_valuation_semantics_propagate_in_payload(self) -> None:
        unified = _limited_unified("CRM")
        payload = build_ai_summary_payload(
            unified,
            evidence_level="LIMITED",
            financial_trends_source="sec_annual",
        )
        semantics = payload["authoritative_constraints"]["valuation_semantics"]
        self.assertTrue(semantics["current_valuation_metrics_available"])
        self.assertFalse(semantics["historical_valuation_median_available"])
        self.assertTrue(semantics["relative_valuation_context_limited"])
        self.assertTrue(semantics["thesis_valuation_context_does_not_mean_metrics_missing"])
        self.assertEqual(semantics["thesis_valuation_context_code"], "VALUATION_UNAVAILABLE")
        self.assertIn("P/S", semantics["recommended_valuation_summary_framing"])
        self.assertNotIn("değerleme verisi yok", semantics["recommended_valuation_summary_framing"].lower())
        self.assertTrue(payload["authoritative_constraints"]["coverage"]["valuation_available"])

    def test_no_metrics_semantics_remain_unavailable(self) -> None:
        unified = UnifiedResearchContext(
            symbol="CRM",
            company_name="CRM Inc.",
            schema_version="unified-research-v1",
            generated_at=datetime.now(timezone.utc).isoformat(),
            company_intelligence={
                "symbol": "CRM",
                "valuation_metrics": [],
                "data_quality": {
                    "valuation_available": False,
                    "historical_valuation_available": False,
                },
            },
            investment_thesis={
                "symbol": "CRM",
                "valuation_context": "VALUATION_UNAVAILABLE",
            },
            nabi_context=None,
            participation_context=ParticipationResearchContext(
                status="Uygun",
                confidence="MEDIUM",
                assessed_at="2026-08-15T00:00:00Z",
                limitations=(),
            ),
            wealth_exposure_context=None,
            data_quality={
                "valuation_available": False,
                "historical_valuation_available": False,
            },
            provenance=(),
            focus_symbol="CRM",
        )
        payload = build_ai_summary_payload(
            unified,
            evidence_level="LIMITED",
            financial_trends_source=None,
        )
        semantics = payload["authoritative_constraints"]["valuation_semantics"]
        self.assertFalse(semantics["current_valuation_metrics_available"])
        self.assertFalse(semantics["thesis_valuation_context_does_not_mean_metrics_missing"])
        self.assertIn("hesaplanamıyor", semantics["recommended_valuation_summary_framing"].lower())

    def test_jnj_generic_hybrid_valuation_semantics(self) -> None:
        unified = _limited_unified("JNJ")
        payload = build_ai_summary_payload(
            unified,
            evidence_level="LIMITED",
            financial_trends_source="sec_annual",
        )
        semantics = payload["authoritative_constraints"]["valuation_semantics"]
        self.assertTrue(semantics["current_valuation_metrics_available"])
        self.assertTrue(semantics["thesis_valuation_context_does_not_mean_metrics_missing"])

    def test_unified_research_service_path_preserves_hybrid_metrics(self) -> None:
        from services.unified_research_service import UnifiedResearchService

        service = UnifiedResearchService()
        unified = service.build_context(
            symbol="CRM",
            research_eligibility=_eligible_eligibility("CRM"),
            company_intelligence_view=_ci_view("CRM"),
            investment_thesis_view=_thesis_view("CRM"),
        )
        payload = build_ai_summary_payload(
            unified,
            evidence_level="LIMITED",
            financial_trends_source="sec_annual",
        )
        semantics = payload["authoritative_constraints"]["valuation_semantics"]
        metrics = semantics["available_valuation_metrics"]
        self.assertTrue(semantics["current_valuation_metrics_available"])
        self.assertTrue(any(item["label"] == "P/S" for item in metrics))
        self.assertTrue(semantics["thesis_valuation_context_does_not_mean_metrics_missing"])


class AIResearchSummaryValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.constraints = AIResearchSummaryConstraints(
            symbol="CRM",
            participation_status="Uygun",
            thesis_status="INSUFFICIENT_DATA",
            thesis_confidence="LOW",
            evidence_level="LIMITED",
            earnings_available=False,
            news_available=False,
            peers_available=False,
            historical_valuation_available=False,
            allowed_symbols=("CRM",),
        )

    def test_exact_trade_output_rejected(self) -> None:
        parsed = parse_ai_summary_response(
            _valid_summary_json().replace(
                "Bu özet yatırım talimatı değildir.",
                "Bugün CRM al.",
            )
        )
        result = validate_ai_research_summary(parsed, self.constraints)
        self.assertFalse(result.valid)
        self.assertIn("explicit_transaction_command", result.reasons)

    def test_position_size_output_rejected(self) -> None:
        parsed = parse_ai_summary_response(
            _valid_summary_json().replace(
                "Bu özet yatırım talimatı değildir.",
                "CRM hisselerinin %50'sini sat.",
            )
        )
        result = validate_ai_research_summary(parsed, self.constraints)
        self.assertFalse(result.valid)

    def test_hybrid_valuation_cannot_become_cheap(self) -> None:
        parsed = parse_ai_summary_response(
            _valid_summary_json().replace(
                "tarihsel karşılaştırma kanıtı yok.",
                "Hisse ucuz görünüyor.",
            )
        )
        result = validate_ai_research_summary(parsed, self.constraints)
        self.assertFalse(result.valid)
        self.assertIn("unsupported_valuation_attractiveness", result.reasons)

    def test_safe_valuation_disclaimer_passes_without_attractiveness_claim(self) -> None:
        parsed = parse_ai_summary_response(
            _valid_summary_json().replace(
                "tarihsel karşılaştırma kanıtı yok.",
                (
                    "Değerleme oranları hesaplanabiliyor ancak tarihsel ve benzer şirket "
                    "karşılaştırması olmadığı için göreceli çekicilik konusunda kanıt sınırlı."
                ),
            )
        )
        result = validate_ai_research_summary(parsed, self.constraints)
        self.assertTrue(result.valid)

    def test_confidence_vocabulary_not_flagged_as_ticker(self) -> None:
        parsed = parse_ai_summary_response(
            _valid_summary_json().replace(
                "Veri kapsamı sınırlı.",
                "Tez güveni LOW düzeyinde kalıyor.",
            )
        )
        result = validate_ai_research_summary(parsed, self.constraints)
        self.assertNotIn("unsupported_symbol:LOW", result.reasons)

    def test_thesis_low_cannot_become_high_confidence(self) -> None:
        parsed = parse_ai_summary_response(
            _valid_summary_json().replace(
                "Veri kapsamı sınırlı.",
                "Güçlü yatırım tezi oluşuyor.",
            )
        )
        result = validate_ai_research_summary(parsed, self.constraints)
        self.assertFalse(result.valid)
        self.assertIn("thesis_confidence_inflation", result.reasons)

    def test_metric_strength_language_passes_with_low_thesis(self) -> None:
        for phrase in (
            "Gelir büyümesi güçlü.",
            "Güçlü yönler arasında yıllık gelir artışı var.",
            "Faaliyet nakit akışı güçlü seyrediyor.",
            "Mevcut veriler güçlü yatırım tezi oluşturmaya yetmiyor.",
            "Güçlü yatırım tezi oluşturmak için kanıt yetersiz.",
            "Güçlü yatırım tezi için kanıt yetersiz.",
            "Bu değerlendirmeye yüksek güven duyulamaz.",
            "SEC yıllık veride gelirde yıllık bazda anlamlı değişim tespit edildi (destekleyen veri, yüksek güven).",
            "Yıllık gelir trendi için veri güveni yüksek.",
            "Bu tek sinyal yüksek güvenle ölçülüyor.",
        ):
            parsed = parse_ai_summary_response(
                _valid_summary_json().replace(
                    "Veri kapsamı sınırlı.",
                    phrase,
                )
            )
            result = validate_ai_research_summary(parsed, self.constraints)
            self.assertNotIn(
                "thesis_confidence_inflation",
                result.reasons,
                msg=phrase,
            )

    def test_thesis_confidence_inflation_cases_fail(self) -> None:
        cases = (
            "Yatırım tezi güçlü.",
            "Tez güveni yüksek.",
            "Bu değerlendirmeye yüksek güven duyulabilir.",
            "Kanıt düzeyi güçlü.",
            "Tez yüksek güvenle destekleniyor.",
            "Overall thesis confidence is HIGH.",
            "Bu araştırmaya yüksek güven duyulabilir.",
        )
        for phrase in cases:
            parsed = parse_ai_summary_response(
                _valid_summary_json().replace(
                    "Veri kapsamı sınırlı.",
                    phrase,
                )
            )
            result = validate_ai_research_summary(parsed, self.constraints)
            self.assertIn("thesis_confidence_inflation", result.reasons, msg=phrase)

    def test_live_captured_metric_confidence_phrase_passes(self) -> None:
        from services.ai_research_summary_validator import (
            explain_thesis_confidence_inflation_for_summary,
        )

        live_phrase = (
            "SEC yıllık veride gelirde yıllık bazda anlamlı değişim tespit edildi "
            "(destekleyen veri, yüksek güven)."
        )
        parsed = parse_ai_summary_response(
            _valid_summary_json().replace(
                "Gelir ve faaliyet kârı yıllık bazda iyileşiyor.",
                live_phrase,
            )
        )
        self.assertEqual(explain_thesis_confidence_inflation_for_summary(parsed), ())
        result = validate_ai_research_summary(parsed, self.constraints)
        self.assertNotIn("thesis_confidence_inflation", result.reasons)

    def test_thesis_confidence_inflation_is_field_aware(self) -> None:
        parsed = parse_ai_summary_response(
            json.dumps(
                {
                    "financial_outlook": "Gelir trendi yıllık bazda iyileşiyor.",
                    "valuation_summary": "Oranlar mevcut.",
                    "key_strengths": [
                        "Yıllık gelir trendi için veri güveni yüksek.",
                    ],
                    "key_weaknesses": ["Tez güveni yüksek."],
                    "risks_to_watch": [],
                    "missing_evidence": [],
                    "monitoring_points": [],
                    "limitations": [],
                    "evidence_level": "LIMITED",
                },
                ensure_ascii=False,
            )
        )
        result = validate_ai_research_summary(parsed, self.constraints)
        self.assertIn("thesis_confidence_inflation", result.reasons)

    def test_api_acronym_passes_without_context(self) -> None:
        for phrase in (
            "API erişim sınırı var.",
            "SEC API verisi sınırlı.",
            "FMP API erişimi kısıtlı.",
            "Bazı veri sağlayıcı API erişim sınırları nedeniyle haber akışı eksik.",
        ):
            parsed = parse_ai_summary_response(
                _valid_summary_json().replace(
                    "Veri kapsamı sınırlı.",
                    phrase,
                )
            )
            result = validate_ai_research_summary(parsed, self.constraints)
            self.assertNotIn("unsupported_symbol:API", result.reasons, msg=phrase)
            self.assertTrue(result.valid, msg=phrase)

    def test_unsupported_tickers_still_fail_when_api_also_present(self) -> None:
        parsed = parse_ai_summary_response(
            _valid_summary_json().replace(
                "Veri kapsamı sınırlı.",
                "API sınırlı ama MSFT daha iyi.",
            )
        )
        result = validate_ai_research_summary(parsed, self.constraints)
        self.assertIn("unsupported_symbol:MSFT", result.reasons)

    def test_unsupported_ticker_examples_still_fail(self) -> None:
        for phrase in (
            "CRM yerine MSFT daha iyi.",
            "AAPL alınabilir.",
            "NVDA yerine CRM.",
            "GOOGL daha cazip.",
            "META daha güçlü görünüyor.",
            "JNJ ile kıyaslandığında CRM sınırlı.",
        ):
            parsed = parse_ai_summary_response(
                _valid_summary_json().replace(
                    "Veri kapsamı sınırlı.",
                    phrase,
                )
            )
            result = validate_ai_research_summary(parsed, self.constraints)
            self.assertFalse(result.valid, msg=phrase)
            self.assertTrue(
                any(reason.startswith("unsupported_symbol:") for reason in result.reasons),
                msg=phrase,
            )

    def test_missing_news_not_inferred_as_clean(self) -> None:
        parsed = parse_ai_summary_response(
            _valid_summary_json().replace(
                "Haber verisi mevcut değil.",
                "Olumsuz haber bulunmuyor.",
            )
        )
        result = validate_ai_research_summary(parsed, self.constraints)
        self.assertFalse(result.valid)
        self.assertIn("news_absence_inference", result.reasons)

    def test_unsupported_ticker_rejected(self) -> None:
        parsed = parse_ai_summary_response(
            _valid_summary_json().replace(
                "Gelir ve faaliyet kârı yıllık bazda iyileşiyor.",
                "MSFT'e kıyasla CRM daha güçlü.",
            )
        )
        result = validate_ai_research_summary(parsed, self.constraints)
        self.assertFalse(result.valid)
        self.assertIn("unsupported_symbol:MSFT", result.reasons)

    def test_sec_and_sic_acronyms_pass(self) -> None:
        parsed = parse_ai_summary_response(
            _valid_summary_json().replace(
                "Son yıllık finansallara göre gelir artışı görülüyor.",
                "SEC ve SIC sınıflandırması katılım bağlamında referans alınabilir.",
            )
        )
        result = validate_ai_research_summary(parsed, self.constraints)
        self.assertNotIn("unsupported_symbol:SIC", result.reasons)
        self.assertNotIn("unsupported_symbol:SEC", result.reasons)
        self.assertTrue(result.valid)

    def test_financial_metric_acronyms_pass(self) -> None:
        parsed = parse_ai_summary_response(
            _valid_summary_json().replace(
                "P/S, P/FCF ve EV/EBIT hesaplanabiliyor; tarihsel karşılaştırma kanıtı yok.",
                "EPS, FCF, EV/EBIT ve TTM verileri mevcut; göreceli çekicilik kanıtı sınırlı.",
            )
        )
        result = validate_ai_research_summary(parsed, self.constraints)
        self.assertTrue(result.valid)
        for token in ("EPS", "FCF", "EBIT", "TTM", "EV"):
            self.assertNotIn(f"unsupported_symbol:{token}", result.reasons)

    def test_allowed_symbol_with_sic_reference_passes(self) -> None:
        parsed = parse_ai_summary_response(
            _valid_summary_json().replace(
                "Son yıllık finansallara göre gelir artışı görülüyor.",
                "CRM'nin SIC kodu katılım değerlendirmesinde dikkate alınmıştır.",
            )
        )
        result = validate_ai_research_summary(parsed, self.constraints)
        self.assertTrue(result.valid)
        self.assertNotIn("unsupported_symbol:SIC", result.reasons)

    def test_mixed_acronyms_and_unsupported_ticker_still_fail(self) -> None:
        parsed = parse_ai_summary_response(
            _valid_summary_json().replace(
                "Son yıllık finansallara göre gelir artışı görülüyor.",
                "SEC ve SIC bağlamında CRM yerine MSFT daha iyi görünüyor.",
            )
        )
        result = validate_ai_research_summary(parsed, self.constraints)
        self.assertFalse(result.valid)
        self.assertIn("unsupported_symbol:MSFT", result.reasons)

    def test_aapl_trade_command_still_fails(self) -> None:
        parsed = parse_ai_summary_response(
            _valid_summary_json().replace(
                "Bu özet yatırım talimatı değildir.",
                "AAPL al.",
            )
        )
        result = validate_ai_research_summary(parsed, self.constraints)
        self.assertFalse(result.valid)
        self.assertTrue(
            "explicit_transaction_command" in result.reasons
            or "unsupported_symbol:AAPL" in result.reasons
        )

    def test_domain_acronyms_sec_sic_ttm_pass(self) -> None:
        for phrase in (
            "SEC ve SIC sınıflandırması referans alınabilir.",
            "EPS, FCF, EV/EBIT ve TTM verileri mevcut.",
        ):
            parsed = parse_ai_summary_response(
                _valid_summary_json().replace(
                    "Son yıllık finansallara göre gelir artışı görülüyor.",
                    phrase,
                )
            )
            result = validate_ai_research_summary(parsed, self.constraints)
            self.assertNotIn("unsupported_symbol:SEC", result.reasons, msg=phrase)
            self.assertNotIn("unsupported_symbol:SIC", result.reasons, msg=phrase)
            self.assertNotIn("unsupported_symbol:TTM", result.reasons, msg=phrase)

    def test_invented_ttvm_rejected_when_absent_from_context(self) -> None:
        parsed = parse_ai_summary_response(
            _valid_summary_json().replace(
                "P/S, P/FCF ve EV/EBIT hesaplanabiliyor; tarihsel karşılaştırma kanıtı yok.",
                "EPS, FCF ve TTVM verileri mevcut; göreceli çekicilik kanıtı sınırlı.",
            )
        )
        result = validate_ai_research_summary(parsed, self.constraints)
        self.assertIn("unsupported_symbol:TTVM", result.reasons)

    def test_context_uppercase_token_passes_when_present_in_authoritative_context(self) -> None:
        from services.ai_research_summary_validator import extract_context_uppercase_tokens

        unified = _limited_unified("CRM")
        context_blob = dict(unified.company_intelligence or {})
        context_blob["data_quality"] = {
            **(context_blob.get("data_quality") or {}),
            "warnings": ("XBRL kaynaklı veri kullanıldı.",),
        }
        context_tokens = extract_context_uppercase_tokens({"company_intelligence": context_blob})
        self.assertIn("XBRL", context_tokens)
        constraints = AIResearchSummaryConstraints(
            symbol="CRM",
            participation_status="Uygun",
            thesis_status="INSUFFICIENT_DATA",
            thesis_confidence="LOW",
            evidence_level="LIMITED",
            earnings_available=False,
            news_available=False,
            peers_available=False,
            historical_valuation_available=False,
            allowed_symbols=("CRM",),
            context_uppercase_tokens=context_tokens,
        )
        parsed = parse_ai_summary_response(
            _valid_summary_json().replace(
                "Son yıllık finansallara göre gelir artışı görülüyor.",
                "XBRL tabanlı finansal kaynaklar kullanıldı.",
            )
        )
        result = validate_ai_research_summary(parsed, constraints)
        self.assertNotIn("unsupported_symbol:XBRL", result.reasons)

    def test_invented_tickers_msft_aapl_fail(self) -> None:
        for ticker, phrase in (
            ("MSFT", "MSFT'e kıyasla CRM daha güçlü."),
            ("AAPL", "AAPL benzeri büyüme profili anlatılamaz."),
        ):
            parsed = parse_ai_summary_response(
                _valid_summary_json().replace(
                    "Gelir ve faaliyet kârı yıllık bazda iyileşiyor.",
                    phrase,
                )
            )
            result = validate_ai_research_summary(parsed, self.constraints)
            self.assertIn(f"unsupported_symbol:{ticker}", result.reasons, msg=phrase)


class AIResearchSummaryServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = _enabled_config()
        self.client = MagicMock()
        self.client.complete.return_value = _valid_summary_json()
        self.unified_service = MagicMock()
        self.unified_service.build_context.return_value = _limited_unified("CRM")
        self.service = AIResearchSummaryService(
            config=self.config,
            client=self.client,
            unified_research_service=self.unified_service,
        )
        self.participation_view = None

    def test_eligible_context_can_build_summary(self) -> None:
        view = self.service.generate(
            symbol="CRM",
            research_eligibility=_eligible_eligibility("CRM"),
            company_intelligence_view=_ci_view("CRM"),
            investment_thesis_view=_thesis_view("CRM"),
        )
        self.assertEqual(view.status, "AVAILABLE")
        self.assertEqual(view.evidence_level, "LIMITED")
        self.client.complete.assert_called_once()

    def test_blocked_participation_zero_llm_call(self) -> None:
        view = self.service.generate(
            symbol="AAPL",
            research_eligibility=_blocked_eligibility("AAPL", status="FAIL"),
            company_intelligence_view=_ci_view("AAPL"),
            investment_thesis_view=_thesis_view("AAPL"),
        )
        self.assertEqual(view.status, "UNAVAILABLE")
        self.client.complete.assert_not_called()

    def test_broad_segment_kontrol_et_zero_llm_call(self) -> None:
        view = self.service.generate(
            symbol="MSFT",
            research_eligibility=_blocked_eligibility("MSFT", status="UNKNOWN"),
            company_intelligence_view=_ci_view("MSFT"),
            investment_thesis_view=_thesis_view("MSFT"),
        )
        self.assertEqual(view.status, "UNAVAILABLE")
        self.client.complete.assert_not_called()

    def test_disabled_llm_returns_unavailable(self) -> None:
        disabled = AdviserLlmConfig(
            enabled=False,
            provider="openai",
            model="gpt-test",
            timeout_seconds=10,
            max_output_tokens=800,
            temperature=0.2,
            api_key=None,
        )
        service = AIResearchSummaryService(
            config=disabled,
            client=self.client,
            unified_research_service=self.unified_service,
        )
        view = service.generate(
            symbol="CRM",
            research_eligibility=_eligible_eligibility("CRM"),
            company_intelligence_view=_ci_view("CRM"),
            investment_thesis_view=_thesis_view("CRM"),
        )
        self.assertEqual(view.status, "UNAVAILABLE")
        self.client.complete.assert_not_called()

    def test_cache_hit_avoids_second_llm_call(self) -> None:
        first = self.service.generate(
            symbol="CRM",
            research_eligibility=_eligible_eligibility("CRM"),
            company_intelligence_view=_ci_view("CRM"),
            investment_thesis_view=_thesis_view("CRM"),
            force_refresh=True,
        )
        identity = first.metadata.context_semantic_identity if first.metadata else ""
        self.service.generate(
            symbol="CRM",
            research_eligibility=_eligible_eligibility("CRM"),
            company_intelligence_view=_ci_view("CRM"),
            investment_thesis_view=_thesis_view("CRM"),
            cached_view=first,
            cached_identity=identity,
        )
        self.assertEqual(self.client.complete.call_count, 1)

    def test_changed_context_identity_differs(self) -> None:
        first_identity = compute_context_semantic_identity(
            symbol="CRM",
            participation_result=None,
            company_intelligence_view=_ci_view("CRM"),
            investment_thesis_view=_thesis_view("CRM"),
        )
        changed_thesis = InvestmentThesisView(
            symbol="CRM",
            company_name="CRM Inc.",
            as_of="2026-08-15T00:00:00Z",
            thesis_version=THESIS_VERSION,
            thesis_status="INSUFFICIENT_DATA",
            confidence="MEDIUM",
            thesis_summary="Veri kapsamı sınırlı.",
            key_question="Kapsam genişletilebilir mi?",
            valuation_context="VALUATION_UNAVAILABLE",
            earnings_context="EARNINGS_UNAVAILABLE",
            peer_context="PEERS_UNAVAILABLE",
            news_context="NEWS_UNAVAILABLE",
            participation_context="PARTICIPATION_COMPLIANT",
            nabi_context=None,
            supporting_evidence=(),
            weakening_evidence=(),
            risks=(),
            catalysts=(),
            invalidation_conditions=(),
            assumptions=(),
        )
        second_identity = compute_context_semantic_identity(
            symbol="CRM",
            participation_result=None,
            company_intelligence_view=_ci_view("CRM"),
            investment_thesis_view=changed_thesis,
        )
        self.assertNotEqual(first_identity, second_identity)

    def test_jnj_generic_path(self) -> None:
        self.unified_service.build_context.return_value = _limited_unified("JNJ")
        self.client.complete.return_value = _valid_summary_json().replace("CRM", "JNJ")
        view = self.service.generate(
            symbol="JNJ",
            research_eligibility=_eligible_eligibility("JNJ"),
            company_intelligence_view=_ci_view("JNJ"),
            investment_thesis_view=_thesis_view("JNJ"),
            force_refresh=True,
        )
        self.assertEqual(view.symbol, "JNJ")
        self.assertEqual(view.status, "AVAILABLE")
        self.client.complete.assert_called_once()

    def test_validation_failed_on_unsafe_output(self) -> None:
        self.client.complete.return_value = _valid_summary_json().replace(
            "Bu özet yatırım talimatı değildir.",
            "CRM'den 100 adet satın al.",
        )
        view = self.service.generate(
            symbol="CRM",
            research_eligibility=_eligible_eligibility("CRM"),
            company_intelligence_view=_ci_view("CRM"),
            investment_thesis_view=_thesis_view("CRM"),
            force_refresh=True,
        )
        self.assertEqual(view.status, "VALIDATION_FAILED")


class AIResearchSummaryEvidenceLevelTests(unittest.TestCase):
    def test_crm_like_context_is_limited(self) -> None:
        level = compute_evidence_level(
            _limited_unified("CRM"),
            investment_thesis_view=_thesis_view("CRM"),
        )
        self.assertEqual(level, "LIMITED")


class AIResearchSummaryCacheIdentityTests(unittest.TestCase):
    def test_ci_fingerprint_stable_when_as_of_changes(self) -> None:
        ci1 = _ci_view("CRM")
        ci2 = CompanyIntelligenceView(**{**ci1.__dict__, "as_of": "2026-08-15T02:00:00Z"})
        self.assertEqual(
            compute_ci_semantic_fingerprint(ci1),
            compute_ci_semantic_fingerprint(ci2),
        )
        id1 = compute_context_semantic_identity(
            symbol="CRM",
            participation_result=None,
            company_intelligence_view=ci1,
            investment_thesis_view=_thesis_view("CRM"),
        )
        id2 = compute_context_semantic_identity(
            symbol="CRM",
            participation_result=None,
            company_intelligence_view=ci2,
            investment_thesis_view=_thesis_view("CRM"),
        )
        self.assertEqual(id1, id2)

    def test_button_flow_store_and_render_cached_result(self) -> None:
        from components.ai_research_summary_ui import (
            ai_summary_cache_key,
            ai_summary_identity_key,
            store_ai_summary,
        )

        service = AIResearchSummaryService(
            config=_enabled_config(),
            client=MagicMock(complete=MagicMock(return_value=_valid_summary_json())),
            unified_research_service=MagicMock(
                build_context=MagicMock(return_value=_limited_unified("CRM"))
            ),
        )
        view = service.generate(
            symbol="CRM",
            research_eligibility=_eligible_eligibility("CRM"),
            company_intelligence_view=_ci_view("CRM"),
            investment_thesis_view=_thesis_view("CRM"),
            force_refresh=True,
        )
        identity = compute_context_semantic_identity(
            symbol="CRM",
            participation_result=None,
            company_intelligence_view=_ci_view("CRM"),
            investment_thesis_view=_thesis_view("CRM"),
        )
        session: dict = {}
        session[ai_summary_cache_key("CRM")] = view
        session[ai_summary_identity_key("CRM")] = identity
        cached = session.get(ai_summary_cache_key("CRM"))
        self.assertIsNotNone(cached)
        self.assertEqual(cached.status, "AVAILABLE")
        self.assertEqual(cached.financial_outlook, view.financial_outlook)

    def test_parse_accepts_json_code_fence(self) -> None:
        parsed = parse_ai_summary_response(f"```json\n{_valid_summary_json()}\n```")
        self.assertEqual(parsed.evidence_level, "LIMITED")


class AIResearchSummaryRenderContractTests(unittest.TestCase):
    def test_page_facing_renderer_accepts_generate_callback(self) -> None:
        import inspect

        from components.ai_research_summary_ui import render_ai_research_summary_section

        params = inspect.signature(render_ai_research_summary_section).parameters
        self.assertIn("generate_callback", params)
        self.assertEqual(
            inspect.getfile(render_ai_research_summary_section),
            str(Path("components/ai_research_summary_ui.py").resolve()),
        )

    def test_exact_page_call_pattern(self) -> None:
        import inspect

        from components.ai_research_summary_ui import render_ai_research_summary_section

        generated = AIResearchSummaryView(
            symbol="CRM",
            status="AVAILABLE",
            evidence_level="LIMITED",
            financial_outlook="Özet hazır.",
            generated_at="2026-08-15T00:00:00Z",
        )
        callback = MagicMock(return_value=generated)
        mock_st = MagicMock()
        mock_st.button.return_value = True
        mock_st.session_state = {}
        with patch("components.ai_research_summary_ui.st", mock_st), patch(
            "components.ai_research_summary_ui.mark_ai_summary_scroll_target"
        ):
            render_ai_research_summary_section(
                view=None,
                feature_enabled=True,
                symbol="CRM",
                generate_callback=callback,
            )
        callback.assert_called_once()
        mock_st.rerun.assert_not_called()
        mock_st.write.assert_called_with("Özet hazır.")

    def test_old_generate_requested_kwarg_is_not_supported(self) -> None:
        import inspect

        from components.ai_research_summary_ui import render_ai_research_summary_section

        self.assertNotIn(
            "generate_requested",
            inspect.signature(render_ai_research_summary_section).parameters,
        )


class AIResearchSummaryUiSmokeTests(unittest.TestCase):
    def test_turkish_render_smoke(self) -> None:
        from components.ai_research_summary_ui import render_ai_research_summary_section

        view = AIResearchSummaryView(
            symbol="CRM",
            status="AVAILABLE",
            evidence_level="LIMITED",
            financial_outlook="Son yıllık finansallara göre gelir artıyor.",
            valuation_summary="Oranlar hesaplanabiliyor; karşılaştırma kanıtı yok.",
            key_strengths=("Gelir artışı",),
            missing_evidence=("Haber verisi mevcut değil.",),
            generated_at="2026-08-15T00:00:00Z",
        )
        mock_st = MagicMock()
        mock_st.button.return_value = False
        mock_st.session_state = {}
        with patch("components.ai_research_summary_ui.st", mock_st):
            render_ai_research_summary_section(
                view,
                feature_enabled=True,
                symbol="CRM",
            )
        self.assertTrue(mock_st.subheader.called)

    def test_validation_failed_is_visible(self) -> None:
        from components.ai_research_summary_ui import render_ai_research_summary_section

        view = AIResearchSummaryView.validation_failed(
            symbol="CRM",
            message="AI özeti güvenlik doğrulamasından geçemedi.",
            evidence_level="LIMITED",
            metadata=None,
        )
        mock_st = MagicMock()
        mock_st.button.return_value = False
        mock_st.session_state = {}
        with patch("components.ai_research_summary_ui.st", mock_st):
            render_ai_research_summary_section(view, feature_enabled=True, symbol="CRM")
        mock_st.warning.assert_called_once()

    def test_button_click_generates_in_same_run_without_rerun(self) -> None:
        from components.ai_research_summary_ui import (
            ai_summary_scroll_to_key,
            render_ai_research_summary_section,
        )

        generated = AIResearchSummaryView(
            symbol="CRM",
            status="AVAILABLE",
            evidence_level="LIMITED",
            financial_outlook="Özet hazır.",
            generated_at="2026-08-15T00:00:00Z",
        )
        callback = MagicMock(return_value=generated)
        mock_st = MagicMock()
        mock_st.button.return_value = True
        mock_st.session_state = {}
        with patch("components.ai_research_summary_ui.st", mock_st), patch(
            "components.ai_research_summary_ui.mark_ai_summary_scroll_target"
        ) as mark_scroll:
            render_ai_research_summary_section(
                None,
                feature_enabled=True,
                symbol="CRM",
                generate_callback=callback,
            )
        callback.assert_called_once()
        mock_st.rerun.assert_not_called()
        mark_scroll.assert_called_once_with("CRM")

    def test_cached_render_does_not_set_scroll_anchor(self) -> None:
        from components.ai_research_summary_ui import (
            ai_summary_scroll_to_key,
            render_ai_research_summary_section,
        )

        view = AIResearchSummaryView(
            symbol="CRM",
            status="AVAILABLE",
            evidence_level="LIMITED",
            financial_outlook="Önbellekten.",
            generated_at="2026-08-15T00:00:00Z",
        )
        mock_st = MagicMock()
        mock_st.button.return_value = False
        session_state: dict = {}
        mock_st.session_state = session_state
        with patch("components.ai_research_summary_ui.st", mock_st):
            render_ai_research_summary_section(
                view,
                feature_enabled=True,
                symbol="CRM",
            )
        self.assertNotIn(ai_summary_scroll_to_key("CRM"), session_state)

    def test_provider_error_visible_and_scrolls(self) -> None:
        from components.ai_research_summary_ui import (
            ai_summary_scroll_to_key,
            render_ai_research_summary_section,
        )

        unavailable = AIResearchSummaryView.unavailable(
            symbol="CRM",
            message="AI araştırma özeti şu anda üretilemedi.",
        )
        mock_st = MagicMock()
        mock_st.button.return_value = True
        mock_st.session_state = {}
        with patch("components.ai_research_summary_ui.st", mock_st), patch(
            "components.ai_research_summary_ui.mark_ai_summary_scroll_target"
        ) as mark_scroll:
            render_ai_research_summary_section(
                None,
                feature_enabled=True,
                symbol="CRM",
                generate_callback=MagicMock(return_value=unavailable),
            )
        mock_st.info.assert_called()
        mark_scroll.assert_called_once_with("CRM")

    def test_section_anchor_is_symbol_specific(self) -> None:
        from components.ai_research_summary_ui import ai_summary_section_anchor_id

        self.assertEqual(ai_summary_section_anchor_id("crm"), "nabi-ai-research-summary-CRM")
        self.assertNotEqual(
            ai_summary_section_anchor_id("CRM"),
            ai_summary_section_anchor_id("JNJ"),
        )

    def test_validation_failed_scrolls_to_section(self) -> None:
        from components.ai_research_summary_ui import (
            ai_summary_scroll_to_key,
            render_ai_research_summary_section,
        )

        failed = AIResearchSummaryView.validation_failed(
            symbol="CRM",
            message="AI özeti güvenlik doğrulamasından geçemedi.",
        )
        mock_st = MagicMock()
        mock_st.button.return_value = True
        mock_st.session_state = {}
        with patch("components.ai_research_summary_ui.st", mock_st), patch(
            "components.ai_research_summary_ui.mark_ai_summary_scroll_target"
        ) as mark_scroll:
            render_ai_research_summary_section(
                None,
                feature_enabled=True,
                symbol="CRM",
                generate_callback=MagicMock(return_value=failed),
            )
        mock_st.warning.assert_called()
        mark_scroll.assert_called_once_with("CRM")
        from components.ai_research_summary_ui import scroll_to_ai_summary_section

        with patch("components.ai_research_summary_ui.components.html") as mock_html:
            scroll_to_ai_summary_section("CRM")
        rendered = mock_html.call_args.args[0]
        self.assertIn("nabi-ai-research-summary-CRM", rendered)
        self.assertIn("scrollIntoView", rendered)


class AIResearchSummaryDisplayTests(unittest.TestCase):
    def test_strip_internal_enum_labels_from_prose(self) -> None:
        from services.ai_research_summary_display import strip_internal_enum_labels

        cleaned = strip_internal_enum_labels("Değerleme verisi yok (VALUATION_UNAVAILABLE).")
        self.assertNotIn("VALUATION_UNAVAILABLE", cleaned)
        self.assertIn("Değerleme verisi yok", cleaned)

    def test_hybrid_valuation_hesaplanamiyor_is_replaced(self) -> None:
        from services.ai_research_summary_display import polish_ai_research_summary_view

        view = AIResearchSummaryView(
            symbol="CRM",
            status="AVAILABLE",
            evidence_level="LIMITED",
            valuation_summary="Mevcut değerleme oranları hesaplanamıyor.",
        )
        polished = polish_ai_research_summary_view(view, unified=_limited_unified("CRM"))
        self.assertNotIn("hesaplanamıyor", polished.valuation_summary.lower())
        self.assertIn("P/S", polished.valuation_summary)
        self.assertIn("3.87", polished.valuation_summary)
        self.assertIn("göreceli değerleme yorumu sınırlı", polished.valuation_summary)

    def test_hybrid_valuation_wording_distinguishes_metrics_and_context(self) -> None:
        from services.ai_research_summary_display import polish_ai_research_summary_view

        view = AIResearchSummaryView(
            symbol="CRM",
            status="AVAILABLE",
            evidence_level="LIMITED",
            valuation_summary="Değerleme verisi yok (VALUATION_UNAVAILABLE).",
        )
        polished = polish_ai_research_summary_view(
            view,
            unified=_limited_unified("CRM"),
        )
        self.assertNotIn("VALUATION_UNAVAILABLE", polished.valuation_summary)
        self.assertIn("P/S", polished.valuation_summary)
        self.assertIn("göreceli değerleme yorumu sınırlı", polished.valuation_summary)

    def test_no_metrics_keeps_unavailable_wording(self) -> None:
        from services.ai_research_summary_display import polish_valuation_summary_text

        unified = UnifiedResearchContext(
            symbol="CRM",
            company_name="CRM Inc.",
            schema_version="unified-research-v1",
            generated_at=datetime.now(timezone.utc).isoformat(),
            company_intelligence={"symbol": "CRM", "valuation_metrics": []},
            investment_thesis={"symbol": "CRM", "valuation_context": "VALUATION_UNAVAILABLE"},
            nabi_context=None,
            participation_context=None,
            wealth_exposure_context=None,
            data_quality={"valuation_available": False, "historical_valuation_available": False},
            provenance=(),
            focus_symbol="CRM",
        )
        polished = polish_valuation_summary_text(
            "Mevcut değerleme oranları hesaplanamıyor.",
            unified=unified,
        )
        self.assertIn("hesaplanamıyor", polished.lower())

    def test_metric_observation_enums_translate_without_thesis_inflation(self) -> None:
        from services.ai_research_summary_display import polish_user_facing_text

        polished = polish_user_facing_text(
            "Yıllık gelir trendi artış yönünde (IMPROVING, HIGH confidence)."
        )
        self.assertNotIn("IMPROVING", polished)
        self.assertNotIn("HIGH confidence", polished)
        self.assertIn("artış yönünde", polished)
        self.assertIn("bu sinyalin veri güveni yüksek", polished)

    def test_primary_summary_strips_machine_tokens(self) -> None:
        from services.ai_research_summary_display import (
            polish_ai_research_summary_view,
            primary_text_contains_machine_tokens,
        )

        view = AIResearchSummaryView(
            symbol="CRM",
            status="AVAILABLE",
            evidence_level="LIMITED",
            financial_outlook="AUTHORITATIVE_RESEARCH_CONTEXT kullanıldı.",
            valuation_summary="Thesis durumu INSUFFICIENT_DATA ve confidence LOW.",
            limitations=(
                "Araştırma yalnızca AUTHORITATIVE_RESEARCH_CONTEXT içeriğiyle sınırlandırılmıştır.",
            ),
        )
        polished = polish_ai_research_summary_view(view, unified=_limited_unified("CRM"))
        combined = " ".join(
            [
                polished.financial_outlook,
                polished.valuation_summary,
                *polished.limitations,
            ]
        )
        self.assertFalse(primary_text_contains_machine_tokens(combined))
        self.assertNotIn("HIGH confidence", combined)
        self.assertIn("doğrulanmış nabi araştırma verileri", combined.lower())

    def test_limitations_are_turkish_human_readable(self) -> None:
        from services.ai_research_summary_display import polish_user_facing_text

        polished = polish_user_facing_text(
            "Thesis durumu INSUFFICIENT_DATA ve confidence LOW; valuation UNAVAILABLE.",
            section="limitations",
        )
        self.assertIn("kanıt yetersiz", polished.lower())
        self.assertIn("güven düzeyi düşük", polished.lower())
        self.assertNotIn("INSUFFICIENT_DATA", polished)
        self.assertNotIn("UNAVAILABLE", polished)

    def test_jnj_generic_display_polish(self) -> None:
        from services.ai_research_summary_display import polish_ai_research_summary_view

        view = AIResearchSummaryView(
            symbol="JNJ",
            status="AVAILABLE",
            evidence_level="LIMITED",
            valuation_summary="Mevcut değerleme oranları hesaplanamıyor.",
        )
        polished = polish_ai_research_summary_view(view, unified=_limited_unified("JNJ"))
        self.assertIn("P/S", polished.valuation_summary)
        self.assertNotIn("hesaplanamıyor", polished.valuation_summary.lower())

    def test_limited_context_always_uses_authoritative_framing(self) -> None:
        from services.ai_research_summary_display import enforce_valuation_summary_invariant
        from services.ai_research_summary_valuation_semantics import derive_valuation_semantics

        semantics = derive_valuation_semantics(_limited_unified("CRM"))
        neutral_llm = "Değerleme bölümünde genel bir yorum yapılmıştır."
        enforced = enforce_valuation_summary_invariant(neutral_llm, semantics=semantics)
        self.assertIn("hibrit yıllık değerleme oranları", enforced.lower())
        self.assertIn("3.87", enforced)

    def test_full_relative_context_preserves_llm_valuation(self) -> None:
        from services.ai_research_summary_display import enforce_valuation_summary_invariant
        from services.ai_research_summary_valuation_semantics import derive_valuation_semantics

        unified = UnifiedResearchContext(
            symbol="CRM",
            company_name="CRM Inc.",
            schema_version="unified-research-v1",
            generated_at=datetime.now(timezone.utc).isoformat(),
            company_intelligence={
                "symbol": "CRM",
                "valuation_metrics": [
                    {"code": "price_to_sales", "label": "P/S", "current_value": 3.87},
                ],
                "data_quality": {
                    "valuation_available": True,
                    "historical_valuation_available": True,
                    "peer_data_available": True,
                },
            },
            investment_thesis={"symbol": "CRM", "valuation_context": "SUPPORTED"},
            nabi_context=None,
            participation_context=None,
            wealth_exposure_context=None,
            data_quality={
                "valuation_available": True,
                "historical_valuation_available": True,
                "peer_data_available": True,
            },
            provenance=(),
            focus_symbol="CRM",
        )
        semantics = derive_valuation_semantics(unified)
        llm_text = "Tarihsel medyanın üzerinde işlem görüyor; göreceli yorum mümkün."
        enforced = enforce_valuation_summary_invariant(llm_text, semantics=semantics)
        self.assertEqual(enforced.rstrip("."), llm_text.rstrip("."))

    def test_provider_tokens_are_humanized(self) -> None:
        from services.ai_research_summary_display import polish_user_facing_text

        polished = polish_user_facing_text(
            "Haber akışı RATE_LIMIT nedeniyle sınırlı (fmp)."
        )
        self.assertNotIn("RATE_LIMIT", polished)
        self.assertNotIn("(fmp)", polished.lower())
        self.assertIn("veri sağlayıcı", polished.lower())

    def test_valuation_invariant_does_not_overwrite_unrelated_fields(self) -> None:
        from services.ai_research_summary_display import polish_ai_research_summary_view

        view = AIResearchSummaryView(
            symbol="CRM",
            status="AVAILABLE",
            evidence_level="LIMITED",
            financial_outlook="Gelir trendi yıllık bazda iyileşiyor.",
            valuation_summary="Değerleme oranları hesaplanamıyor.",
            key_strengths=("Gelir büyümesi destekleyici.",),
            key_weaknesses=("Çeyreklik veri eksik.",),
            missing_evidence=("Rakip karşılaştırması yok.",),
            monitoring_points=("Bir sonraki yıllık rapor izlenmeli.",),
            limitations=("Tez güveni düşük.",),
        )
        polished = polish_ai_research_summary_view(view, unified=_limited_unified("CRM"))

        self.assertEqual(polished.financial_outlook, "Gelir trendi yıllık bazda iyileşiyor")
        self.assertIn("3.87", polished.valuation_summary)
        self.assertNotIn("hesaplanamıyor", polished.valuation_summary.lower())
        self.assertEqual(polished.key_strengths, ("Gelir büyümesi destekleyici",))
        self.assertEqual(polished.key_weaknesses, ("Çeyreklik veri eksik",))
        self.assertEqual(polished.missing_evidence, ("Rakip karşılaştırması yok",))
        self.assertEqual(polished.monitoring_points, ("Bir sonraki yıllık rapor izlenmeli",))
        self.assertEqual(polished.limitations, ("Tez güveni düşük",))
        valuation_lower = polished.valuation_summary.lower()
        for field_text in (
            polished.financial_outlook,
            *polished.key_strengths,
            *polished.key_weaknesses,
            *polished.missing_evidence,
            *polished.monitoring_points,
            *polished.limitations,
        ):
            self.assertNotEqual(field_text.lower(), valuation_lower)

    def test_cached_repolish_preserves_field_separation(self) -> None:
        from services.ai_research_summary_contract import AIResearchSummaryMetadata
        from services.ai_research_summary_display import polish_ai_research_summary_view
        from services.ai_research_summary_valuation_semantics import derive_valuation_semantics

        semantics = derive_valuation_semantics(_limited_unified("CRM"))
        stale = AIResearchSummaryView(
            symbol="CRM",
            status="AVAILABLE",
            evidence_level="LIMITED",
            financial_outlook="Gelir trendi yıllık bazda iyileşiyor.",
            valuation_summary="Mevcut değerleme oranları hesaplanamıyor.",
            key_strengths=("Gelir büyümesi destekleyici.",),
            key_weaknesses=("Çeyreklik veri eksik.",),
            metadata=AIResearchSummaryMetadata(
                context_semantic_identity="stale",
                validation_outcome="valid",
                valuation_semantics=semantics.to_dict(),
            ),
        )
        repolished = polish_ai_research_summary_view(stale, unified=_limited_unified("CRM"))
        self.assertEqual(repolished.financial_outlook, "Gelir trendi yıllık bazda iyileşiyor")
        self.assertIn("3.87", repolished.valuation_summary)
        self.assertEqual(repolished.key_strengths, ("Gelir büyümesi destekleyici",))
        self.assertEqual(repolished.key_weaknesses, ("Çeyreklik veri eksik",))

    def test_persisted_roundtrip_preserves_field_separation(self) -> None:
        from services.ai_research_summary_display import polish_ai_research_summary_view
        from services.ai_research_summary_persistence_service import (
            build_snapshot_payload,
            view_from_row,
        )

        raw = AIResearchSummaryView(
            symbol="JNJ",
            status="AVAILABLE",
            evidence_level="LIMITED",
            financial_outlook="Gelir trendi yıllık bazda iyileşiyor.",
            valuation_summary="Değerleme oranları hesaplanamıyor.",
            key_strengths=("Gelir büyümesi destekleyici.",),
            key_weaknesses=("Çeyreklik veri eksik.",),
            monitoring_points=("Bir sonraki yıllık rapor izlenmeli.",),
        )
        polished = polish_ai_research_summary_view(raw, unified=_limited_unified("JNJ"))
        row = build_snapshot_payload(polished, semantic_identity="jnj-identity")
        restored = view_from_row(row, semantic_identity="jnj-identity")
        self.assertEqual(restored.financial_outlook, polished.financial_outlook)
        self.assertEqual(restored.valuation_summary, polished.valuation_summary)
        self.assertEqual(restored.key_strengths, polished.key_strengths)
        self.assertNotEqual(restored.valuation_summary, restored.financial_outlook)

    def test_display_version_bump_invalidates_corrupted_snapshot_identity(self) -> None:
        from services.ai_research_summary_contract import AI_RESEARCH_SUMMARY_DISPLAY_VERSION
        from services import ai_research_summary_service as summary_service_module
        from unittest.mock import patch

        self.assertEqual(AI_RESEARCH_SUMMARY_DISPLAY_VERSION, "display-polish-v3")
        kwargs = {
            "symbol": "CRM",
            "participation_result": None,
            "company_intelligence_view": _ci_view("CRM"),
            "investment_thesis_view": _thesis_view("CRM"),
        }
        current = compute_context_semantic_identity(**kwargs)
        with patch.object(
            summary_service_module,
            "AI_RESEARCH_SUMMARY_DISPLAY_VERSION",
            "display-polish-v2",
        ):
            old = compute_context_semantic_identity(**kwargs)
        self.assertNotEqual(current, old)

    def test_cached_unpolished_view_repolished_from_metadata_snapshot(self) -> None:
        from services.ai_research_summary_contract import AIResearchSummaryMetadata
        from services.ai_research_summary_display import polish_ai_research_summary_view
        from services.ai_research_summary_valuation_semantics import derive_valuation_semantics

        semantics = derive_valuation_semantics(_limited_unified("CRM"))
        stale = AIResearchSummaryView(
            symbol="CRM",
            status="AVAILABLE",
            evidence_level="LIMITED",
            valuation_summary="Mevcut değerleme oranları hesaplanamıyor.",
            metadata=AIResearchSummaryMetadata(
                context_semantic_identity="stale",
                validation_outcome="valid",
                valuation_semantics=semantics.to_dict(),
            ),
        )
        repolished = polish_ai_research_summary_view(stale)
        self.assertNotIn("hesaplanamıyor", repolished.valuation_summary.lower())
        self.assertIn("3.87", repolished.valuation_summary)

    def test_cache_store_load_keeps_authoritative_valuation(self) -> None:
        from components.ai_research_summary_ui import load_cached_ai_summary, store_ai_summary
        from services.ai_research_summary_contract import AIResearchSummaryMetadata
        from services.ai_research_summary_display import polish_ai_research_summary_view
        from services.ai_research_summary_valuation_semantics import derive_valuation_semantics
        import streamlit as st

        if not hasattr(st, "session_state"):
            st.session_state = {}
        st.session_state.clear()

        semantics = derive_valuation_semantics(_limited_unified("CRM"))
        raw_view = AIResearchSummaryView(
            symbol="CRM",
            status="AVAILABLE",
            evidence_level="LIMITED",
            valuation_summary="Mevcut değerleme oranları hesaplanamıyor.",
            metadata=AIResearchSummaryMetadata(
                context_semantic_identity="identity",
                validation_outcome="valid",
                valuation_semantics=semantics.to_dict(),
            ),
        )
        polished = polish_ai_research_summary_view(raw_view, unified=_limited_unified("CRM"))
        store_ai_summary("CRM", polished, identity="identity")
        loaded, identity = load_cached_ai_summary("CRM")
        assert loaded is not None
        self.assertEqual(identity, "identity")
        self.assertNotIn("hesaplanamıyor", loaded.valuation_summary.lower())
        self.assertIn("3.87", loaded.valuation_summary)

    def test_service_cache_hit_reapplies_display_polish(self) -> None:
        unified = _limited_unified("CRM")
        stale_cached = AIResearchSummaryView(
            symbol="CRM",
            status="AVAILABLE",
            evidence_level="LIMITED",
            valuation_summary="Mevcut değerleme oranları hesaplanamıyor.",
        )
        service = AIResearchSummaryService(
            config=_enabled_config(),
            client=MagicMock(),
            unified_research_service=MagicMock(build_context=MagicMock(return_value=unified)),
        )
        view = service.generate(
            symbol="CRM",
            research_eligibility=_eligible_eligibility("CRM"),
            company_intelligence_view=_ci_view("CRM"),
            investment_thesis_view=_thesis_view("CRM"),
            cached_view=stale_cached,
            cached_identity=compute_context_semantic_identity(
                symbol="CRM",
                participation_result=None,
                company_intelligence_view=_ci_view("CRM"),
                investment_thesis_view=_thesis_view("CRM"),
            ),
            force_refresh=False,
        )
        self.assertTrue(view.metadata.cache_hit if view.metadata else False)
        self.assertNotIn("hesaplanamıyor", view.valuation_summary.lower())
        self.assertIn("3.87", view.valuation_summary)

    def test_service_polishes_available_summary(self) -> None:
        raw_json = _valid_summary_json().replace(
            "P/S, P/FCF ve EV/EBIT hesaplanabiliyor; tarihsel karşılaştırma kanıtı yok.",
            "Değerleme verisi yok (VALUATION_UNAVAILABLE).",
        )
        service = AIResearchSummaryService(
            config=_enabled_config(),
            client=MagicMock(complete=MagicMock(return_value=raw_json)),
            unified_research_service=MagicMock(
                build_context=MagicMock(return_value=_limited_unified("CRM"))
            ),
        )
        view = service.generate(
            symbol="CRM",
            research_eligibility=_eligible_eligibility("CRM"),
            company_intelligence_view=_ci_view("CRM"),
            investment_thesis_view=_thesis_view("CRM"),
            force_refresh=True,
        )
        self.assertEqual(view.status, "AVAILABLE")
        self.assertNotIn("VALUATION_UNAVAILABLE", view.valuation_summary)
        self.assertIn("P/S", view.valuation_summary)


if __name__ == "__main__":
    unittest.main()
