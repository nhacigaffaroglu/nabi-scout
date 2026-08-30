"""Official BIST Participation evidence and policy vocabulary.

BIST official evidence stays in participation.bist_official.* and is never
collapsed into participation.msci.* fields. Shadow/read-only: no production writes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from services.bist_katilim_tum_contract import BistKatilimMembership
from services.kap_kafif_contract import KapKafifDocument
from services.participation_intelligence_contract import AUTHORITY_BIST_OFFICIAL


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

LIMITATION_READ_ONLY = "SHADOW_READ_ONLY_NO_PRODUCTION_PERSISTENCE"
LIMITATION_SHADOW = LIMITATION_READ_ONLY

NAMESPACE_BIST_OFFICIAL = "participation.bist_official"
NAMESPACE_MSCI = "participation.msci"

DECISION_AUTHORITY_BIST_OFFICIAL = AUTHORITY_BIST_OFFICIAL

BASIS_MEMBER_COMPLETE_KAFIF = "BIST_KATILIM_TUM_MEMBER_AND_COMPLETE_KAFIF"
BASIS_NOT_LISTED_NOT_NEGATIVE = "NOT_LISTED_ALONE_IS_NOT_UYGUN_DEGIL"
BASIS_KAFIF_MISSING = "KAFIF_MISSING"
BASIS_KAFIF_INCOMPLETE = "KAFIF_INCOMPLETE_OR_AMBIGUOUS"
BASIS_KAFIF_STALE = "KAFIF_PERIOD_NOT_APPLICABLE"
BASIS_SOURCE_UNAVAILABLE = "BORSA_SOURCE_UNAVAILABLE"
BASIS_IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
BASIS_MEMBERSHIP_UNKNOWN = "MEMBERSHIP_UNKNOWN"

METHODOLOGY_NEGATIVE_MAPPING_UNRESOLVED = "METHODOLOGY_NEGATIVE_MAPPING_UNRESOLVED"
FRESHNESS_POLICY_NEEDS_FOLLOWUP = "FRESHNESS_POLICY_NEEDS_FOLLOWUP"
FRESHNESS_LATEST_KNOWN_OFFICIAL = "LATEST_KNOWN_OFFICIAL_KAFIF_PLUS_PERIOD_ALIGNMENT"

WATCHER_COMPARE_FIELDS = (
    "symbol",
    "status",
    "decision_authority",
    "source_membership_state",
    "membership_as_of",
    "source_notification_id",
    "source_period",
    "source_financial_year",
)


@dataclass(frozen=True)
class KafifFailureFieldAudit:
    kafif_field: str
    official_question_or_formula: str
    explicit_official_fail_flag: bool
    safe_for_automatic_uygun_degil: bool
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "kafif_field": self.kafif_field,
            "official_question_or_formula": self.official_question_or_formula,
            "explicit_official_fail_flag": self.explicit_official_fail_flag,
            "safe_for_automatic_uygun_degil": self.safe_for_automatic_uygun_degil,
            "note": self.note,
        }


@dataclass(frozen=True)
class KafifNegativeMappingAudit:
    automatic_uygun_degil_implemented: bool
    methodology_negative_mapping_unresolved: bool
    explicit_safe_failure_fields: tuple[str, ...]
    unresolved_fields: tuple[str, ...]
    fields: tuple[KafifFailureFieldAudit, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "automatic_uygun_degil_implemented": self.automatic_uygun_degil_implemented,
            "methodology_negative_mapping_unresolved": (
                self.methodology_negative_mapping_unresolved
            ),
            "explicit_safe_failure_fields": list(self.explicit_safe_failure_fields),
            "unresolved_fields": list(self.unresolved_fields),
            "fields": [item.to_dict() for item in self.fields],
        }


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
    decision_authority: str = ""
    confidence: str = ""
    decision_basis: str = ""
    explanation: str = ""
    negative_mapping: str = METHODOLOGY_NEGATIVE_MAPPING_UNRESOLVED
    freshness_policy: str = FRESHNESS_POLICY_NEEDS_FOLLOWUP
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
            "decision_authority": self.decision_authority,
            "confidence": self.confidence,
            "decision_basis": self.decision_basis,
            "explanation": self.explanation,
            "negative_mapping": self.negative_mapping,
            "freshness_policy": self.freshness_policy,
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
