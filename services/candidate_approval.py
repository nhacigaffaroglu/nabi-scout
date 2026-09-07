from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Optional

from services.candidate_contract import CandidateRankingResult, RankedCandidate

REVIEW_PENDING = "PENDING_REVIEW"
REVIEW_RESEARCH_APPROVED = "RESEARCH_APPROVED"
REVIEW_REJECTED = "REJECTED"
REVIEW_STATES = (
    REVIEW_PENDING,
    REVIEW_RESEARCH_APPROVED,
    REVIEW_REJECTED,
)

APPROVAL_PACKAGE_VERSION = "candidate_approval_2"

RESEARCH_APPROVAL_NOTICE = (
    "Research approval only. This does not authorize a trade, allocation, "
    "position size, 8E action, New Money action, or portfolio write."
)


@dataclass(frozen=True)
class CandidateReviewDecision:
    state: str
    reason: str = ""

    def validate(self) -> None:
        if self.state not in REVIEW_STATES:
            raise ValueError(f"unknown_candidate_review_state:{self.state}")


@dataclass(frozen=True)
class CandidateApprovalPackage:
    symbol: str
    rank: int
    peer_group: Optional[str]
    peer_rank: Optional[int]
    analysis_snapshot_id: str
    ranking_version: str
    ranking_as_of: str
    universe_fingerprint: str
    score_version: str
    facts_version: Optional[str]
    review: CandidateReviewDecision
    notice: str = RESEARCH_APPROVAL_NOTICE
    package_version: str = APPROVAL_PACKAGE_VERSION

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["review"] = asdict(self.review)
        return payload



def _peer_rank_for(
    ranking_result: CandidateRankingResult,
    candidate,
) -> Optional[int]:
    group = str(candidate.peer_group or "").strip()
    if not group:
        return None
    for row in ranking_result.ranked_by_peer_group.get(group, ()):
        if (
            row.candidate.symbol == candidate.symbol
            and row.candidate.source_trace.analysis_snapshot_id
            == candidate.source_trace.analysis_snapshot_id
        ):
            return row.rank
    return None


def build_candidate_approval_package(
    ranked: RankedCandidate,
    ranking_result: CandidateRankingResult,
    *,
    review: Optional[CandidateReviewDecision] = None,
) -> CandidateApprovalPackage:
    if ranked.rank < 1:
        raise ValueError("candidate_approval_rank_invalid")

    candidate = ranked.candidate
    candidate.validate()
    if not candidate.eligibility.rankable:
        raise ValueError(f"candidate_approval_not_rankable:{candidate.symbol}")

    match = next(
        (
            row
            for row in ranking_result.ranked
            if row.rank == ranked.rank
            and row.candidate.symbol == candidate.symbol
            and row.candidate.source_trace.analysis_snapshot_id
            == candidate.source_trace.analysis_snapshot_id
        ),
        None,
    )
    if match is None:
        raise ValueError(
            f"candidate_approval_ranking_membership_mismatch:{candidate.symbol}"
        )

    decision = review or CandidateReviewDecision(state=REVIEW_PENDING)
    decision.validate()

    return CandidateApprovalPackage(
        symbol=candidate.symbol,
        rank=ranked.rank,
        peer_group=candidate.peer_group,
        peer_rank=_peer_rank_for(ranking_result, candidate),
        analysis_snapshot_id=candidate.source_trace.analysis_snapshot_id,
        ranking_version=ranking_result.ranking_version,
        ranking_as_of=ranking_result.ranking_as_of,
        universe_fingerprint=ranking_result.universe_fingerprint,
        score_version=candidate.source_trace.score_version,
        facts_version=candidate.source_trace.facts_version,
        review=decision,
    )


def with_review_decision(
    package: CandidateApprovalPackage,
    decision: CandidateReviewDecision,
) -> CandidateApprovalPackage:
    decision.validate()
    return CandidateApprovalPackage(
        symbol=package.symbol,
        rank=package.rank,
        peer_group=package.peer_group,
        peer_rank=package.peer_rank,
        analysis_snapshot_id=package.analysis_snapshot_id,
        ranking_version=package.ranking_version,
        ranking_as_of=package.ranking_as_of,
        universe_fingerprint=package.universe_fingerprint,
        score_version=package.score_version,
        facts_version=package.facts_version,
        review=decision,
    )
