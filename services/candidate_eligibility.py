from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from services.candidate_contract import (
    CandidateEligibility,
    ELIGIBILITY_ELIGIBLE,
    ELIGIBILITY_INELIGIBLE,
    ELIGIBILITY_WATCH_ONLY,
)

PROTECTED_BLOCKERS = frozenset({
    "YBF_MISSING",
    "MANDATE_UNRESOLVED",
    "GOVERNANCE_NOT_CONFIRMED",
    "GOVERNANCE_EVIDENCE_MISSING",
    "KAP_GOVERNANCE_EVIDENCE_MISSING",
    "MATERIAL_CONTRADICTION",
    "HOLDINGS_MISSING",
    "EVIDENCE_STALE",
    "PDR_RECONCILIATION_FAILED",
    "PDR_PARSE_INCOMPLETE",
    "PDR_MISSING",
})

SCANNER_READY = "READY"
PARTICIPATION_UYGUN = "Uygun"


@dataclass(frozen=True)
class CandidateEligibilityInput:
    scanner_status: str
    participation_status: Optional[str]
    research_allowed: bool
    intelligence_publishable: bool
    economic_exposure_known: bool
    analysis_snapshot_id: str
    missing_evidence: tuple[str, ...] = ()
    required_evidence_fresh: bool = True


def evaluate_candidate_eligibility(
    row: CandidateEligibilityInput,
) -> CandidateEligibility:
    reasons: list[str] = []

    if not row.analysis_snapshot_id:
        reasons.append("ANALYSIS_SNAPSHOT_MISSING")
    if row.participation_status != PARTICIPATION_UYGUN:
        reasons.append("PARTICIPATION_NOT_UYGUN")
    if not row.research_allowed:
        reasons.append("RESEARCH_NOT_ALLOWED")
    if row.scanner_status != SCANNER_READY:
        reasons.append("SCANNER_NOT_READY")
    if not row.intelligence_publishable:
        reasons.append("INTELLIGENCE_NOT_PUBLISHABLE")
    if not row.economic_exposure_known:
        reasons.append("ECONOMIC_EXPOSURE_UNKNOWN")
    if not row.required_evidence_fresh:
        reasons.append("REQUIRED_EVIDENCE_STALE")

    reasons.extend(sorted(PROTECTED_BLOCKERS.intersection(row.missing_evidence)))
    reasons = list(dict.fromkeys(reasons))

    if reasons:
        if (
            row.participation_status == PARTICIPATION_UYGUN
            and row.research_allowed
            and row.analysis_snapshot_id
        ):
            return CandidateEligibility(
                status=ELIGIBILITY_WATCH_ONLY,
                reasons=tuple(reasons),
            )
        return CandidateEligibility(
            status=ELIGIBILITY_INELIGIBLE,
            reasons=tuple(reasons),
        )

    return CandidateEligibility(status=ELIGIBILITY_ELIGIBLE)
