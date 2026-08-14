from __future__ import annotations

from typing import Any, Mapping, Optional

from services.company_report_participation_service import (
    CompanyReportParticipationView,
    build_company_report_participation,
)
from services.participation_assessment_service import ParticipationAssessmentResult
from services.participation_intelligence_contract import (
    METHODOLOGY_COMPLETENESS_COMPLETE,
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
    RULE_OUTCOME_INSUFFICIENT_DATA,
)
from services.research_eligibility_contract import (
    REASON_PARTICIPATION_ASSESSMENT_ERROR,
    REASON_PARTICIPATION_ASSESSMENT_UNAVAILABLE,
    REASON_PARTICIPATION_COMPLIANT,
    REASON_PARTICIPATION_INSUFFICIENT_EVIDENCE,
    REASON_PARTICIPATION_NON_COMPLIANT,
    REASON_PARTICIPATION_UNVERIFIED,
    REASON_RESEARCH_GATE_MISSING,
    RESEARCH_STATUS_ERROR,
    RESEARCH_STATUS_FAIL,
    RESEARCH_STATUS_INSUFFICIENT_DATA,
    RESEARCH_STATUS_PASS,
    RESEARCH_STATUS_UNKNOWN,
    ResearchEligibilityResult,
)
from services.sec_financial_client import SECFinancialClient


class ResearchEligibilityBlockedError(Exception):
    def __init__(self, eligibility: ResearchEligibilityResult) -> None:
        self.eligibility = eligibility
        super().__init__(eligibility.block_message)


def _insufficient_evidence_reasons(result: ParticipationAssessmentResult) -> tuple[str, ...]:
    reasons: list[str] = []
    if not result.sec_available:
        reasons.append("sec_unavailable")
    assessment = result.participation_assessment
    if assessment.methodology_completeness != METHODOLOGY_COMPLETENESS_COMPLETE:
        reasons.append("methodology_incomplete")
    for screen in assessment.financial_screens:
        if screen.outcome == RULE_OUTCOME_INSUFFICIENT_DATA:
            reasons.append(f"financial_rule_insufficient:{screen.rule_id}")
    if assessment.business_activity is not None:
        if assessment.business_activity.outcome == RULE_OUTCOME_INSUFFICIENT_DATA:
            reasons.append("business_rule_insufficient")
    return tuple(reasons)


def evaluate_research_eligibility_from_assessment(
    result: Optional[ParticipationAssessmentResult],
    *,
    symbol: str = "",
) -> ResearchEligibilityResult:
    normalized = str(symbol or (result.symbol if result else "")).strip().upper()
    if result is None:
        return ResearchEligibilityResult(
            symbol=normalized,
            status=RESEARCH_STATUS_ERROR,
            research_allowed=False,
            participation_status="",
            reason_codes=(REASON_PARTICIPATION_ASSESSMENT_UNAVAILABLE,),
            limitations=("Katılım değerlendirmesi mevcut değil.",),
            provenance=(("gate", "participation_assessment"),),
        )

    assessment = result.participation_assessment
    status = assessment.status
    provenance = (
        ("gate", "participation_assessment"),
        ("methodology_id", str(result.methodology_id or "")),
        ("confidence", assessment.confidence),
    )

    if result.errors:
        return ResearchEligibilityResult(
            symbol=normalized,
            status=RESEARCH_STATUS_ERROR,
            research_allowed=False,
            participation_status=status,
            reason_codes=(REASON_PARTICIPATION_ASSESSMENT_ERROR,),
            limitations=tuple(result.errors),
            provenance=provenance,
        )

    if status == PARTICIPATION_STATUS_UYGUN:
        return ResearchEligibilityResult(
            symbol=normalized,
            status=RESEARCH_STATUS_PASS,
            research_allowed=True,
            participation_status=status,
            reason_codes=(REASON_PARTICIPATION_COMPLIANT,),
            limitations=tuple(result.warnings),
            provenance=provenance,
        )

    if status == PARTICIPATION_STATUS_UYGUN_DEGIL:
        return ResearchEligibilityResult(
            symbol=normalized,
            status=RESEARCH_STATUS_FAIL,
            research_allowed=False,
            participation_status=status,
            reason_codes=(REASON_PARTICIPATION_NON_COMPLIANT,),
            limitations=tuple(result.warnings),
            provenance=provenance,
        )

    insufficient_reasons = _insufficient_evidence_reasons(result)
    if insufficient_reasons or not result.sec_available:
        limitations = list(result.warnings)
        if not result.sec_available:
            limitations.append("SEC finansal verisi kullanılamadı.")
        if result.missing_capabilities:
            limitations.append(
                "Eksik kanıt alanları: "
                + ", ".join(result.missing_capabilities[:4])
            )
        return ResearchEligibilityResult(
            symbol=normalized,
            status=RESEARCH_STATUS_INSUFFICIENT_DATA,
            research_allowed=False,
            participation_status=status,
            reason_codes=(REASON_PARTICIPATION_INSUFFICIENT_EVIDENCE, *insufficient_reasons),
            limitations=tuple(dict.fromkeys(limitations)),
            provenance=provenance,
        )

    if status == PARTICIPATION_STATUS_KONTROL_ET:
        return ResearchEligibilityResult(
            symbol=normalized,
            status=RESEARCH_STATUS_UNKNOWN,
            research_allowed=False,
            participation_status=status,
            reason_codes=(REASON_PARTICIPATION_UNVERIFIED,),
            limitations=tuple(result.warnings),
            provenance=provenance,
        )

    return ResearchEligibilityResult(
        symbol=normalized,
        status=RESEARCH_STATUS_UNKNOWN,
        research_allowed=False,
        participation_status=status,
        reason_codes=(REASON_PARTICIPATION_UNVERIFIED,),
        limitations=tuple(result.warnings),
        provenance=provenance,
    )


def evaluate_research_eligibility_from_participation_view(
    view: CompanyReportParticipationView,
) -> ResearchEligibilityResult:
    normalized = str(view.symbol or "").strip().upper()
    if not view.available:
        return ResearchEligibilityResult(
            symbol=normalized,
            status=RESEARCH_STATUS_ERROR,
            research_allowed=False,
            participation_status="",
            reason_codes=(REASON_PARTICIPATION_ASSESSMENT_UNAVAILABLE,),
            limitations=(view.error_message or "Katılım değerlendirmesi kullanılamıyor.",),
            provenance=(("gate", "company_report_participation"),),
        )
    return evaluate_research_eligibility_from_assessment(
        view.result,
        symbol=normalized,
    )


def evaluate_research_eligibility_for_candidate(
    candidate: Mapping[str, Any],
    *,
    sec_client: Optional[SECFinancialClient] = None,
    methodology_id: Optional[str] = None,
    sec_financials: Optional[dict[str, Any]] = None,
    fmp_client: Any = None,
    persistence_available: bool = False,
) -> ResearchEligibilityResult:
    view = build_company_report_participation(
        candidate,
        sec_client=sec_client,
        methodology_id=methodology_id,
        sec_financials=sec_financials,
        fmp_client=fmp_client,
        persistence_available=persistence_available,
    )
    return evaluate_research_eligibility_from_participation_view(view)


def research_eligibility_pass_fixture(symbol: str = "TEST") -> ResearchEligibilityResult:
    normalized = str(symbol or "TEST").strip().upper()
    return ResearchEligibilityResult(
        symbol=normalized,
        status=RESEARCH_STATUS_PASS,
        research_allowed=True,
        participation_status=PARTICIPATION_STATUS_UYGUN,
        reason_codes=(REASON_PARTICIPATION_COMPLIANT,),
        limitations=(),
        provenance=(("gate", "test_fixture"),),
    )


def require_research_allowed(
    eligibility: Optional[ResearchEligibilityResult],
    *,
    symbol: str = "",
) -> ResearchEligibilityResult:
    if eligibility is None:
        blocked = ResearchEligibilityResult(
            symbol=str(symbol or "").strip().upper(),
            status=RESEARCH_STATUS_ERROR,
            research_allowed=False,
            participation_status="",
            reason_codes=(REASON_RESEARCH_GATE_MISSING,),
            limitations=("Araştırma uygunluk kapısı doğrulanmadı.",),
            provenance=(("gate", "missing"),),
        )
        raise ResearchEligibilityBlockedError(blocked)
    if not eligibility.research_allowed:
        raise ResearchEligibilityBlockedError(eligibility)
    return eligibility
