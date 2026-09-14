"""Deterministic FUND18 portfolio-fit assessment engine.

Consumes structured facts plus the versioned FUND18 policy.
No evidence free-text parsing, ranking, recommendation, allocation,
execution, or persistence is allowed here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from services.turkiye_fund_portfolio_fit_assessment_facts import (
    PortfolioFitAssessmentFacts,
)
from services.turkiye_fund_portfolio_fit_assessment_policy import (
    Fund18AssessmentPolicy,
)


UNKNOWN = "UNKNOWN"

MODE_SIMULATION = "SIMULATION"
MODE_EFFECTIVE = "EFFECTIVE"

VALID_MODES = {
    MODE_SIMULATION,
    MODE_EFFECTIVE,
}

ROLE_STRENGTH = {
    "STRONG": 3,
    "PARTIAL": 2,
    "WEAK": 1,
}


class PortfolioFitAssessmentEngineError(ValueError):
    """Fail-closed assessment-engine contract error."""


@dataclass(frozen=True)
class DimensionAssessment:
    assessment: str
    confidence: str
    rule_id: str | None
    reason_code: str | None
    structured_facts: dict[str, Any]
    evidence_state: str
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        raw["limitations"] = list(self.limitations)
        return raw


@dataclass(frozen=True)
class PortfolioFitAssessmentResult:
    fund_code: str
    policy_version: str
    decision_id: str
    mode: str
    production_effective: bool
    role_fit: DimensionAssessment
    economic_overlap: DimensionAssessment
    diversification_contribution: DimensionAssessment
    concentration_risk: DimensionAssessment

    def to_dict(self) -> dict[str, Any]:
        return {
            "fund_code": self.fund_code,
            "policy_version": self.policy_version,
            "decision_id": self.decision_id,
            "mode": self.mode,
            "production_effective": self.production_effective,
            "role_fit": self.role_fit.to_dict(),
            "economic_overlap": self.economic_overlap.to_dict(),
            "diversification_contribution":
                self.diversification_contribution.to_dict(),
            "concentration_risk":
                self.concentration_risk.to_dict(),
        }


def _unknown(
    *,
    evidence_state: str,
    reason_code: str,
    rule_id: str | None = None,
    structured_facts: dict[str, Any] | None = None,
    limitations: tuple[str, ...] = (),
) -> DimensionAssessment:
    return DimensionAssessment(
        assessment=UNKNOWN,
        confidence=UNKNOWN,
        rule_id=rule_id,
        reason_code=reason_code,
        structured_facts=structured_facts or {},
        evidence_state=evidence_state,
        limitations=limitations,
    )


def _require_supported(
    facts: PortfolioFitAssessmentFacts,
    dimension: str,
) -> str | None:
    state = facts.evidence_states[dimension]

    if state != "SUPPORTED":
        return "EVIDENCE_NOT_SUPPORTED"

    return None


def _role_fit(
    facts: PortfolioFitAssessmentFacts,
    policy: Fund18AssessmentPolicy,
) -> DimensionAssessment:
    state = facts.evidence_states["role_fit"]

    unsupported = _require_supported(facts, "role_fit")
    if unsupported:
        return _unknown(
            evidence_state=state,
            reason_code=unsupported,
        )

    exposure = facts.candidate_primary_exposure
    if not exposure:
        return _unknown(
            evidence_state=state,
            reason_code="CANDIDATE_EXPOSURE_UNAVAILABLE",
        )

    if not facts.desired_roles:
        return _unknown(
            evidence_state=state,
            reason_code="STRUCTURED_FACT_MISSING",
        )

    rules = policy.raw["role_fit"]["rules"]

    matches: list[dict[str, Any]] = []

    for rule in rules:
        if rule["primary_exposure"] != exposure:
            continue
        if rule["desired_role"] not in facts.desired_roles:
            continue
        matches.append(dict(rule))

    if not matches:
        return _unknown(
            evidence_state=state,
            reason_code="POLICY_RULE_NOT_APPLICABLE",
            structured_facts={
                "candidate_primary_exposure": exposure,
                "desired_roles": list(facts.desired_roles),
            },
        )

    best = sorted(
        matches,
        key=lambda r: (
            -ROLE_STRENGTH[r["assessment"]],
            r["rule_id"],
        ),
    )[0]

    confidence = (
        str(facts.candidate_exposure_confidence).upper()
        if facts.candidate_exposure_confidence
        else "MEDIUM"
    )

    if confidence not in {"HIGH", "MEDIUM", "LOW"}:
        confidence = "MEDIUM"

    return DimensionAssessment(
        assessment=best["assessment"],
        confidence=confidence,
        rule_id=best["rule_id"],
        reason_code=None,
        structured_facts={
            "candidate_primary_exposure": exposure,
            "desired_roles": list(facts.desired_roles),
            "matched_role": best["desired_role"],
            "candidate_exposure_as_of":
                facts.candidate_exposure_as_of,
        },
        evidence_state=state,
        limitations=(),
    )


def _interval_for_candidate_bucket(
    facts: PortfolioFitAssessmentFacts,
) -> tuple[float, float] | None:
    exposure = facts.candidate_primary_exposure

    if not exposure:
        return None

    if exposure not in facts.portfolio_bucket_weights:
        return None

    known = facts.portfolio_bucket_weights[exposure]

    unknown = facts.portfolio_unknown_pct
    if unknown is None:
        unknown = 0.0

    upper = min(100.0, known + unknown)

    return known, upper


def _portfolio_confidence(
    facts: PortfolioFitAssessmentFacts,
) -> str:
    completeness = (
        facts.portfolio_completeness or ""
    ).upper()

    if completeness in {
        "COMPLETE",
        "COMPLETE_EXPOSURE",
        "FULL_EXPOSURE",
    }:
        return "HIGH"

    return "MEDIUM"


def _classify_overlap_point(
    value: float,
    *,
    low_upper_exclusive: float,
    medium_upper_inclusive: float,
) -> str:
    if value < low_upper_exclusive:
        return "LOW"

    if value <= medium_upper_inclusive:
        return "MEDIUM"

    return "HIGH"


def _economic_overlap(
    facts: PortfolioFitAssessmentFacts,
    policy: Fund18AssessmentPolicy,
) -> DimensionAssessment:
    state = facts.evidence_states["economic_overlap"]

    unsupported = _require_supported(
        facts,
        "economic_overlap",
    )
    if unsupported:
        return _unknown(
            evidence_state=state,
            reason_code=unsupported,
        )

    exposure = facts.candidate_primary_exposure
    if not exposure:
        return _unknown(
            evidence_state=state,
            reason_code="CANDIDATE_EXPOSURE_UNAVAILABLE",
        )

    interval = _interval_for_candidate_bucket(facts)

    if interval is None:
        return _unknown(
            evidence_state=state,
            reason_code="PORTFOLIO_BUCKET_UNMEASURED",
            rule_id="OVERLAP-UNKNOWN-UNMEASURED-01",
            structured_facts={
                "candidate_primary_exposure": exposure,
                "measured_portfolio_buckets":
                    dict(facts.portfolio_bucket_weights),
                "portfolio_unknown_pct":
                    facts.portfolio_unknown_pct,
            },
        )

    lower, upper = interval

    cfg = policy.raw["economic_overlap"]

    low_band = float(cfg["low_upper_exclusive_pct"])
    medium_band = float(cfg["medium_upper_inclusive_pct"])

    lower_class = _classify_overlap_point(
        lower,
        low_upper_exclusive=low_band,
        medium_upper_inclusive=medium_band,
    )
    upper_class = _classify_overlap_point(
        upper,
        low_upper_exclusive=low_band,
        medium_upper_inclusive=medium_band,
    )

    structured = {
        "candidate_primary_exposure": exposure,
        "portfolio_bucket_weight_pct": lower,
        "portfolio_unknown_pct":
            facts.portfolio_unknown_pct,
        "possible_true_bucket_interval_pct": [
            lower,
            upper,
        ],
        "portfolio_completeness":
            facts.portfolio_completeness,
    }

    if lower_class != upper_class:
        return _unknown(
            evidence_state=state,
            reason_code="UNCERTAINTY_CROSSES_POLICY_BOUNDARY",
            rule_id="OVERLAP-UNKNOWN-CROSS-BAND-01",
            structured_facts=structured,
            limitations=(
                "PORTFOLIO_EXPOSURE_PARTIAL",
            ),
        )

    rule_id = {
        "LOW": "OVERLAP-LOW-01",
        "MEDIUM": "OVERLAP-MEDIUM-01",
        "HIGH": "OVERLAP-HIGH-01",
    }[lower_class]

    limitations: tuple[str, ...] = ()
    if facts.portfolio_unknown_pct not in {None, 0.0}:
        limitations = (
            "PORTFOLIO_EXPOSURE_PARTIAL",
        )

    return DimensionAssessment(
        assessment=lower_class,
        confidence=_portfolio_confidence(facts),
        rule_id=rule_id,
        reason_code=None,
        structured_facts=structured,
        evidence_state=state,
        limitations=limitations,
    )


def _classify_diversification_point(
    value: float,
    *,
    high_upper_exclusive: float,
    medium_upper_inclusive: float,
) -> str:
    if value < high_upper_exclusive:
        return "HIGH"

    if value <= medium_upper_inclusive:
        return "MEDIUM"

    return "LOW"


def _diversification(
    facts: PortfolioFitAssessmentFacts,
    policy: Fund18AssessmentPolicy,
) -> DimensionAssessment:
    state = facts.evidence_states[
        "diversification_contribution"
    ]

    unsupported = _require_supported(
        facts,
        "diversification_contribution",
    )
    if unsupported:
        return _unknown(
            evidence_state=state,
            reason_code=unsupported,
        )

    exposure = facts.candidate_primary_exposure
    if not exposure:
        return _unknown(
            evidence_state=state,
            reason_code="CANDIDATE_EXPOSURE_UNAVAILABLE",
        )

    interval = _interval_for_candidate_bucket(facts)

    if interval is None:
        return _unknown(
            evidence_state=state,
            reason_code="PORTFOLIO_BUCKET_UNMEASURED",
            rule_id="DIVERSIFICATION-UNKNOWN-UNMEASURED-01",
            structured_facts={
                "candidate_primary_exposure": exposure,
                "measured_portfolio_buckets":
                    dict(facts.portfolio_bucket_weights),
                "portfolio_unknown_pct":
                    facts.portfolio_unknown_pct,
            },
        )

    lower, upper = interval

    cfg = policy.raw[
        "diversification_contribution"
    ]

    high_band = float(
        cfg["high_upper_exclusive_pct"]
    )
    medium_band = float(
        cfg["medium_upper_inclusive_pct"]
    )

    lower_class = _classify_diversification_point(
        lower,
        high_upper_exclusive=high_band,
        medium_upper_inclusive=medium_band,
    )
    upper_class = _classify_diversification_point(
        upper,
        high_upper_exclusive=high_band,
        medium_upper_inclusive=medium_band,
    )

    structured = {
        "candidate_primary_exposure": exposure,
        "portfolio_bucket_weight_pct": lower,
        "portfolio_unknown_pct":
            facts.portfolio_unknown_pct,
        "possible_true_bucket_interval_pct": [
            lower,
            upper,
        ],
        "portfolio_completeness":
            facts.portfolio_completeness,
    }

    if lower_class != upper_class:
        return _unknown(
            evidence_state=state,
            reason_code="UNCERTAINTY_CROSSES_POLICY_BOUNDARY",
            rule_id="DIVERSIFICATION-UNKNOWN-CROSS-BAND-01",
            structured_facts=structured,
            limitations=(
                "PORTFOLIO_EXPOSURE_PARTIAL",
            ),
        )

    rule_id = {
        "HIGH": "DIVERSIFICATION-HIGH-01",
        "MEDIUM": "DIVERSIFICATION-MEDIUM-01",
        "LOW": "DIVERSIFICATION-LOW-01",
    }[lower_class]

    limitations: tuple[str, ...] = ()
    if facts.portfolio_unknown_pct not in {None, 0.0}:
        limitations = (
            "PORTFOLIO_EXPOSURE_PARTIAL",
        )

    return DimensionAssessment(
        assessment=lower_class,
        confidence=_portfolio_confidence(facts),
        rule_id=rule_id,
        reason_code=None,
        structured_facts=structured,
        evidence_state=state,
        limitations=limitations,
    )


def _concentration(
    facts: PortfolioFitAssessmentFacts,
    policy: Fund18AssessmentPolicy,
) -> DimensionAssessment:
    state = facts.evidence_states["concentration_risk"]

    unsupported = _require_supported(
        facts,
        "concentration_risk",
    )
    if unsupported:
        return _unknown(
            evidence_state=state,
            reason_code=unsupported,
        )

    weight = facts.current_candidate_weight_pct

    if weight is None:
        return _unknown(
            evidence_state=state,
            reason_code="CURRENT_WEIGHT_UNAVAILABLE",
            rule_id="CONCENTRATION-UNKNOWN-WEIGHT-01",
        )

    cfg = policy.raw["concentration_risk"]

    low_upper = float(
        cfg["low_upper_inclusive_pct"]
    )
    medium_upper = float(
        cfg["medium_upper_inclusive_pct"]
    )

    if weight <= low_upper:
        assessment = "LOW"
        rule_id = "CONCENTRATION-LOW-01"
    elif weight <= medium_upper:
        assessment = "MEDIUM"
        rule_id = "CONCENTRATION-MEDIUM-01"
    else:
        assessment = "HIGH"
        rule_id = "CONCENTRATION-HIGH-01"

    return DimensionAssessment(
        assessment=assessment,
        confidence="HIGH",
        rule_id=rule_id,
        reason_code=None,
        structured_facts={
            "current_candidate_weight_pct": weight,
        },
        evidence_state=state,
        limitations=(
            "CURRENT_POSITION_CONCENTRATION_ONLY",
        ),
    )


def evaluate_portfolio_fit_assessments(
    facts: PortfolioFitAssessmentFacts,
    policy: Fund18AssessmentPolicy,
    *,
    mode: str = MODE_SIMULATION,
) -> PortfolioFitAssessmentResult:
    if mode not in VALID_MODES:
        raise PortfolioFitAssessmentEngineError(
            f"unsupported_mode:{mode}"
        )

    if mode == MODE_EFFECTIVE:
        if not policy.human_approved:
            raise PortfolioFitAssessmentEngineError(
                "effective_mode_requires_human_approval"
            )
        if not policy.locked:
            raise PortfolioFitAssessmentEngineError(
                "effective_mode_requires_locked_policy"
            )
        if not policy.production_effective:
            raise PortfolioFitAssessmentEngineError(
                "effective_mode_requires_production_effective_policy"
            )

    return PortfolioFitAssessmentResult(
        fund_code=facts.fund_code,
        policy_version=str(
            policy.raw["policy_version"]
        ),
        decision_id=str(
            policy.raw["decision_id"]
        ),
        mode=mode,
        production_effective=(
            mode == MODE_EFFECTIVE
            and policy.production_effective
        ),
        role_fit=_role_fit(facts, policy),
        economic_overlap=_economic_overlap(
            facts,
            policy,
        ),
        diversification_contribution=_diversification(
            facts,
            policy,
        ),
        concentration_risk=_concentration(
            facts,
            policy,
        ),
    )
