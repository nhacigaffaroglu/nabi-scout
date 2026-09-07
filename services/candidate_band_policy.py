from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable, Optional

from services.candidate_contract import (
    CANDIDATE_BAND_CANDIDATE,
    CANDIDATE_BAND_REJECT,
    CANDIDATE_BAND_STRONG,
    CANDIDATE_BAND_WATCH,
    CandidateRecord,
    ELIGIBILITY_ELIGIBLE,
)

BAND_POLICY_SCHEMA_VERSION = "candidate_band_policy_1"


@dataclass(frozen=True)
class CandidateBandPolicy:
    policy_version: str
    calibration_fingerprint: str
    strong_candidate_min: float
    candidate_min: float
    watch_min: float
    schema_version: str = BAND_POLICY_SCHEMA_VERSION

    def validate(self) -> None:
        if not self.policy_version:
            raise ValueError("candidate_band_policy_version_required")
        if not self.calibration_fingerprint:
            raise ValueError("candidate_band_calibration_fingerprint_required")
        values = (
            float(self.strong_candidate_min),
            float(self.candidate_min),
            float(self.watch_min),
        )
        if not all(0.0 <= value <= 100.0 for value in values):
            raise ValueError("candidate_band_threshold_out_of_range")
        if not (
            self.strong_candidate_min
            > self.candidate_min
            > self.watch_min
        ):
            raise ValueError("candidate_band_threshold_order_invalid")


def band_for_score(
    score: Optional[float],
    *,
    policy: CandidateBandPolicy,
) -> str:
    policy.validate()
    if score is None:
        return CANDIDATE_BAND_REJECT
    value = float(score)
    if value >= policy.strong_candidate_min:
        return CANDIDATE_BAND_STRONG
    if value >= policy.candidate_min:
        return CANDIDATE_BAND_CANDIDATE
    if value >= policy.watch_min:
        return CANDIDATE_BAND_WATCH
    return CANDIDATE_BAND_REJECT


def apply_candidate_band_policy(
    record: CandidateRecord,
    *,
    policy: CandidateBandPolicy,
) -> CandidateRecord:
    record.validate()
    policy.validate()

    if record.eligibility.status != ELIGIBILITY_ELIGIBLE:
        return replace(record, recommendation_band=None)

    return replace(
        record,
        recommendation_band=band_for_score(record.total_score, policy=policy),
    )


def apply_band_policy_to_records(
    records: Iterable[CandidateRecord],
    *,
    policy: CandidateBandPolicy,
) -> tuple[CandidateRecord, ...]:
    return tuple(
        apply_candidate_band_policy(row, policy=policy)
        for row in records
    )
