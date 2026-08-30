"""Read-only official BIST Participation evidence. No production verdict."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from services.bist_katilim_tum_contract import BistKatilimMembership
from services.kap_kafif_contract import KapKafifDocument


EVIDENCE_OFFICIAL_ELIGIBILITY = "OFFICIAL_ELIGIBILITY_EVIDENCE"
EVIDENCE_INCOMPLETE = "OFFICIAL_EVIDENCE_INCOMPLETE"
EVIDENCE_UNAVAILABLE = "OFFICIAL_EVIDENCE_UNAVAILABLE"

SHADOW_METHODOLOGY_DECISION_REQUIRED = "METHODOLOGY_DECISION_REQUIRED"
SHADOW_INSUFFICIENT = "INSUFFICIENT_OFFICIAL_EVIDENCE"
SHADOW_IDENTITY_REJECTED = "IDENTITY_REJECTED"
SHADOW_NOT_COMPUTED = "NABI_PARTICIPATION_NOT_COMPUTED"

PERIOD_COMPARABLE = "COMPARABLE"
PERIOD_MISMATCH = "PERIOD_MISMATCH"
PERIOD_UNKNOWN = "PERIOD_UNKNOWN"

LIMITATION_READ_ONLY = "READINESS_ONLY_NO_PARTICIPATION_VERDICT"


@dataclass(frozen=True)
class BistOfficialParticipationEvidence:
    symbol: str
    identity_source: str
    membership: Optional[BistKatilimMembership]
    kafif: Optional[KapKafifDocument]
    official_eligibility: str
    kafif_evidence_complete: bool
    nabi_participation_shadow: str
    period_vs_financial_report: str
    financial_report_period: str = ""
    limitation: str = LIMITATION_READ_ONLY
    persisted: bool = False
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "identity_source": self.identity_source,
            "membership": self.membership.to_dict() if self.membership else None,
            "kafif": self.kafif.to_dict() if self.kafif else None,
            "official_eligibility": self.official_eligibility,
            "kafif_evidence_complete": self.kafif_evidence_complete,
            "nabi_participation_shadow": self.nabi_participation_shadow,
            "period_vs_financial_report": self.period_vs_financial_report,
            "financial_report_period": self.financial_report_period,
            "limitation": self.limitation,
            "persisted": self.persisted,
            "provenance": dict(self.provenance or {}),
        }


@dataclass(frozen=True)
class BistKatilimUniverseAudit:
    member_count: int
    matched_security_master: tuple[str, ...]
    unmatched_symbols: tuple[str, ...]
    normalization_issues: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "member_count": self.member_count,
            "matched_security_master": list(self.matched_security_master),
            "unmatched_symbols": list(self.unmatched_symbols),
            "normalization_issues": list(self.normalization_issues),
        }
