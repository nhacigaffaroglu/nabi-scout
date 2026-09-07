from __future__ import annotations

import hashlib
import json
from typing import Iterable

from services.candidate_contract import (
    CANDIDATE_RANKING_VERSION,
    CandidateRankingResult,
    CandidateRecord,
    RankedCandidate,
    ELIGIBILITY_ELIGIBLE,
    ELIGIBILITY_INELIGIBLE,
    ELIGIBILITY_WATCH_ONLY,
)


def _normalized_symbol(value: str) -> str:
    return str(value or "").strip().upper()


def _score(value):
    return float(value) if value is not None else None


def _completeness(value):
    return float(value) if value is not None else -1.0


def _confidence(value):
    return float(value) if value is not None else -1.0


def candidate_rank_key(row: CandidateRecord) -> tuple:
    """score desc -> completeness desc -> confidence desc -> symbol asc."""
    if row.total_score is None:
        raise ValueError(f"eligible_candidate_missing_score:{row.symbol}")
    return (
        -float(row.total_score),
        -_completeness(row.data_completeness),
        -_confidence(row.confidence),
        _normalized_symbol(row.symbol),
    )


def _fingerprint_payload(records: tuple[CandidateRecord, ...]) -> list[dict]:
    payload = []
    for row in sorted(
        records,
        key=lambda item: (
            _normalized_symbol(item.symbol),
            item.source_trace.analysis_snapshot_id,
        ),
    ):
        payload.append(
            {
                "symbol": _normalized_symbol(row.symbol),
                "market": row.market,
                "instrument_type": row.instrument_type,
                "total_score": _score(row.total_score),
                "confidence": _confidence(row.confidence),
                "data_completeness": (
                    None
                    if row.data_completeness is None
                    else float(row.data_completeness)
                ),
                "intelligence_state": row.intelligence_state,
                "eligibility_status": row.eligibility.status,
                "eligibility_reasons": list(row.eligibility.reasons),
                "analysis_snapshot_id": row.source_trace.analysis_snapshot_id,
                "analysis_as_of": row.source_trace.analysis_as_of,
                "score_version": row.source_trace.score_version,
                "facts_version": row.source_trace.facts_version,
                "recommendation_band": row.recommendation_band,
                "peer_group": row.peer_group,
            }
        )
    return payload


def universe_fingerprint(records: Iterable[CandidateRecord]) -> str:
    items = tuple(records)
    body = json.dumps(
        _fingerprint_payload(items),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()



def _peer_group(value: object) -> str:
    return str(value or "").strip()


def _rank_rows(rows: Iterable[CandidateRecord]) -> tuple[RankedCandidate, ...]:
    ordered = tuple(sorted(tuple(rows), key=candidate_rank_key))
    return tuple(
        RankedCandidate(rank=index, candidate=row)
        for index, row in enumerate(ordered, start=1)
    )


def rank_candidates(
    records: Iterable[CandidateRecord],
    *,
    ranking_as_of: str,
) -> CandidateRankingResult:
    items = tuple(records)
    if not ranking_as_of:
        raise ValueError("ranking_as_of_required")

    seen: set[tuple[str, str]] = set()
    for row in items:
        row.validate()
        identity = (
            _normalized_symbol(row.symbol),
            row.source_trace.analysis_snapshot_id,
        )
        if identity in seen:
            raise ValueError(
                f"duplicate_candidate_snapshot:{identity[0]}:{identity[1]}"
            )
        seen.add(identity)

    eligible = tuple(
        row for row in items if row.eligibility.status == ELIGIBILITY_ELIGIBLE
    )
    watch_only = tuple(
        sorted(
            (
                row
                for row in items
                if row.eligibility.status == ELIGIBILITY_WATCH_ONLY
            ),
            key=lambda row: _normalized_symbol(row.symbol),
        )
    )
    ineligible = tuple(
        sorted(
            (
                row
                for row in items
                if row.eligibility.status == ELIGIBILITY_INELIGIBLE
            ),
            key=lambda row: _normalized_symbol(row.symbol),
        )
    )

    ranked = _rank_rows(eligible)

    peer_groups: dict[str, list[CandidateRecord]] = {}
    for row in eligible:
        group = _peer_group(row.peer_group)
        if not group:
            continue
        peer_groups.setdefault(group, []).append(row)
    ranked_by_peer_group = {
        group: _rank_rows(rows)
        for group, rows in sorted(peer_groups.items())
    }

    return CandidateRankingResult(
        ranking_version=CANDIDATE_RANKING_VERSION,
        ranking_as_of=ranking_as_of,
        universe_fingerprint=universe_fingerprint(items),
        ranked=ranked,
        watch_only=watch_only,
        ineligible=ineligible,
        ranked_by_peer_group=ranked_by_peer_group,
    )
