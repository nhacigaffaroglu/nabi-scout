from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
from typing import Any

from services.candidate_wealth_export import (
    WealthCandidateFeed,
    validate_wealth_candidate_feed,
)

WEALTH_TRANSPORT_VERSION = "nabi_wealth_candidate_transport_2"
DEFAULT_WEALTH_TRANSPORT_PATH = Path(
    ".cache/candidate_release_gate/wealth_os_candidate_transport.json"
)

FRESHNESS_FRESH = "FRESH"
FRESHNESS_STALE = "STALE"
FRESHNESS_FUTURE_DATED = "FUTURE_DATED"


@dataclass(frozen=True)
class WealthCandidateTransport:
    envelope_version: str
    payload_sha256: str
    payload_json: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WealthFeedFreshness:
    status: str
    ranking_as_of: str
    reference_date: str
    age_days: int
    max_age_days: int

    @property
    def acceptable(self) -> bool:
        return self.status == FRESHNESS_FRESH

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _payload_json(feed: WealthCandidateFeed) -> str:
    validate_wealth_candidate_feed(feed)
    return json.dumps(
        feed.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_wealth_candidate_transport(
    feed: WealthCandidateFeed,
) -> WealthCandidateTransport:
    payload_json = _payload_json(feed)
    return WealthCandidateTransport(
        envelope_version=WEALTH_TRANSPORT_VERSION,
        payload_sha256=_sha256_text(payload_json),
        payload_json=payload_json,
    )


def validate_wealth_candidate_transport(
    envelope: WealthCandidateTransport,
) -> WealthCandidateFeed:
    if envelope.envelope_version != WEALTH_TRANSPORT_VERSION:
        raise ValueError("wealth_transport_version_invalid")
    if not isinstance(envelope.payload_json, str) or not envelope.payload_json:
        raise ValueError("wealth_transport_payload_json_required")
    if _sha256_text(envelope.payload_json) != envelope.payload_sha256:
        raise ValueError("wealth_transport_payload_sha256_mismatch")

    payload = json.loads(envelope.payload_json)
    if not isinstance(payload, dict):
        raise ValueError("wealth_transport_payload_object_required")

    feed = WealthCandidateFeed(
        schema_version=payload.get("schema_version"),
        source_system=payload.get("source_system"),
        authority=payload.get("authority"),
        research_only=payload.get("research_only"),
        ranking_version=payload.get("ranking_version"),
        ranking_as_of=payload.get("ranking_as_of"),
        universe_fingerprint=payload.get("universe_fingerprint"),
        export_fingerprint=payload.get("export_fingerprint"),
        eligible=tuple(payload.get("eligible") or ()),
        watch_only=tuple(payload.get("watch_only") or ()),
        ineligible=tuple(payload.get("ineligible") or ()),
        notice=payload.get("notice"),
    )
    validate_wealth_candidate_feed(feed)
    return feed


def evaluate_wealth_feed_freshness(
    feed: WealthCandidateFeed,
    *,
    reference_date: date,
    max_age_days: int,
) -> WealthFeedFreshness:
    if not isinstance(reference_date, date):
        raise TypeError("wealth_feed_reference_date_required")
    if not isinstance(max_age_days, int) or isinstance(max_age_days, bool):
        raise TypeError("wealth_feed_max_age_days_must_be_int")
    if max_age_days < 0:
        raise ValueError("wealth_feed_max_age_days_must_be_nonnegative")

    try:
        as_of = date.fromisoformat(str(feed.ranking_as_of))
    except ValueError as exc:
        raise ValueError("wealth_feed_ranking_as_of_invalid") from exc

    age_days = (reference_date - as_of).days
    if age_days < 0:
        status = FRESHNESS_FUTURE_DATED
    elif age_days > max_age_days:
        status = FRESHNESS_STALE
    else:
        status = FRESHNESS_FRESH

    return WealthFeedFreshness(
        status=status,
        ranking_as_of=as_of.isoformat(),
        reference_date=reference_date.isoformat(),
        age_days=age_days,
        max_age_days=max_age_days,
    )


def require_wealth_feed_freshness(
    feed: WealthCandidateFeed,
    *,
    reference_date: date,
    max_age_days: int,
) -> WealthFeedFreshness:
    freshness = evaluate_wealth_feed_freshness(
        feed,
        reference_date=reference_date,
        max_age_days=max_age_days,
    )
    if freshness.status == FRESHNESS_STALE:
        raise ValueError(
            "wealth_feed_stale:"
            f"age_days={freshness.age_days}:max_age_days={freshness.max_age_days}"
        )
    if freshness.status == FRESHNESS_FUTURE_DATED:
        raise ValueError(
            "wealth_feed_future_dated:"
            f"age_days={freshness.age_days}"
        )
    return freshness


def write_wealth_candidate_transport(
    feed: WealthCandidateFeed,
    *,
    output_path: Path = DEFAULT_WEALTH_TRANSPORT_PATH,
) -> Path:
    envelope = build_wealth_candidate_transport(feed)
    validate_wealth_candidate_transport(envelope)

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(envelope.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path
