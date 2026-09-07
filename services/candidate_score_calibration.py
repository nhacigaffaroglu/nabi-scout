from __future__ import annotations

from dataclasses import asdict, dataclass
from math import floor
from typing import Any, Iterable, Optional

from services.candidate_contract import CandidateRecord, ELIGIBILITY_ELIGIBLE

CALIBRATION_DIAGNOSTIC_VERSION = "candidate_calibration_diag_2"


@dataclass(frozen=True)
class ScoreDistribution:
    count: int
    minimum: Optional[float]
    q10: Optional[float]
    q25: Optional[float]
    median: Optional[float]
    q75: Optional[float]
    q90: Optional[float]
    maximum: Optional[float]
    mean: Optional[float]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CandidateCalibrationDiagnostic:
    eligible_scores: ScoreDistribution
    by_intelligence_state: tuple[tuple[str, ScoreDistribution], ...]
    by_instrument_type: tuple[tuple[str, ScoreDistribution], ...]
    by_peer_group: tuple[tuple[str, ScoreDistribution], ...]
    by_economic_exposure: tuple[tuple[str, ScoreDistribution], ...]
    diagnostic_version: str = CALIBRATION_DIAGNOSTIC_VERSION
    thresholds_proposed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "diagnostic_version": self.diagnostic_version,
            "thresholds_proposed": self.thresholds_proposed,
            "eligible_scores": self.eligible_scores.to_dict(),
            "by_intelligence_state": [
                (key, value.to_dict()) for key, value in self.by_intelligence_state
            ],
            "by_instrument_type": [
                (key, value.to_dict()) for key, value in self.by_instrument_type
            ],
            "by_peer_group": [
                (key, value.to_dict()) for key, value in self.by_peer_group
            ],
            "by_economic_exposure": [
                (key, value.to_dict()) for key, value in self.by_economic_exposure
            ],
        }


def _quantile(sorted_values: list[float], q: float) -> Optional[float]:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * q
    lower = floor(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = position - lower
    return sorted_values[lower] + (
        sorted_values[upper] - sorted_values[lower]
    ) * fraction


def score_distribution(values: Iterable[float]) -> ScoreDistribution:
    data = sorted(float(value) for value in values)
    if not data:
        return ScoreDistribution(0, None, None, None, None, None, None, None, None)
    return ScoreDistribution(
        count=len(data),
        minimum=data[0],
        q10=_quantile(data, 0.10),
        q25=_quantile(data, 0.25),
        median=_quantile(data, 0.50),
        q75=_quantile(data, 0.75),
        q90=_quantile(data, 0.90),
        maximum=data[-1],
        mean=sum(data) / len(data),
    )


def candidate_score_calibration_diagnostic(
    records: Iterable[CandidateRecord],
) -> CandidateCalibrationDiagnostic:
    eligible = tuple(
        row for row in records
        if row.eligibility.status == ELIGIBILITY_ELIGIBLE
        and row.total_score is not None
    )
    state_groups: dict[str, list[float]] = {}
    instrument_groups: dict[str, list[float]] = {}
    peer_groups: dict[str, list[float]] = {}
    exposure_groups: dict[str, list[float]] = {}
    for row in eligible:
        row.validate()
        score = float(row.total_score)
        state_groups.setdefault(row.intelligence_state, []).append(score)
        instrument_groups.setdefault(row.instrument_type, []).append(score)
        peer = str(row.peer_group or "").strip()
        if peer:
            peer_groups.setdefault(peer, []).append(score)
        exposure = str(row.economic_exposure or "").strip()
        if exposure:
            exposure_groups.setdefault(exposure, []).append(score)
    return CandidateCalibrationDiagnostic(
        eligible_scores=score_distribution(float(row.total_score) for row in eligible),
        by_intelligence_state=tuple(
            (key, score_distribution(values))
            for key, values in sorted(state_groups.items())
        ),
        by_instrument_type=tuple(
            (key, score_distribution(values))
            for key, values in sorted(instrument_groups.items())
        ),
        by_peer_group=tuple(
            (key, score_distribution(values))
            for key, values in sorted(peer_groups.items())
        ),
        by_economic_exposure=tuple(
            (key, score_distribution(values))
            for key, values in sorted(exposure_groups.items())
        ),
        thresholds_proposed=False,
    )
