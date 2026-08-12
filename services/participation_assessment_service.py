from __future__ import annotations

"""End-to-end equity participation assessment orchestration (Phase 6B.2c).

Composes SEC fetch, input resolution, financial screening, and assessment
composition into a single callable API. Isolated from Scanner, NABI Score,
decision engine, and persistence.

Confidence policy (deterministic, conservative):
- LOW when SEC is unavailable or no meaningful financial rule evaluated
- MEDIUM when SEC succeeded and at least one financial rule reached PASS/FAIL
- HIGH is never assigned in 6B.2c (business-activity screening absent)
"""

from dataclasses import dataclass, field, replace
from typing import Any, Optional, Tuple

from services.participation_financial_contract import (
    ParticipationFinancialInputs,
    ParticipationFinancialScreenResult,
)
from services.participation_financial_engine import evaluate_financial_rules
from services.participation_intelligence_contract import (
    ASSET_KIND_EQUITY,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    ParticipationAssessment,
)
from services.participation_intelligence_service import (
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

BUSINESS_ACTIVITY_WARNING = (
    "Finansal oran taraması tamamlandı; faaliyet alanı taraması bu aşamada uygulanmadı."
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
    source_evidence: Tuple[Tuple[str, str], ...] = field(default_factory=tuple)
    warnings: Tuple[str, ...] = field(default_factory=tuple)
    errors: Tuple[str, ...] = field(default_factory=tuple)
    provider_status: Tuple[Tuple[str, str], ...] = field(default_factory=tuple)
    sec_available: bool = False
    used_market_capitalization: Optional[float] = None
    missing_capabilities: Tuple[str, ...] = DEFAULT_MISSING_CAPABILITIES

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "symbol": self.symbol,
            "methodology_id": self.methodology_id,
            "resolved_methodology_version": self.resolved_methodology_version,
            "participation_assessment": self.participation_assessment.to_dict(),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "provider_status": dict(self.provider_status),
            "sec_available": self.sec_available,
            "used_market_capitalization": self.used_market_capitalization,
            "missing_capabilities": list(self.missing_capabilities),
        }
        if self.financial_screen_result is not None:
            payload["financial_screen_result"] = (
                self.financial_screen_result.to_dict()
            )
        if self.financial_inputs is not None:
            payload["financial_inputs"] = self.financial_inputs.to_dict()
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
) -> str:
    if not sec_available:
        return CONFIDENCE_LOW
    if financial_screen is not None and financial_screen.financial_rules_evaluated:
        return CONFIDENCE_MEDIUM
    return CONFIDENCE_LOW


def _append_business_activity_warning(
    assessment: ParticipationAssessment,
) -> ParticipationAssessment:
    warnings = tuple(dict.fromkeys((*assessment.warnings, BUSINESS_ACTIVITY_WARNING)))
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
) -> ParticipationAssessmentResult:
    normalized_symbol = _normalize_symbol(symbol)
    normalized_cik = _normalize_cik(cik)
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

    if normalized_cik is None or sec_client is None:
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

    sec_financials: dict[str, Any] = {}
    sec_warnings: list[str] = []
    sec_errors: list[str] = []
    sec_available = False
    provider_status: list[tuple[str, str]] = [("sec", "attempted")]

    try:
        payload = sec_client.company_facts(normalized_cik)
        sec_financials = sec_client.extract_financials(payload)
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
        sec_financials,
        market_capitalization=market_capitalization,
        cik=normalized_cik,
    )
    financial_inputs = input_resolution.inputs

    financial_screen = evaluate_financial_rules(
        resolved_methodology_id,
        financial_inputs,
    )
    assessment = build_methodology_assessment_from_financial_screen(
        financial_screen,
        asset_kind=ASSET_KIND_EQUITY,
    )
    assessment = _append_business_activity_warning(assessment)
    assessment = replace(
        assessment,
        confidence=_orchestration_confidence(
            sec_available=sec_available,
            financial_screen=financial_screen,
        ),
    )

    warnings = tuple(
        dict.fromkeys(
            (
                *sec_warnings,
                *input_resolution.warnings,
                *financial_screen.warnings,
                *assessment.warnings,
            )
        )
    )

    return ParticipationAssessmentResult(
        symbol=normalized_symbol,
        methodology_id=resolved_methodology_id,
        resolved_methodology_version=resolved_version,
        participation_assessment=assessment,
        financial_screen_result=financial_screen,
        financial_inputs=financial_inputs,
        source_evidence=financial_inputs.source_evidence,
        warnings=warnings,
        errors=tuple(sec_errors),
        provider_status=tuple(provider_status),
        sec_available=sec_available,
        used_market_capitalization=market_capitalization,
    )
