from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from services.candidate_wealth_facade import WealthCandidateFacade

WEALTH_FEED_SCHEMA_VERSION = "nabi_wealth_candidate_feed_2"
WEALTH_FEED_SOURCE_SYSTEM = "NABI_SCOUT"
WEALTH_FEED_AUTHORITY = "RESEARCH_ONLY"
DEFAULT_WEALTH_FEED_PATH = Path(
    ".cache/candidate_release_gate/wealth_os_candidate_feed.json"
)

FORBIDDEN_EXECUTION_KEYS = frozenset({
    "action",
    "buy",
    "sell",
    "allocation",
    "target_weight",
    "quantity",
    "position_size",
    "trade",
    "new_money",
    "new_money_amount",
    "amount",
    "units",
    "shares",
})


@dataclass(frozen=True)
class WealthCandidateFeed:
    schema_version: str
    source_system: str
    authority: str
    research_only: bool
    ranking_version: str
    ranking_as_of: str
    universe_fingerprint: str
    export_fingerprint: str
    eligible: tuple[dict[str, Any], ...]
    watch_only: tuple[dict[str, Any], ...]
    ineligible: tuple[dict[str, Any], ...]
    notice: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _row_payload(row: Any) -> dict[str, Any]:
    return {
        "symbol": row.symbol,
        "rank": row.rank,
        "peer_rank": row.peer_rank,
        "eligibility_status": row.eligibility_status,
        "recommendation_band": row.recommendation_band,
        "intelligence_state": row.intelligence_state,
        "total_score": row.total_score,
        "confidence": row.confidence,
        "data_completeness": row.data_completeness,
        "economic_exposure": row.economic_exposure,
        "peer_group": row.peer_group,
        "analysis_snapshot_id": row.analysis_snapshot_id,
        "analysis_as_of": row.analysis_as_of,
        "score_version": row.score_version,
        "facts_version": row.facts_version,
    }


def _assert_no_execution_keys(value: Any, *, path: str = "root") -> None:
    if isinstance(value, dict):
        bad = sorted(FORBIDDEN_EXECUTION_KEYS.intersection(value))
        if bad:
            raise ValueError(
                f"wealth_feed_execution_keys_forbidden:{path}:{','.join(bad)}"
            )
        for key, item in value.items():
            _assert_no_execution_keys(item, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_no_execution_keys(item, path=f"{path}[{index}]")


def _base_payload(facade: WealthCandidateFacade) -> dict[str, Any]:
    payload = {
        "schema_version": WEALTH_FEED_SCHEMA_VERSION,
        "source_system": WEALTH_FEED_SOURCE_SYSTEM,
        "authority": WEALTH_FEED_AUTHORITY,
        "research_only": True,
        "ranking_version": facade.ranking_version,
        "ranking_as_of": facade.ranking_as_of,
        "universe_fingerprint": facade.universe_fingerprint,
        "eligible": [_row_payload(row) for row in facade.eligible],
        "watch_only": [_row_payload(row) for row in facade.watch_only],
        "ineligible": [_row_payload(row) for row in facade.ineligible],
        "notice": facade.notice,
    }
    _assert_no_execution_keys(payload)
    return payload


def _fingerprint(payload: dict[str, Any]) -> str:
    body = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def build_wealth_candidate_feed(
    facade: WealthCandidateFacade,
) -> WealthCandidateFeed:
    payload = _base_payload(facade)
    fingerprint = _fingerprint(payload)
    return WealthCandidateFeed(
        schema_version=payload["schema_version"],
        source_system=payload["source_system"],
        authority=payload["authority"],
        research_only=True,
        ranking_version=payload["ranking_version"],
        ranking_as_of=payload["ranking_as_of"],
        universe_fingerprint=payload["universe_fingerprint"],
        export_fingerprint=fingerprint,
        eligible=tuple(payload["eligible"]),
        watch_only=tuple(payload["watch_only"]),
        ineligible=tuple(payload["ineligible"]),
        notice=payload["notice"],
    )


def validate_wealth_candidate_feed(feed: WealthCandidateFeed) -> None:
    payload = feed.to_dict()
    if payload["schema_version"] != WEALTH_FEED_SCHEMA_VERSION:
        raise ValueError("wealth_feed_schema_version_invalid")
    if payload["source_system"] != WEALTH_FEED_SOURCE_SYSTEM:
        raise ValueError("wealth_feed_source_system_invalid")
    if payload["authority"] != WEALTH_FEED_AUTHORITY:
        raise ValueError("wealth_feed_authority_invalid")
    if payload["research_only"] is not True:
        raise ValueError("wealth_feed_must_be_research_only")

    expected = _fingerprint({
        key: value
        for key, value in payload.items()
        if key != "export_fingerprint"
    })
    if payload["export_fingerprint"] != expected:
        raise ValueError("wealth_feed_export_fingerprint_mismatch")

    _assert_no_execution_keys(payload)


def write_wealth_candidate_feed(
    facade: WealthCandidateFacade,
    *,
    output_path: Path = DEFAULT_WEALTH_FEED_PATH,
) -> Path:
    feed = build_wealth_candidate_feed(facade)
    validate_wealth_candidate_feed(feed)

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(feed.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path
