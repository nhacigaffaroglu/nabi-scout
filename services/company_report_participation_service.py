from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Tuple

from services.participation_assessment_service import (
    ParticipationAssessmentResult,
    assess_equity_participation,
)
from services.participation_business_evidence_resolver import (
    build_business_activity_evidence_from_candidate,
)
from services.participation_completeness import (
    build_assessment_completeness,
    translate_missing_capability,
)
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    RULE_OUTCOME_FAIL,
    RULE_OUTCOME_INSUFFICIENT_DATA,
    RULE_OUTCOME_PASS,
    RULE_OUTCOME_REVIEW_REQUIRED,
)
from services.sec_financial_client import SECFinancialClient


@dataclass(frozen=True)
class CompanyReportParticipationView:
    symbol: str
    available: bool
    result: Optional[ParticipationAssessmentResult] = None
    error_message: Optional[str] = None
    financial_screen_summary: str = ""
    business_screen_summary: str = ""
    missing_capabilities: Tuple[str, ...] = field(default_factory=tuple)
    warnings: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "symbol": self.symbol,
            "available": self.available,
            "error_message": self.error_message,
            "financial_screen_summary": self.financial_screen_summary,
            "business_screen_summary": self.business_screen_summary,
            "missing_capabilities": list(self.missing_capabilities),
            "warnings": list(self.warnings),
        }
        if self.result is not None:
            payload["result"] = self.result.to_dict()
        return payload


def _outcome_label(outcome: str) -> str:
    return {
        RULE_OUTCOME_PASS: "Geçti",
        RULE_OUTCOME_FAIL: "Başarısız",
        RULE_OUTCOME_REVIEW_REQUIRED: "İnceleme gerekli",
        RULE_OUTCOME_INSUFFICIENT_DATA: "Yetersiz veri",
    }.get(outcome, outcome)


def _summarize_financial_screen(result: ParticipationAssessmentResult) -> str:
    screen = result.financial_screen_result
    if screen is None:
        return "Finansal oran taraması uygulanmadı."
    evaluated = sum(
        1
        for rule in screen.rule_results
        if rule.outcome in {RULE_OUTCOME_PASS, RULE_OUTCOME_FAIL}
    )
    total = len(screen.rule_results)
    completeness = result.assessment_completeness
    suffix = ""
    if completeness is not None:
        suffix = f" · tamamlanma {completeness.financial_rules_evaluated}/{completeness.financial_rules_total}"
    return (
        f"Genel sonuç: {_outcome_label(screen.overall_outcome)} · "
        f"{evaluated}/{total} kural değerlendirildi{suffix}"
    )


def _summarize_business_screen(result: ParticipationAssessmentResult) -> str:
    screen = result.business_screen_result
    if screen is None:
        return "Faaliyet alanı taraması için kanıt sağlanmadı."
    evaluated = sum(
        1
        for rule in screen.rule_results
        if rule.outcome
        in {RULE_OUTCOME_PASS, RULE_OUTCOME_FAIL, RULE_OUTCOME_REVIEW_REQUIRED}
    )
    return (
        f"Genel sonuç: {_outcome_label(screen.overall_outcome)} · "
        f"{evaluated}/{len(screen.rule_results)} kural değerlendirildi"
    )


def build_company_report_participation(
    candidate: Mapping[str, Any],
    *,
    sec_client: Optional[SECFinancialClient] = None,
    methodology_id: Optional[str] = None,
    sec_financials: Optional[dict[str, Any]] = None,
    fmp_client: Any = None,
    persistence_available: bool = False,
) -> CompanyReportParticipationView:
    symbol = str(candidate.get("symbol") or "").strip().upper()
    if not symbol:
        return CompanyReportParticipationView(
            symbol="",
            available=False,
            error_message="Sembol bulunamadı.",
        )

    try:
        business_evidence = build_business_activity_evidence_from_candidate(candidate)
        assessment_result = assess_equity_participation(
            symbol,
            methodology_id=methodology_id,
            sec_client=sec_client,
            cik=candidate.get("cik"),
            market_capitalization=candidate.get("market_cap"),
            business_evidence=business_evidence,
            sec_financials=sec_financials,
            fmp_client=fmp_client,
            persistence_available=persistence_available,
        )
    except (TypeError, ValueError) as exc:
        return CompanyReportParticipationView(
            symbol=symbol,
            available=False,
            error_message=f"Katılım incelemesi oluşturulamadı: {exc}",
        )

    return CompanyReportParticipationView(
        symbol=symbol,
        available=True,
        result=assessment_result,
        financial_screen_summary=_summarize_financial_screen(assessment_result),
        business_screen_summary=_summarize_business_screen(assessment_result),
        missing_capabilities=assessment_result.missing_capabilities,
        warnings=assessment_result.warnings,
    )


def participation_status_is_final_uygun(view: CompanyReportParticipationView) -> bool:
    if not view.available or view.result is None:
        return False
    return view.result.participation_assessment.status == PARTICIPATION_STATUS_UYGUN


def participation_status_is_review(view: CompanyReportParticipationView) -> bool:
    if not view.available or view.result is None:
        return True
    status = view.result.participation_assessment.status
    return status == PARTICIPATION_STATUS_KONTROL_ET
