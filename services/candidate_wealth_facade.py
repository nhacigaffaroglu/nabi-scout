from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Optional

from services.candidate_contract import CandidateRankingResult, CandidateRecord

WEALTH_FACADE_VERSION = "candidate_wealth_facade_2"
WEALTH_READ_ONLY_NOTICE = (
    "Read-only research intelligence for Wealth OS. "
    "No allocation, target weight, quantity, trade, 8E, New Money, "
    "or portfolio mutation authority."
)


@dataclass(frozen=True)
class WealthCandidateRow:
    symbol: str
    rank: Optional[int]
    peer_rank: Optional[int]
    eligibility_status: str
    recommendation_band: Optional[str]
    intelligence_state: str
    total_score: Optional[float]
    confidence: float
    data_completeness: Optional[float]
    economic_exposure: Optional[str]
    peer_group: Optional[str]
    analysis_snapshot_id: str
    analysis_as_of: Optional[str]
    score_version: str
    facts_version: Optional[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WealthCandidateFacade:
    ranking_version: str
    ranking_as_of: str
    universe_fingerprint: str
    eligible: tuple[WealthCandidateRow, ...]
    watch_only: tuple[WealthCandidateRow, ...]
    ineligible: tuple[WealthCandidateRow, ...]
    facade_version: str = WEALTH_FACADE_VERSION
    notice: str = WEALTH_READ_ONLY_NOTICE

    def to_dict(self) -> dict[str, Any]:
        return {
            "facade_version": self.facade_version,
            "notice": self.notice,
            "ranking_version": self.ranking_version,
            "ranking_as_of": self.ranking_as_of,
            "universe_fingerprint": self.universe_fingerprint,
            "eligible": [row.to_dict() for row in self.eligible],
            "watch_only": [row.to_dict() for row in self.watch_only],
            "ineligible": [row.to_dict() for row in self.ineligible],
        }


def _row(
    candidate: CandidateRecord,
    *,
    rank: Optional[int],
    peer_rank: Optional[int],
) -> WealthCandidateRow:
    candidate.validate()
    return WealthCandidateRow(
        symbol=candidate.symbol,
        rank=rank,
        peer_rank=peer_rank,
        eligibility_status=candidate.eligibility.status,
        recommendation_band=candidate.recommendation_band,
        intelligence_state=candidate.intelligence_state,
        total_score=candidate.total_score,
        confidence=candidate.confidence,
        data_completeness=candidate.data_completeness,
        economic_exposure=candidate.economic_exposure,
        peer_group=candidate.peer_group,
        analysis_snapshot_id=candidate.source_trace.analysis_snapshot_id,
        analysis_as_of=candidate.source_trace.analysis_as_of,
        score_version=candidate.source_trace.score_version,
        facts_version=candidate.source_trace.facts_version,
    )


def wealth_candidate_facade(ranking: CandidateRankingResult) -> WealthCandidateFacade:
    peer_rank_lookup: dict[tuple[str, str, str], int] = {}
    for group, rows in ranking.ranked_by_peer_group.items():
        for item in rows:
            peer_rank_lookup[
                (
                    group,
                    item.candidate.symbol.upper(),
                    item.candidate.source_trace.analysis_snapshot_id,
                )
            ] = item.rank

    def peer_rank(candidate: CandidateRecord) -> Optional[int]:
        group = str(candidate.peer_group or "").strip()
        if not group:
            return None
        return peer_rank_lookup.get(
            (
                group,
                candidate.symbol.upper(),
                candidate.source_trace.analysis_snapshot_id,
            )
        )

    return WealthCandidateFacade(
        ranking_version=ranking.ranking_version,
        ranking_as_of=ranking.ranking_as_of,
        universe_fingerprint=ranking.universe_fingerprint,
        eligible=tuple(
            _row(
                item.candidate,
                rank=item.rank,
                peer_rank=peer_rank(item.candidate),
            )
            for item in ranking.ranked
        ),
        watch_only=tuple(
            _row(item, rank=None, peer_rank=None) for item in ranking.watch_only
        ),
        ineligible=tuple(
            _row(item, rank=None, peer_rank=None) for item in ranking.ineligible
        ),
    )


def wealth_candidate_lookup(
    facade: WealthCandidateFacade,
    symbol: str,
) -> Optional[WealthCandidateRow]:
    code = str(symbol or "").strip().upper()
    for row in (*facade.eligible, *facade.watch_only, *facade.ineligible):
        if row.symbol.upper() == code:
            return row
    return None
