from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from services.ai_research_summary_contract import (
    AI_RESEARCH_SUMMARY_DISPLAY_VERSION,
    AI_RESEARCH_SUMMARY_VERSION,
    AIResearchSummaryMetadata,
    AIResearchSummaryView,
)
from services.ai_research_summary_prompt import (
    build_ai_summary_messages,
    build_ai_summary_payload,
    validate_ai_summary_payload_shape,
)
from services.ai_research_summary_display import polish_ai_research_summary_view
from services.ai_research_summary_trace import capture_ai_summary_generation_trace
from services.ai_research_summary_valuation_semantics import (
    derive_valuation_semantics,
    merged_unified_data_quality,
)
from services.ai_research_summary_validator import (
    AIResearchSummaryConstraints,
    extract_context_uppercase_tokens,
    parse_ai_summary_response,
    validate_ai_research_summary,
)
from services.company_intelligence_contract import CompanyIntelligenceView
from services.investment_thesis_contract import InvestmentThesisView
from services.investment_thesis_persistence_service import compute_semantic_identity as thesis_semantic_identity
from services.participation_assessment_persistence_service import (
    compute_semantic_identity as participation_semantic_identity,
)
from services.research_eligibility_contract import ResearchEligibilityResult
from services.research_eligibility_service import require_research_allowed
from services.unified_research_contract import UnifiedResearchContext
from services.unified_research_service import UnifiedResearchService
from services.wealth_adviser_config import AdviserLlmConfig, load_adviser_llm_config
from services.wealth_adviser_llm_client import WealthAdviserLlmClient, WealthAdviserLlmError


def _normalize_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper()


def infer_financial_trends_source(
    company_intelligence_view: Optional[CompanyIntelligenceView],
) -> Optional[str]:
    if company_intelligence_view is None or company_intelligence_view.financial_trends is None:
        return None
    provenance = company_intelligence_view.financial_trends.provenance
    if provenance.data_family == "financial_statements_annual":
        return "sec_annual"
    if provenance.provider == "fmp":
        return "fmp_quarterly"
    return provenance.data_family or provenance.provider


def compute_evidence_level(
    unified: UnifiedResearchContext,
    *,
    investment_thesis_view: Optional[InvestmentThesisView],
) -> str:
    ci = unified.company_intelligence or {}
    dq = merged_unified_data_quality(unified)
    thesis = unified.investment_thesis or {}
    thesis_status = thesis.get("thesis_status")
    thesis_confidence = thesis.get("confidence")
    if investment_thesis_view is not None:
        thesis_status = investment_thesis_view.thesis_status
        thesis_confidence = investment_thesis_view.confidence

    if thesis_status == "INSUFFICIENT_DATA" or thesis_confidence == "LOW":
        return "LIMITED"

    quarterly = bool(dq.get("quarterly_comparison_available"))
    earnings = bool(dq.get("earnings_expectations_available"))
    news = bool(dq.get("news_available"))
    peers = bool(dq.get("peer_data_available"))
    historical_valuation = bool(dq.get("historical_valuation_available"))

    if (
        quarterly
        and earnings
        and historical_valuation
        and (news or peers)
        and thesis_status in {"SUPPORTED", "MIXED"}
    ):
        return "STRONG"
    if quarterly and earnings:
        return "MODERATE"
    if bool(dq.get("financial_history_available")):
        return "LIMITED"
    return "LIMITED"


def compute_ci_semantic_fingerprint(
    company_intelligence_view: Optional[CompanyIntelligenceView],
) -> Optional[str]:
    if company_intelligence_view is None:
        return None
    trends = company_intelligence_view.financial_trends
    valuation = company_intelligence_view.valuation
    dq = company_intelligence_view.data_quality
    payload = {
        "symbol": company_intelligence_view.symbol,
        "trends": tuple(
            (
                point.metric,
                point.latest_value,
                point.previous_value,
                point.pct_change,
                point.direction,
                point.period,
            )
            for point in (trends.trends if trends else ())
        ),
        "valuation": tuple(
            (
                metric.code,
                metric.current_value,
                metric.historical_median,
                metric.position,
                metric.alignment_status,
            )
            for metric in (valuation.metrics if valuation else ())
        ),
        "data_quality": (
            {
                "financial_history_available": dq.financial_history_available,
                "quarterly_comparison_available": dq.quarterly_comparison_available,
                "earnings_expectations_available": dq.earnings_expectations_available,
                "valuation_available": dq.valuation_available,
                "historical_valuation_available": dq.historical_valuation_available,
                "peer_data_available": dq.peer_data_available,
                "news_available": dq.news_available,
                "catalyst_data_available": dq.catalyst_data_available,
                "partial_sections": tuple(dq.partial_sections),
                "provider_failures": tuple(dq.provider_failures),
            }
            if dq
            else None
        ),
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def compute_context_semantic_identity(
    *,
    symbol: str,
    participation_result: Any,
    company_intelligence_view: Optional[CompanyIntelligenceView],
    investment_thesis_view: Optional[InvestmentThesisView],
) -> str:
    payload = {
        "symbol": _normalize_symbol(symbol),
        "participation": (
            participation_semantic_identity(participation_result)
            if participation_result is not None
            else None
        ),
        "ci_fingerprint": compute_ci_semantic_fingerprint(company_intelligence_view),
        "thesis": (
            thesis_semantic_identity(investment_thesis_view)
            if investment_thesis_view is not None
            else None
        ),
        "summary_version": AI_RESEARCH_SUMMARY_VERSION,
        "display_polish_version": AI_RESEARCH_SUMMARY_DISPLAY_VERSION,
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_summary_constraints(
    unified: UnifiedResearchContext,
    *,
    evidence_level: str,
) -> AIResearchSummaryConstraints:
    ci = unified.company_intelligence or {}
    dq = merged_unified_data_quality(unified)
    thesis = unified.investment_thesis or {}
    participation = unified.participation_context
    return AIResearchSummaryConstraints(
        symbol=unified.symbol,
        participation_status=participation.status if participation else None,
        thesis_status=thesis.get("thesis_status"),
        thesis_confidence=thesis.get("confidence"),
        evidence_level=evidence_level,
        earnings_available=bool(dq.get("earnings_expectations_available")),
        news_available=bool(dq.get("news_available")),
        peers_available=bool(dq.get("peer_data_available")),
        historical_valuation_available=bool(dq.get("historical_valuation_available")),
        allowed_symbols=(unified.symbol,),
        context_uppercase_tokens=extract_context_uppercase_tokens(unified.to_dict()),
    )


class AIResearchSummaryService:
    def __init__(
        self,
        *,
        config: Optional[AdviserLlmConfig] = None,
        client: Optional[WealthAdviserLlmClient] = None,
        unified_research_service: Optional[UnifiedResearchService] = None,
    ) -> None:
        self.config = config or load_adviser_llm_config()
        self.client = client or WealthAdviserLlmClient.from_config(self.config)
        self.unified_research_service = unified_research_service or UnifiedResearchService()

    def build_unified_context(
        self,
        *,
        symbol: str,
        research_eligibility: ResearchEligibilityResult,
        company_intelligence_view: CompanyIntelligenceView,
        investment_thesis_view: InvestmentThesisView,
        candidate: Optional[Mapping[str, Any]] = None,
        participation_view: Any = None,
        previous_thesis_snapshot: Optional[Mapping[str, Any]] = None,
    ) -> UnifiedResearchContext:
        require_research_allowed(research_eligibility, symbol=symbol)
        return self.unified_research_service.build_context(
            symbol=symbol,
            research_eligibility=research_eligibility,
            company_intelligence_view=company_intelligence_view,
            investment_thesis_view=investment_thesis_view,
            candidate=candidate,
            participation_view=participation_view,
            previous_thesis_snapshot=previous_thesis_snapshot,
        )

    def generate(
        self,
        *,
        symbol: str,
        research_eligibility: ResearchEligibilityResult,
        company_intelligence_view: CompanyIntelligenceView,
        investment_thesis_view: InvestmentThesisView,
        candidate: Optional[Mapping[str, Any]] = None,
        participation_view: Any = None,
        previous_thesis_snapshot: Optional[Mapping[str, Any]] = None,
        cached_view: Optional[AIResearchSummaryView] = None,
        cached_identity: Optional[str] = None,
        persisted_view: Optional[AIResearchSummaryView] = None,
        force_refresh: bool = False,
    ) -> AIResearchSummaryView:
        normalized = _normalize_symbol(symbol)
        if not research_eligibility.research_allowed:
            return AIResearchSummaryView.unavailable(
                symbol=normalized,
                message="Araştırma özeti yalnızca araştırmaya uygun semboller için üretilebilir.",
            )
        if not self.config.is_usable:
            return AIResearchSummaryView.unavailable(
                symbol=normalized,
                message="AI araştırma özeti şu anda etkin değil.",
            )

        participation_result = None
        if participation_view is not None and getattr(participation_view, "result", None) is not None:
            participation_result = participation_view.result

        context_identity = compute_context_semantic_identity(
            symbol=normalized,
            participation_result=participation_result,
            company_intelligence_view=company_intelligence_view,
            investment_thesis_view=investment_thesis_view,
        )

        unified = self.build_unified_context(
            symbol=normalized,
            research_eligibility=research_eligibility,
            company_intelligence_view=company_intelligence_view,
            investment_thesis_view=investment_thesis_view,
            candidate=candidate,
            participation_view=participation_view,
            previous_thesis_snapshot=previous_thesis_snapshot,
        )
        valuation_semantics = derive_valuation_semantics(unified)

        if (
            not force_refresh
            and cached_view is not None
            and cached_identity == context_identity
            and cached_view.status == "AVAILABLE"
        ):
            return self._reuse_available_view(
                cached_view,
                unified=unified,
                context_identity=context_identity,
                valuation_semantics=valuation_semantics,
                validation_outcome="cache_hit",
                cache_hit=True,
            )

        if (
            not force_refresh
            and persisted_view is not None
            and persisted_view.status == "AVAILABLE"
        ):
            return self._reuse_available_view(
                persisted_view,
                unified=unified,
                context_identity=context_identity,
                valuation_semantics=valuation_semantics,
                validation_outcome="persisted",
                cache_hit=False,
            )

        evidence_level = compute_evidence_level(
            unified,
            investment_thesis_view=investment_thesis_view,
        )
        payload = build_ai_summary_payload(
            unified,
            evidence_level=evidence_level,
            financial_trends_source=infer_financial_trends_source(company_intelligence_view),
        )
        if not validate_ai_summary_payload_shape(payload):
            return AIResearchSummaryView.validation_failed(
                symbol=normalized,
                message="AI özeti isteği güvenli biçimde oluşturulamadı.",
                evidence_level=evidence_level,
            )

        capture_ai_summary_generation_trace(
            company_intelligence_view=company_intelligence_view,
            investment_thesis_view=investment_thesis_view,
            unified=unified,
            valuation_semantics=valuation_semantics,
            payload=payload,
        )

        started = time.perf_counter()
        try:
            raw = self.client.complete(build_ai_summary_messages(payload))
        except WealthAdviserLlmError as exc:
            return AIResearchSummaryView(
                symbol=normalized,
                status="UNAVAILABLE",
                evidence_level=evidence_level,
                user_message="AI araştırma özeti şu anda üretilemedi.",
                limitations=("AI araştırma özeti şu anda üretilemedi.",),
                metadata=AIResearchSummaryMetadata(
                    context_semantic_identity=context_identity,
                    validation_outcome=f"provider_error:{exc.error_class}",
                    llm_call_count=1,
                ),
            )
        latency_ms = int((time.perf_counter() - started) * 1000)
        generated_at = datetime.now(timezone.utc).isoformat()

        try:
            parsed = parse_ai_summary_response(raw)
        except (ValueError, json.JSONDecodeError):
            return AIResearchSummaryView.validation_failed(
                symbol=normalized,
                message="AI özeti yanıtı doğrulanamadı.",
                evidence_level=evidence_level,
                metadata=AIResearchSummaryMetadata(
                    context_semantic_identity=context_identity,
                    validation_outcome="parse_failed",
                    latency_ms=latency_ms,
                    llm_call_count=1,
                ),
            )

        validation = validate_ai_research_summary(
            parsed,
            build_summary_constraints(unified, evidence_level=evidence_level),
        )
        if not validation.valid:
            from services.ai_research_summary_validator import (
                explain_thesis_confidence_inflation_for_summary,
            )

            capture_ai_summary_generation_trace(
                company_intelligence_view=company_intelligence_view,
                investment_thesis_view=investment_thesis_view,
                unified=unified,
                valuation_semantics=valuation_semantics,
                payload=payload,
                raw_llm_response=None,
                parsed_valuation_summary=parsed.valuation_summary,
                validation_failure={
                    "reasons": list(validation.reasons),
                    "thesis_confidence_inflation_matches": list(
                        explain_thesis_confidence_inflation_for_summary(parsed)
                    ),
                    "summary_fields": {
                        "financial_outlook": parsed.financial_outlook,
                        "valuation_summary": parsed.valuation_summary,
                        "key_strengths": list(parsed.key_strengths),
                        "key_weaknesses": list(parsed.key_weaknesses),
                        "risks_to_watch": list(parsed.risks_to_watch),
                        "missing_evidence": list(parsed.missing_evidence),
                        "monitoring_points": list(parsed.monitoring_points),
                        "limitations": list(parsed.limitations),
                        "evidence_level": parsed.evidence_level,
                    },
                },
            )
            return AIResearchSummaryView.validation_failed(
                symbol=normalized,
                message="AI özeti güvenlik doğrulamasından geçemedi.",
                evidence_level=evidence_level,
                metadata=AIResearchSummaryMetadata(
                    context_semantic_identity=context_identity,
                    validation_outcome=",".join(validation.reasons[:3]) or "validation_failed",
                    latency_ms=latency_ms,
                    llm_call_count=1,
                ),
            )

        polished_view = polish_ai_research_summary_view(
            AIResearchSummaryView(
                symbol=normalized,
                status="AVAILABLE",
                evidence_level=parsed.evidence_level,
                financial_outlook=parsed.financial_outlook,
                valuation_summary=parsed.valuation_summary,
                key_strengths=parsed.key_strengths,
                key_weaknesses=parsed.key_weaknesses,
                risks_to_watch=parsed.risks_to_watch,
                missing_evidence=parsed.missing_evidence,
                monitoring_points=parsed.monitoring_points,
                limitations=parsed.limitations,
                generated_at=generated_at,
                model_provider=self.config.provider,
                model_name=self.config.model,
                metadata=AIResearchSummaryMetadata(
                    context_semantic_identity=context_identity,
                    validation_outcome="valid",
                    latency_ms=latency_ms,
                    llm_call_count=1,
                    valuation_semantics=valuation_semantics.to_dict(),
                    display_polish_version=AI_RESEARCH_SUMMARY_DISPLAY_VERSION,
                ),
            ),
            unified=unified,
            semantics=valuation_semantics,
        )
        capture_ai_summary_generation_trace(
            company_intelligence_view=company_intelligence_view,
            investment_thesis_view=investment_thesis_view,
            unified=unified,
            valuation_semantics=valuation_semantics,
            payload=payload,
            raw_llm_response=parsed.valuation_summary,
            parsed_valuation_summary=parsed.valuation_summary,
            final_valuation_summary=polished_view.valuation_summary,
        )
        return polished_view

    def _reuse_available_view(
        self,
        view: AIResearchSummaryView,
        *,
        unified: UnifiedResearchContext,
        context_identity: str,
        valuation_semantics: Any,
        validation_outcome: str,
        cache_hit: bool,
    ) -> AIResearchSummaryView:
        polished = polish_ai_research_summary_view(
            view,
            unified=unified,
            semantics=valuation_semantics,
        )
        metadata = AIResearchSummaryMetadata(
            context_semantic_identity=context_identity,
            validation_outcome=validation_outcome,
            llm_call_count=0,
            cache_hit=cache_hit,
            valuation_semantics=valuation_semantics.to_dict(),
            display_polish_version=AI_RESEARCH_SUMMARY_DISPLAY_VERSION,
        )
        return AIResearchSummaryView(
            symbol=polished.symbol,
            status=polished.status,
            evidence_level=polished.evidence_level,
            financial_outlook=polished.financial_outlook,
            valuation_summary=polished.valuation_summary,
            key_strengths=polished.key_strengths,
            key_weaknesses=polished.key_weaknesses,
            risks_to_watch=polished.risks_to_watch,
            missing_evidence=polished.missing_evidence,
            monitoring_points=polished.monitoring_points,
            limitations=polished.limitations,
            generated_at=polished.generated_at,
            model_provider=polished.model_provider,
            model_name=polished.model_name,
            source_context_version=polished.source_context_version,
            metadata=metadata,
        )
