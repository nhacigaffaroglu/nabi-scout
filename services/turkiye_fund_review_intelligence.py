"""Read-only Review Intelligence derived from the existing Türkiye fund scanner result.

FUND25-D.
No new scanner-result schema, persistence table, background job, ranking,
recommendation, 8E, New Money, portfolio write, or execution authority.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from services.turkiye_fund_review_reason_presentation import (
    READY,
    UNCLASSIFIED_REVIEW_GATE,
    actionable_reason_depth,
    extract_review_reasons,
    present_review_reasons,
    primary_review_reason,
)

SCHEMA_VERSION = "fund25d_review_intelligence_1"


@dataclass(frozen=True)
class FundReviewDiagnostic:
    fund_code: str
    fund_name: str | None
    scanner_status: str
    participation: str | None
    fi_profile: str | None
    primary_root_cause: str
    primary_family: str
    primary_family_label: str
    primary_action: str
    secondary_reasons: tuple[str, ...]
    reasons: tuple[str, ...]
    reason_depth: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TurkiyeFundReviewIntelligence:
    schema_version: str
    status_counts: dict[str, int]
    reason_counts: dict[str, int]
    root_cause_counts: dict[str, int]
    reason_depth_counts: dict[int, int]
    profile_reason_counts: dict[str, dict[str, int]]
    fund_diagnostics: tuple[FundReviewDiagnostic, ...]
    unclassified_count: int
    execution_authority: bool = False
    production_persist: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["fund_diagnostics"] = [row.to_dict() for row in self.fund_diagnostics]
        return payload


def _payload(scanner_result: Any) -> Mapping[str, Any]:
    if isinstance(scanner_result, Mapping):
        return scanner_result
    to_dict = getattr(scanner_result, "to_dict", None)
    if callable(to_dict):
        value = to_dict()
        if isinstance(value, Mapping):
            return value
    raise TypeError("scanner_result_must_be_mapping_or_to_dict")


def build_review_intelligence(scanner_result: Any) -> TurkiyeFundReviewIntelligence:
    payload = _payload(scanner_result)
    rows = tuple(payload.get("rows") or ())

    status_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    root_cause_counts: Counter[str] = Counter()
    depth_counts: Counter[int] = Counter()
    profile_reason_counts: dict[str, Counter[str]] = defaultdict(Counter)
    diagnostics: list[FundReviewDiagnostic] = []
    unclassified_count = 0

    for raw in rows:
        if not isinstance(raw, Mapping):
            continue

        status = str(raw.get("scanner_status") or "UNKNOWN").strip().upper() or "UNKNOWN"
        status_counts[status] += 1
        if status == READY:
            continue

        reasons = extract_review_reasons(raw)
        presented = present_review_reasons(raw)
        primary = primary_review_reason(raw)
        if primary is None:
            continue

        for reason in reasons:
            reason_counts[reason] += 1

        root_cause_counts[primary.code] += 1
        depth = actionable_reason_depth(raw)
        depth_counts[depth] += 1

        profile = str(raw.get("fi_profile") or "NONE").strip() or "NONE"
        profile_reason_counts[profile][primary.code] += 1

        secondary = tuple(reason.code for reason in presented if reason.code != primary.code)
        if primary.code == UNCLASSIFIED_REVIEW_GATE:
            unclassified_count += 1

        diagnostics.append(
            FundReviewDiagnostic(
                fund_code=str(raw.get("fund_code") or ""),
                fund_name=raw.get("fund_name"),
                scanner_status=status,
                participation=raw.get("participation"),
                fi_profile=raw.get("fi_profile"),
                primary_root_cause=primary.code,
                primary_family=primary.family,
                primary_family_label=primary.family_label,
                primary_action=primary.action,
                secondary_reasons=secondary,
                reasons=reasons,
                reason_depth=depth,
            )
        )

    diagnostics.sort(
        key=lambda row: (
            row.primary_family,
            row.primary_root_cause,
            row.fi_profile or "",
            row.fund_code,
        )
    )

    return TurkiyeFundReviewIntelligence(
        schema_version=SCHEMA_VERSION,
        status_counts=dict(sorted(status_counts.items())),
        reason_counts=dict(sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))),
        root_cause_counts=dict(
            sorted(root_cause_counts.items(), key=lambda item: (-item[1], item[0]))
        ),
        reason_depth_counts=dict(sorted(depth_counts.items())),
        profile_reason_counts={
            profile: dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))
            for profile, counts in sorted(profile_reason_counts.items())
        },
        fund_diagnostics=tuple(diagnostics),
        unclassified_count=unclassified_count,
    )
