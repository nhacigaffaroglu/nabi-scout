from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Tuple

RESEARCH_STATUS_PASS = "PASS"
RESEARCH_STATUS_FAIL = "FAIL"
RESEARCH_STATUS_UNKNOWN = "UNKNOWN"
RESEARCH_STATUS_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
RESEARCH_STATUS_ERROR = "ERROR"

REASON_PARTICIPATION_COMPLIANT = "participation_compliant"
REASON_PARTICIPATION_NON_COMPLIANT = "participation_non_compliant"
REASON_PARTICIPATION_UNVERIFIED = "participation_unverified"
REASON_PARTICIPATION_INSUFFICIENT_EVIDENCE = "participation_insufficient_evidence"
REASON_PARTICIPATION_ASSESSMENT_ERROR = "participation_assessment_error"
REASON_PARTICIPATION_ASSESSMENT_UNAVAILABLE = "participation_assessment_unavailable"
REASON_RESEARCH_GATE_MISSING = "research_gate_missing"


@dataclass(frozen=True)
class ResearchEligibilityResult:
    symbol: str
    status: str
    research_allowed: bool
    participation_status: str
    reason_codes: Tuple[str, ...] = field(default_factory=tuple)
    limitations: Tuple[str, ...] = field(default_factory=tuple)
    provenance: Tuple[Tuple[str, str], ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["provenance"] = dict(self.provenance)
        return payload

    @property
    def block_message(self) -> str:
        if self.status == RESEARCH_STATUS_FAIL:
            return (
                "Bu yatırım aracı katılım kriterlerini karşılamadığı için "
                "NABI araştırma süreci başlatılmadı."
            )
        if self.status in {RESEARCH_STATUS_UNKNOWN, RESEARCH_STATUS_INSUFFICIENT_DATA}:
            return (
                "Katılım uygunluğu doğrulanamadığı için araştırma başlatılmadı."
            )
        return "Katılım uygunluğu doğrulanamadığı için araştırma başlatılmadı."
