from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from services.participation_revenue_segment_contract import (
    CLASSIFICATION_NON_PERMISSIBLE,
    CLASSIFICATION_PERMISSIBLE,
    CLASSIFICATION_UNKNOWN,
    RevenueSegmentEvidence,
)
from services.participation_intelligence_contract import CONFIDENCE_HIGH, CONFIDENCE_MEDIUM

_CLASSIFICATION_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "participation_segment_classification.json"
)


@dataclass(frozen=True)
class SegmentLabelPattern:
    pattern: str
    category: str


@lru_cache(maxsize=1)
def _load_patterns() -> tuple[tuple[SegmentLabelPattern, ...], tuple[SegmentLabelPattern, ...]]:
    payload = json.loads(_CLASSIFICATION_PATH.read_text(encoding="utf-8"))
    non_perm = tuple(
        SegmentLabelPattern(
            pattern=str(item["pattern"]).lower(),
            category=str(item["category"]),
        )
        for item in payload.get("non_permissible_patterns") or ()
    )
    perm = tuple(
        SegmentLabelPattern(
            pattern=str(item["pattern"]).lower(),
            category=str(item["category"]),
        )
        for item in payload.get("permissible_patterns") or ()
    )
    return non_perm, perm


def _label_text(segment: RevenueSegmentEvidence) -> str:
    return f"{segment.segment_name} {segment.category}".lower()


def classify_segment(
    segment: RevenueSegmentEvidence,
    *,
    prohibited_categories: Sequence[str] = (),
) -> RevenueSegmentEvidence:
    text = _label_text(segment)
    non_perm_patterns, perm_patterns = _load_patterns()

    for item in non_perm_patterns:
        if item.pattern in text:
            if prohibited_categories and item.category not in prohibited_categories:
                if item.category != "non_permissible":
                    continue
            return replace(
                segment,
                classification_code=CLASSIFICATION_NON_PERMISSIBLE,
                category=item.category if item.category != "non_permissible" else "non_permissible",
                confidence=CONFIDENCE_HIGH,
            )

    for item in perm_patterns:
        if item.pattern in text:
            return replace(
                segment,
                classification_code=CLASSIFICATION_PERMISSIBLE,
                category=item.category,
                confidence=CONFIDENCE_MEDIUM,
            )

    return replace(
        segment,
        classification_code=CLASSIFICATION_UNKNOWN,
    )


def classify_segments(
    segments: Sequence[RevenueSegmentEvidence],
    *,
    prohibited_categories: Sequence[str] = (),
) -> Tuple[RevenueSegmentEvidence, ...]:
    return tuple(
        classify_segment(segment, prohibited_categories=prohibited_categories)
        for segment in segments
    )
