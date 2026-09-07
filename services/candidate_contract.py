from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

ELIGIBILITY_ELIGIBLE = "ELIGIBLE"
ELIGIBILITY_WATCH_ONLY = "WATCH_ONLY"
ELIGIBILITY_INELIGIBLE = "INELIGIBLE"
ELIGIBILITY_STATES = (
    ELIGIBILITY_ELIGIBLE,
    ELIGIBILITY_WATCH_ONLY,
    ELIGIBILITY_INELIGIBLE,
)

CANDIDATE_BAND_STRONG = "strong_candidate"
CANDIDATE_BAND_CANDIDATE = "candidate"
CANDIDATE_BAND_WATCH = "watch"
CANDIDATE_BAND_REJECT = "reject"
CANDIDATE_BANDS = (
    CANDIDATE_BAND_STRONG,
    CANDIDATE_BAND_CANDIDATE,
    CANDIDATE_BAND_WATCH,
    CANDIDATE_BAND_REJECT,
)

CANDIDATE_CONTRACT_VERSION = "candidate_contract_3"
CANDIDATE_RANKING_VERSION = "candidate_ranking_2"


@dataclass(frozen=True)
class CandidateEligibility:
    status: str
    reasons: tuple[str, ...] = ()

    @property
    def rankable(self) -> bool:
        return self.status == ELIGIBILITY_ELIGIBLE

    def validate(self) -> None:
        if self.status not in ELIGIBILITY_STATES:
            raise ValueError(f"unknown_candidate_eligibility:{self.status}")


@dataclass(frozen=True)
class CandidateSourceTrace:
    analysis_snapshot_id: str
    analysis_as_of: Optional[str]
    score_version: str
    facts_version: Optional[str] = None
    source_provenance: tuple[str, ...] = ()

    def validate(self) -> None:
        if not self.analysis_snapshot_id:
            raise ValueError("candidate_analysis_snapshot_id_required")
        if not self.score_version:
            raise ValueError("candidate_score_version_required")


@dataclass(frozen=True)
class CandidateRecord:
    symbol: str
    market: str
    instrument_type: str
    total_score: Optional[float]
    confidence: float
    intelligence_state: str
    eligibility: CandidateEligibility
    source_trace: CandidateSourceTrace
    recommendation_band: Optional[str] = None
    data_completeness: Optional[float] = None
    economic_exposure: Optional[str] = None
    peer_group: Optional[str] = None
    sub_scores: tuple[tuple[str, float], ...] = ()
    top_drivers: tuple[str, ...] = ()
    top_risks: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    contract_version: str = CANDIDATE_CONTRACT_VERSION

    def validate(self) -> None:
        if not self.symbol:
            raise ValueError("candidate_symbol_required")
        self.eligibility.validate()
        self.source_trace.validate()
        if self.recommendation_band is not None and self.recommendation_band not in CANDIDATE_BANDS:
            raise ValueError(
                f"unknown_candidate_recommendation_band:{self.recommendation_band}"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RankedCandidate:
    rank: int
    candidate: CandidateRecord

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "candidate": self.candidate.to_dict(),
        }


@dataclass(frozen=True)
class CandidateRankingResult:
    ranking_version: str
    ranking_as_of: str
    universe_fingerprint: str
    ranked: tuple[RankedCandidate, ...]
    watch_only: tuple[CandidateRecord, ...]
    ineligible: tuple[CandidateRecord, ...]
    ranked_by_peer_group: dict[str, tuple[RankedCandidate, ...]] = field(default_factory=dict)

    @property
    def candidate_count(self) -> int:
        return len(self.ranked)

    @property
    def watch_only_count(self) -> int:
        return len(self.watch_only)

    @property
    def ineligible_count(self) -> int:
        return len(self.ineligible)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ranking_version": self.ranking_version,
            "ranking_as_of": self.ranking_as_of,
            "universe_fingerprint": self.universe_fingerprint,
            "candidate_count": self.candidate_count,
            "watch_only_count": self.watch_only_count,
            "ineligible_count": self.ineligible_count,
            "ranked": [row.to_dict() for row in self.ranked],
            "watch_only": [row.to_dict() for row in self.watch_only],
            "ineligible": [row.to_dict() for row in self.ineligible],
            "ranked_by_peer_group": {
                key: [row.to_dict() for row in value]
                for key, value in sorted(self.ranked_by_peer_group.items())
            },
        }
