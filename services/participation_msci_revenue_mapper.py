from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Tuple

from services.participation_revenue_attribution_contract import (
    MAPPING_AMBIGUOUS,
    MAPPING_DEFENSIBLE,
    MAPPING_DIRECT,
    MAPPING_NO_MATCH,
    PROHIBITED_MAPPING_STATUSES,
)

_MAPPING_PATH = (
    Path(__file__).resolve().parent.parent
    / "config"
    / "participation_msci_revenue_mapping.json"
)


@dataclass(frozen=True)
class MSCIRevenueMappingResult:
    mapping_status: str
    msci_category: str
    rule_id: str
    rationale: str


@dataclass(frozen=True)
class _MappingRule:
    rule_id: str
    pattern: str
    msci_category: str
    mapping_status: str
    rationale: str


def _normalize_label(text: str) -> str:
    lowered = str(text or "").strip().lower()
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return " ".join(lowered.split())


@lru_cache(maxsize=1)
def _load_mapping_rules() -> Tuple[Tuple[_MappingRule, ...], Tuple[_MappingRule, ...], Tuple[_MappingRule, ...]]:
    payload = json.loads(_MAPPING_PATH.read_text(encoding="utf-8"))
    prohibited = tuple(
        _MappingRule(
            rule_id=str(item["rule_id"]),
            pattern=str(item["pattern"]).lower(),
            msci_category=str(item.get("msci_category") or ""),
            mapping_status=str(item["mapping_status"]),
            rationale=str(item.get("rationale") or ""),
        )
        for item in payload.get("prohibited_rules") or ()
    )
    no_match = tuple(
        _MappingRule(
            rule_id=str(item["rule_id"]),
            pattern=str(item["pattern"]).lower(),
            msci_category=str(item.get("msci_category") or ""),
            mapping_status=MAPPING_NO_MATCH,
            rationale=str(item.get("rationale") or ""),
        )
        for item in payload.get("no_match_rules") or ()
    )
    ambiguous = tuple(
        _MappingRule(
            rule_id=str(item["rule_id"]),
            pattern=str(item["pattern"]).lower(),
            msci_category="",
            mapping_status=MAPPING_AMBIGUOUS,
            rationale=str(item.get("rationale") or ""),
        )
        for item in payload.get("ambiguous_patterns") or ()
    )
    return prohibited, no_match, ambiguous


def map_revenue_member_to_msci(
    reported_label: str,
    *,
    methodology_version: str = "2025-05",
    prohibited_categories: Sequence[str] = (),
) -> MSCIRevenueMappingResult:
    normalized = _normalize_label(reported_label)
    if not normalized:
        return MSCIRevenueMappingResult(
            mapping_status=MAPPING_AMBIGUOUS,
            msci_category="",
            rule_id="msci.rev.unlabeled",
            rationale="Revenue member label is empty.",
        )

    prohibited_rules, no_match_rules, ambiguous_rules = _load_mapping_rules()

    for rule in ambiguous_rules:
        if rule.pattern in normalized:
            return MSCIRevenueMappingResult(
                mapping_status=MAPPING_AMBIGUOUS,
                msci_category="",
                rule_id=rule.rule_id,
                rationale=rule.rationale,
            )

    for rule in prohibited_rules:
        if rule.pattern not in normalized:
            continue
        if prohibited_categories and rule.msci_category not in prohibited_categories:
            if rule.msci_category:
                continue
        return MSCIRevenueMappingResult(
            mapping_status=rule.mapping_status,
            msci_category=rule.msci_category,
            rule_id=rule.rule_id,
            rationale=rule.rationale,
        )

    for rule in no_match_rules:
        if rule.pattern in normalized:
            return MSCIRevenueMappingResult(
                mapping_status=MAPPING_NO_MATCH,
                msci_category="",
                rule_id=rule.rule_id,
                rationale=rule.rationale,
            )

    return MSCIRevenueMappingResult(
        mapping_status=MAPPING_AMBIGUOUS,
        msci_category="",
        rule_id="msci.rev.unmapped",
        rationale="Revenue member could not be mapped deterministically under MSCI taxonomy.",
    )


def is_prohibited_mapping(result: MSCIRevenueMappingResult) -> bool:
    return result.mapping_status in PROHIBITED_MAPPING_STATUSES and bool(result.msci_category)
