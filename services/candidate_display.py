from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Optional

from services.candidate_contract import CandidateRecord, RankedCandidate

CANDIDATE_CARD_VERSION = "candidate_card_2"
CANDIDATE_COMPARISON_VERSION = "candidate_comparison_2"

RESEARCH_ONLY_NOTICE = (
    "Research-only candidate intelligence. Not a buy, sell, allocation, "
    "8E, New Money, or portfolio instruction."
)


@dataclass(frozen=True)
class CandidateCard:
    symbol: str
    rank: Optional[int]
    eligibility_status: str
    eligibility_reasons: tuple[str, ...]
    recommendation_band: Optional[str]
    intelligence_state: str
    total_score: Optional[float]
    confidence: float
    data_completeness: Optional[float]
    economic_exposure: Optional[str]
    peer_group: Optional[str]
    top_drivers: tuple[str, ...]
    top_risks: tuple[str, ...]
    sub_scores: tuple[tuple[str, float], ...]
    analysis_snapshot_id: str
    analysis_as_of: Optional[str]
    score_version: str
    facts_version: Optional[str]
    source_provenance: tuple[str, ...]
    limitations: tuple[str, ...]
    notice: str = RESEARCH_ONLY_NOTICE
    card_version: str = CANDIDATE_CARD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CandidateComparisonRow:
    symbol: str
    rank: Optional[int]
    eligibility_status: str
    recommendation_band: Optional[str]
    intelligence_state: str
    total_score: Optional[float]
    confidence: float
    data_completeness: Optional[float]
    economic_exposure: Optional[str]
    peer_group: Optional[str]
    analysis_snapshot_id: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CandidateComparison:
    rows: tuple[CandidateComparisonRow, ...]
    comparison_version: str = CANDIDATE_COMPARISON_VERSION
    notice: str = RESEARCH_ONLY_NOTICE

    def to_dict(self) -> dict[str, Any]:
        return {
            "comparison_version": self.comparison_version,
            "notice": self.notice,
            "rows": [row.to_dict() for row in self.rows],
        }


def candidate_card(
    candidate: CandidateRecord,
    *,
    rank: Optional[int] = None,
) -> CandidateCard:
    candidate.validate()
    return CandidateCard(
        symbol=candidate.symbol,
        rank=rank,
        eligibility_status=candidate.eligibility.status,
        eligibility_reasons=tuple(candidate.eligibility.reasons),
        recommendation_band=candidate.recommendation_band,
        intelligence_state=candidate.intelligence_state,
        total_score=candidate.total_score,
        confidence=candidate.confidence,
        data_completeness=candidate.data_completeness,
        economic_exposure=candidate.economic_exposure,
        peer_group=candidate.peer_group,
        top_drivers=tuple(candidate.top_drivers),
        top_risks=tuple(candidate.top_risks),
        sub_scores=tuple(candidate.sub_scores),
        analysis_snapshot_id=candidate.source_trace.analysis_snapshot_id,
        analysis_as_of=candidate.source_trace.analysis_as_of,
        score_version=candidate.source_trace.score_version,
        facts_version=candidate.source_trace.facts_version,
        source_provenance=tuple(candidate.source_trace.source_provenance),
        limitations=tuple(candidate.limitations),
    )


def ranked_candidate_card(row: RankedCandidate) -> CandidateCard:
    return candidate_card(row.candidate, rank=row.rank)


def compare_candidates(
    rows: Iterable[RankedCandidate | CandidateRecord],
) -> CandidateComparison:
    normalized: list[CandidateComparisonRow] = []
    for item in rows:
        if isinstance(item, RankedCandidate):
            candidate = item.candidate
            rank = item.rank
        else:
            candidate = item
            rank = None
        candidate.validate()
        normalized.append(
            CandidateComparisonRow(
                symbol=candidate.symbol,
                rank=rank,
                eligibility_status=candidate.eligibility.status,
                recommendation_band=candidate.recommendation_band,
                intelligence_state=candidate.intelligence_state,
                total_score=candidate.total_score,
                confidence=candidate.confidence,
                data_completeness=candidate.data_completeness,
                economic_exposure=candidate.economic_exposure,
                peer_group=candidate.peer_group,
                analysis_snapshot_id=candidate.source_trace.analysis_snapshot_id,
            )
        )
    return CandidateComparison(rows=tuple(normalized))
