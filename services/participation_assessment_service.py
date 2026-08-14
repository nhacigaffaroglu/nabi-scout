from __future__ import annotations

"""End-to-end equity participation assessment orchestration (Phase 6B.2c/6B.2d).

Composes SEC fetch, input resolution, financial screening, optional business
activity screening, and assessment composition into a single callable API.
Isolated from Scanner, NABI Score, decision engine, and persistence.

Confidence policy (deterministic, conservative):
- LOW when SEC is unavailable or no meaningful financial/business rule evaluated
- MEDIUM when SEC succeeded and at least one financial rule reached PASS/FAIL,
  and business evidence (if provided) produced evaluable business rules
- HIGH is never assigned in 6B.2c/6B.2d
"""

from dataclasses import dataclass, field, replace
from typing import Any, Dict, Optional, Tuple

from services.participation_business_contract import (
    BusinessActivityEvidence,
    BusinessActivityScreenResult,
)
from services.participation_business_evidence_enrichment import (
    derive_non_permissible_revenue_amount,
    enrich_business_activity_evidence,
)
from services.participation_business_engine import evaluate_business_activity
from services.participation_methodology_capabilities import blocking_missing_capabilities
from services.participation_message_normalization import merge_warning_messages
from services.participation_business_rules_registry import get_methodology_business_rules
from services.participation_sec_segment_resolver import merge_revenue_segment_sources
from services.participation_completeness import build_assessment_completeness
from services.participation_evidence_service import (
    load_participation_evidence_bundle,
    merge_participation_financial_inputs,
)
from services.participation_financial_contract import (
    ParticipationFinancialInputs,
    ParticipationFinancialScreenResult,
)
from services.participation_financial_engine import evaluate_financial_rules
from services.participation_screening_context import (
    DEFAULT_EQUITY_SCREENING_CONTEXT,
    normalize_screening_context,
    screening_context_label_tr,
)
from services.participation_intelligence_contract import (
    ASSET_KIND_EQUITY,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    ParticipationAssessment,
)
from services.participation_intelligence_service import (
    build_combined_methodology_assessment,
    build_methodology_assessment_from_financial_screen,
    build_unknown_assessment,
)
from services.participation_methodology_registry import (
    get_default_equity_methodology_id,
    get_methodology,
)
from services.participation_sec_input_resolver import (
    build_participation_inputs_from_sec,
)
from services.sec_financial_client import SECFinancialClient, SECFinancialError

BUSINESS_ACTIVITY_UNAVAILABLE_WARNING = (
    "Faaliyet alanı kanıtı sağlanmadı; iş faaliyeti taraması uygulanmadı."
)

DEFAULT_MISSING_CAPABILITIES: Tuple[str, ...] = (
    "business_activity_screening",
    "prohibited_revenue_inference",
    "historical_market_cap_24m",
    "historical_market_value_equity_36m",
    "assessment_persistence",
)


@dataclass(frozen=True)
class ParticipationAssessmentResult:
    symbol: str
    methodology_id: Optional[str]
    resolved_methodology_version: Optional[str]
    participation_assessment: ParticipationAssessment
    financial_screen_result: Optional[ParticipationFinancialScreenResult] = None
    financial_inputs: Optional[ParticipationFinancialInputs] = None
    business_screen_result: Optional[BusinessActivityScreenResult] = None
    source_evidence: Tuple[Tuple[str, str], ...] = field(default_factory=tuple)
    warnings: Tuple[str, ...] = field(default_factory=tuple)
    errors: Tuple[str, ...] = field(default_factory=tuple)
    provider_status: Tuple[Tuple[str, str], ...] = field(default_factory=tuple)
    sec_available: bool = False
    used_market_capitalization: Optional[float] = None
    missing_capabilities: Tuple[str, ...] = DEFAULT_MISSING_CAPABILITIES
    assessment_completeness: Any = None
    participation_provider_calls: Dict[str, int] = field(default_factory=dict)
    screening_context: str = DEFAULT_EQUITY_SCREENING_CONTEXT

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "symbol": self.symbol,
            "methodology_id": self.methodology_id,
            "resolved_methodology_version": self.resolved_methodology_version,
            "screening_context": self.screening_context,
            "participation_assessment": self.participation_assessment.to_dict(),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "provider_status": dict(self.provider_status),
            "sec_available": self.sec_available,
            "used_market_capitalization": self.used_market_capitalization,
            "missing_capabilities": list(self.missing_capabilities),
            "participation_provider_calls": dict(self.participation_provider_calls),
        }
        if self.assessment_completeness is not None:
            payload["assessment_completeness"] = self.assessment_completeness.to_dict()
        if self.financial_screen_result is not None:
            payload["financial_screen_result"] = (
                self.financial_screen_result.to_dict()
            )
        if self.financial_inputs is not None:
            payload["financial_inputs"] = self.financial_inputs.to_dict()
        if self.business_screen_result is not None:
            payload["business_screen_result"] = self.business_screen_result.to_dict()
        payload["source_evidence"] = dict(self.source_evidence)
        return payload


def _normalize_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper()


def _normalize_cik(cik: Optional[str | int]) -> Optional[str]:
    if cik is None:
        return None
    text = str(cik).strip()
    return text or None


def _resolve_methodology_id(methodology_id: Optional[str]) -> tuple[Optional[str], tuple[str, ...]]:
    if methodology_id is not None:
        normalized = str(methodology_id).strip()
        if not normalized:
            return None, ("Methodology id is empty.",)
        if get_methodology(normalized) is None:
            return None, (f"Unknown methodology_id: {normalized}",)
        return normalized, ()
    return get_default_equity_methodology_id(), ()


def _orchestration_confidence(
    *,
    sec_available: bool,
    financial_screen: Optional[ParticipationFinancialScreenResult],
    business_screen: Optional[BusinessActivityScreenResult] = None,
) -> str:
    if not sec_available:
        return CONFIDENCE_LOW
    financial_medium = (
        financial_screen is not None and financial_screen.financial_rules_evaluated
    )
    business_medium = (
        business_screen is not None and business_screen.business_rules_evaluated
    )
    if financial_medium or business_medium:
        if business_screen is not None and not business_medium and not financial_medium:
            return CONFIDENCE_LOW
        if financial_screen is not None and not financial_medium and not business_medium:
            return CONFIDENCE_LOW
        if business_screen is not None and financial_screen is not None:
            if not financial_medium or not business_medium:
                return CONFIDENCE_LOW
        return CONFIDENCE_MEDIUM
    return CONFIDENCE_LOW


def _missing_capabilities_for_result(
    *,
    methodology_id: Optional[str],
    business_evidence_provided: bool,
    business_screen: Optional[BusinessActivityScreenResult],
    financial_inputs: Optional[ParticipationFinancialInputs] = None,
    evidence_bundle: Any = None,
    persistence_available: bool = False,
) -> Tuple[str, ...]:
    if methodology_id is None:
        return (
            "business_activity_screening",
            "prohibited_revenue_inference",
            "historical_market_cap_24m",
            "historical_market_value_equity_36m",
        )
    return blocking_missing_capabilities(
        methodology_id,
        financial_inputs=financial_inputs,
        business_screen=business_screen,
        business_evidence_provided=business_evidence_provided,
    )


def _append_business_unavailable_warning(
    assessment: ParticipationAssessment,
) -> ParticipationAssessment:
    warnings = tuple(
        dict.fromkeys((*assessment.warnings, BUSINESS_ACTIVITY_UNAVAILABLE_WARNING))
    )
    return replace(assessment, warnings=warnings)


def _unknown_equity_result(
    symbol: str,
    *,
    methodology_id: Optional[str],
    resolved_methodology_version: Optional[str],
    warnings: Tuple[str, ...],
    errors: Tuple[str, ...],
    provider_status: Tuple[Tuple[str, str], ...],
    sec_available: bool,
    used_market_capitalization: Optional[float],
) -> ParticipationAssessmentResult:
    assessment = build_unknown_assessment(symbol, asset_kind=ASSET_KIND_EQUITY)
    if methodology_id is not None:
        assessment = replace(
            assessment,
            methodology_id=methodology_id,
            methodology_version=resolved_methodology_version,
        )
    return ParticipationAssessmentResult(
        symbol=_normalize_symbol(symbol),
        methodology_id=methodology_id,
        resolved_methodology_version=resolved_methodology_version,
        participation_assessment=assessment,
        warnings=warnings,
        errors=errors,
        provider_status=provider_status,
        sec_available=sec_available,
        used_market_capitalization=used_market_capitalization,
    )


def assess_equity_participation(
    symbol: str,
    *,
    methodology_id: Optional[str] = None,
    sec_client: Optional[SECFinancialClient] = None,
    cik: Optional[str | int] = None,
    market_capitalization: Optional[float] = None,
    business_evidence: Optional[BusinessActivityEvidence] = None,
    sec_financials: Optional[dict[str, Any]] = None,
    fmp_client: Any = None,
    persistence_available: bool = False,
    screening_context: Optional[str] = None,
) -> ParticipationAssessmentResult:
    normalized_symbol = _normalize_symbol(symbol)
    normalized_cik = _normalize_cik(cik)
    resolved_screening_context = normalize_screening_context(
        screening_context or DEFAULT_EQUITY_SCREENING_CONTEXT
    )
    resolved_methodology_id, methodology_errors = _resolve_methodology_id(methodology_id)

    if resolved_methodology_id is None:
        return _unknown_equity_result(
            normalized_symbol,
            methodology_id=methodology_id,
            resolved_methodology_version=None,
            warnings=(),
            errors=methodology_errors,
            provider_status=(("sec", "skipped"),),
            sec_available=False,
            used_market_capitalization=market_capitalization,
        )

    methodology = get_methodology(resolved_methodology_id)
    resolved_version = methodology.version if methodology else None

    sec_financials_payload: dict[str, Any] = {}
    sec_company_facts_payload: Optional[dict[str, Any]] = None
    sec_warnings: list[str] = []
    sec_errors: list[str] = []
    sec_available = False
    provider_status: list[tuple[str, str]] = [("sec", "skipped")]

    if sec_financials is not None:
        sec_financials_payload = dict(sec_financials)
        sec_available = True
        provider_status[0] = ("sec", "provided")
    elif normalized_cik is None or sec_client is None:
        warnings = (
            "CIK sağlanmadı; SEC finansal verisi kullanılamadı."
            if normalized_cik is None
            else "SEC istemcisi sağlanmadı; SEC finansal verisi kullanılamadı."
        ),
        return _unknown_equity_result(
            normalized_symbol,
            methodology_id=resolved_methodology_id,
            resolved_methodology_version=resolved_version,
            warnings=warnings,
            errors=(),
            provider_status=(("sec", "skipped"),),
            sec_available=False,
            used_market_capitalization=market_capitalization,
        )
    else:
        provider_status[0] = ("sec", "attempted")
        try:
            payload = sec_client.company_facts(normalized_cik)
            sec_company_facts_payload = payload
            sec_financials_payload = sec_client.extract_financials(payload)
            sec_available = True
            provider_status[0] = ("sec", "ok")
        except SECFinancialError as exc:
            sec_errors.append(str(exc))
            provider_status[0] = ("sec", "error")
            sec_warnings.append("SEC finansal verisi alınamadı.")
        except (TypeError, ValueError) as exc:
            sec_errors.append(f"SEC payload is malformed: {exc}")
            provider_status[0] = ("sec", "malformed")
            sec_warnings.append("SEC finansal verisi çözümlenemedi.")

    input_resolution = build_participation_inputs_from_sec(
        normalized_symbol,
        sec_financials_payload,
        market_capitalization=market_capitalization,
        cik=normalized_cik,
    )
    financial_inputs = input_resolution.inputs

    business_rules = get_methodology_business_rules(resolved_methodology_id)
    prohibited_categories = business_rules.prohibited_categories if business_rules else ()

    evidence_bundle = load_participation_evidence_bundle(
        normalized_symbol,
        fmp_client=fmp_client,
        sec_client=sec_client,
        cik=normalized_cik,
        sec_company_facts_payload=sec_company_facts_payload,
        sec_financials=sec_financials_payload,
        prohibited_categories=prohibited_categories,
    )
    provider_calls = dict(evidence_bundle.provider_calls)
    evidence_warnings = list(evidence_bundle.warnings)

    if business_evidence is None:
        business_evidence = enrich_business_activity_evidence(
            {"symbol": normalized_symbol},
            sec_metadata=evidence_bundle.sec_metadata,
            fmp_profile=evidence_bundle.fmp_profile,
            revenue_segments=evidence_bundle.revenue_segments,
            reported_total_revenue=financial_inputs.total_revenue,
        )
    else:
        business_evidence = enrich_business_activity_evidence(
            {
                "symbol": normalized_symbol,
                "company_name": business_evidence.company_name,
                "sector_theme": business_evidence.sector,
                "industry": business_evidence.industry,
                "sic_code": business_evidence.sic_code,
                "sic_description": business_evidence.sic_description,
                "notes": business_evidence.business_description,
            },
            sec_metadata=evidence_bundle.sec_metadata,
            fmp_profile=evidence_bundle.fmp_profile,
            revenue_segments=merge_revenue_segment_sources(
                evidence_bundle.revenue_segments,
                business_evidence.revenue_segments,
            ),
            reported_total_revenue=financial_inputs.total_revenue,
        )

    non_permissible_revenue, revenue_warnings = derive_non_permissible_revenue_amount(
        financial_inputs.total_revenue,
        business_evidence.revenue_segments,
        methodology_id=resolved_methodology_id,
        business_evidence=business_evidence,
    )
    profile_market_cap = None
    if evidence_bundle.fmp_profile:
        try:
            profile_market_cap = float(
                evidence_bundle.fmp_profile.get("marketCap")
                or evidence_bundle.fmp_profile.get("mktCap")
                or 0
            ) or None
        except (TypeError, ValueError):
            profile_market_cap = None

    financial_inputs = merge_participation_financial_inputs(
        financial_inputs,
        evidence_bundle=evidence_bundle,
        non_permissible_revenue=non_permissible_revenue,
        market_capitalization=market_capitalization or profile_market_cap,
    )

    financial_screen = evaluate_financial_rules(
        resolved_methodology_id,
        financial_inputs,
        screening_context=resolved_screening_context,
        methodology_version=resolved_version,
    )
    business_screen: BusinessActivityScreenResult | None = None
    if business_evidence is not None:
        business_screen = evaluate_business_activity(
            resolved_methodology_id,
            business_evidence,
        )

    if business_screen is not None:
        assessment = build_combined_methodology_assessment(
            financial_screen,
            business_screen,
            asset_kind=ASSET_KIND_EQUITY,
        )
    else:
        assessment = build_methodology_assessment_from_financial_screen(
            financial_screen,
            asset_kind=ASSET_KIND_EQUITY,
        )
        assessment = _append_business_unavailable_warning(assessment)

    assessment = replace(
        assessment,
        confidence=_orchestration_confidence(
            sec_available=sec_available,
            financial_screen=financial_screen,
            business_screen=business_screen,
        ),
    )

    warnings = merge_warning_messages(
        sec_warnings,
        input_resolution.warnings,
        evidence_warnings,
        revenue_warnings,
        financial_screen.warnings,
        business_screen.warnings if business_screen is not None else (),
        assessment.warnings,
    )

    missing_capabilities = _missing_capabilities_for_result(
        methodology_id=resolved_methodology_id,
        business_evidence_provided=business_evidence is not None,
        business_screen=business_screen,
        financial_inputs=financial_inputs,
        evidence_bundle=evidence_bundle,
        persistence_available=persistence_available,
    )
    completeness = build_assessment_completeness(
        ParticipationAssessmentResult(
            symbol=normalized_symbol,
            methodology_id=resolved_methodology_id,
            resolved_methodology_version=resolved_version,
            participation_assessment=assessment,
            financial_screen_result=financial_screen,
            financial_inputs=financial_inputs,
            business_screen_result=business_screen,
            missing_capabilities=missing_capabilities,
        )
    )

    return ParticipationAssessmentResult(
        symbol=normalized_symbol,
        methodology_id=resolved_methodology_id,
        resolved_methodology_version=resolved_version,
        participation_assessment=assessment,
        financial_screen_result=financial_screen,
        financial_inputs=financial_inputs,
        business_screen_result=business_screen,
        source_evidence=financial_inputs.source_evidence,
        warnings=warnings,
        errors=tuple(sec_errors),
        provider_status=tuple(provider_status),
        sec_available=sec_available,
        used_market_capitalization=market_capitalization or profile_market_cap,
        missing_capabilities=missing_capabilities,
        assessment_completeness=completeness,
        participation_provider_calls=provider_calls,
        screening_context=resolved_screening_context,
    )
