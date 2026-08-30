from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Dict, Mapping, Optional, Tuple

PARTICIPATION_STATUS_UYGUN = "Uygun"
PARTICIPATION_STATUS_KONTROL_ET = "Kontrol Et"
PARTICIPATION_STATUS_UYGUN_DEGIL = "Uygun Değil"

RULE_OUTCOME_PASS = "PASS"
RULE_OUTCOME_FAIL = "FAIL"
RULE_OUTCOME_REVIEW_REQUIRED = "REVIEW_REQUIRED"
RULE_OUTCOME_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

CONFIDENCE_HIGH = "HIGH"
CONFIDENCE_MEDIUM = "MEDIUM"
CONFIDENCE_LOW = "LOW"

PARTICIPATION_SOURCE_CONFIGURED = "configured"
PARTICIPATION_SOURCE_MANUAL = "manual"
PARTICIPATION_SOURCE_METHODOLOGY = "methodology"
PARTICIPATION_SOURCE_ISSUER_METHODOLOGY = "issuer_methodology"
PARTICIPATION_SOURCE_HOLDINGS_DERIVED = "holdings_derived"
PARTICIPATION_SOURCE_NABI_LOOKTHROUGH = "nabi_lookthrough"
PARTICIPATION_SOURCE_PROVIDER = "provider"
PARTICIPATION_SOURCE_BIST_OFFICIAL = "bist_official"
PARTICIPATION_SOURCE_UNKNOWN = "unknown"

# Distinct from MSCI/SEC-derived methodology and from configured/manual evidence.
AUTHORITY_BIST_OFFICIAL = "BIST_OFFICIAL"
AUTHORITY_MSCI = "MSCI"
AUTHORITY_SEC_DERIVED = "SEC_DERIVED"
AUTHORITY_MANUAL = "MANUAL"
AUTHORITY_EXTERNAL = "EXTERNAL"

ASSET_KIND_EQUITY = "equity"
ASSET_KIND_FUND = "fund"

METHODOLOGY_COMPLETENESS_NOT_APPLICABLE = "not_applicable"
METHODOLOGY_COMPLETENESS_NONE = "none"
METHODOLOGY_COMPLETENESS_PARTIAL = "partial"
METHODOLOGY_COMPLETENESS_COMPLETE = "complete"

PARTICIPATION_DISCLAIMER_FULL = (
    "NABI Scout bir dinî otorite değildir; bu sonuç Şeriat uygunluk sertifikası, "
    "fetva veya dini hüküm değildir. Gösterilen bilgi, belirtilen kaynak ve "
    "metodoloji kapsamındaki otomatik tarama veya yapılandırılmış metadata'dır."
)

PARTICIPATION_DISCLAIMER_SHORT = (
    "Bu bilgi bağımsız NABI Şeriat uygunluk doğrulaması değildir."
)


@dataclass(frozen=True)
class ParticipationRuleResult:
    rule_id: str
    outcome: str = RULE_OUTCOME_INSUFFICIENT_DATA
    methodology_id: Optional[str] = None
    methodology_version: Optional[str] = None
    numerator_definition: Optional[str] = None
    numerator_raw_value: Optional[float] = None
    denominator_definition: Optional[str] = None
    denominator_raw_value: Optional[float] = None
    ratio_pct: Optional[float] = None
    threshold_pct: Optional[float] = None
    comparator: Optional[str] = None
    measurement_period: Optional[str] = None
    source_dates: Tuple[Tuple[str, str], ...] = field(default_factory=tuple)
    evidence_refs: Tuple[str, ...] = field(default_factory=tuple)
    metric_source: Optional[str] = None
    metric_source_fields: Tuple[str, ...] = field(default_factory=tuple)
    warnings: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["source_dates"] = dict(self.source_dates)
        return payload


@dataclass(frozen=True)
class ParticipationAssessment:
    symbol: str
    asset_kind: str
    status: str
    source: str
    confidence: str
    methodology_id: Optional[str] = None
    methodology_version: Optional[str] = None
    methodology_label: Optional[str] = None
    as_of_date: Optional[date] = None
    business_activity: Optional[ParticipationRuleResult] = None
    financial_screens: Tuple[ParticipationRuleResult, ...] = field(default_factory=tuple)
    data_completeness_pct: Optional[float] = None
    holdings_coverage_pct: Optional[float] = None
    freshness_label: Optional[str] = None
    methodology_completeness: str = METHODOLOGY_COMPLETENESS_NONE
    warnings: Tuple[str, ...] = field(default_factory=tuple)
    evidence: Mapping[str, Any] = field(default_factory=dict)
    disclaimer: str = PARTICIPATION_DISCLAIMER_FULL

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "symbol": self.symbol,
            "asset_kind": self.asset_kind,
            "status": self.status,
            "source": self.source,
            "confidence": self.confidence,
            "methodology_id": self.methodology_id,
            "methodology_version": self.methodology_version,
            "methodology_label": self.methodology_label,
            "as_of_date": self.as_of_date.isoformat() if self.as_of_date else None,
            "data_completeness_pct": self.data_completeness_pct,
            "holdings_coverage_pct": self.holdings_coverage_pct,
            "freshness_label": self.freshness_label,
            "methodology_completeness": self.methodology_completeness,
            "warnings": list(self.warnings),
            "evidence": dict(self.evidence),
            "disclaimer": self.disclaimer,
            "financial_screens": [
                screen.to_dict() for screen in self.financial_screens
            ],
        }
        if self.business_activity is not None:
            payload["business_activity"] = self.business_activity.to_dict()
        return payload

    def has_methodology_result(self) -> bool:
        return self.source == PARTICIPATION_SOURCE_METHODOLOGY and bool(
            self.methodology_id
        )

    def is_configured_only(self) -> bool:
        return self.source == PARTICIPATION_SOURCE_CONFIGURED

    def is_bist_official(self) -> bool:
        return self.source == PARTICIPATION_SOURCE_BIST_OFFICIAL

    def requires_review(self) -> bool:
        if self.status == PARTICIPATION_STATUS_KONTROL_ET:
            return True
        screens = list(self.financial_screens)
        if self.business_activity is not None:
            screens.append(self.business_activity)
        return any(
            screen.outcome in {
                RULE_OUTCOME_REVIEW_REQUIRED,
                RULE_OUTCOME_INSUFFICIENT_DATA,
            }
            for screen in screens
        )
