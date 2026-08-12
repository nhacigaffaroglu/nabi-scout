from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class BusinessRulesRegistryError(ValueError):
    pass


@dataclass(frozen=True)
class KeywordPattern:
    pattern: str
    category: str


@dataclass(frozen=True)
class RevenueRuleDefinition:
    rule_id: str
    category: str
    numerator_categories: Tuple[str, ...]
    denominator_field: str
    threshold_pct: float
    comparator: str
    linked_registry_rule_id: str


@dataclass(frozen=True)
class MethodologyBusinessRules:
    methodology_id: str
    version: str
    business_screen_complete_methodology: bool
    prohibited_categories: Tuple[str, ...]
    revenue_rules: Tuple[RevenueRuleDefinition, ...]
    sector_rule_id: str
    description_rule_id: str
    sic_rule_id: str


@dataclass(frozen=True)
class SharedKeywordPolicy:
    negation_patterns: Tuple[str, ...]
    fail_patterns: Tuple[KeywordPattern, ...]
    review_patterns: Tuple[KeywordPattern, ...]


@dataclass(frozen=True)
class StructuredSectorLabels:
    definitive: Dict[str, Tuple[str, ...]]
    review_required: Dict[str, Tuple[str, ...]]


@dataclass(frozen=True)
class BusinessRulesRegistry:
    version: str
    shared_keyword_policy: SharedKeywordPolicy
    structured_sector_labels: StructuredSectorLabels
    methodologies: Dict[str, MethodologyBusinessRules]


@dataclass(frozen=True)
class SicMappingEntry:
    category: str
    description: str
    match_strength: str = "review_required"
    sic_code: Optional[str] = None
    sic_range_start: Optional[str] = None
    sic_range_end: Optional[str] = None


_BUSINESS_RULES_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "participation_business_rules.json"
)
_SIC_MAPPING_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "participation_sic_mapping.json"
)


def _parse_keyword_patterns(raw_items: List[Dict[str, Any]]) -> Tuple[KeywordPattern, ...]:
    return tuple(
        KeywordPattern(
            pattern=str(item["pattern"]).lower(),
            category=str(item["category"]),
        )
        for item in raw_items
    )


def _parse_revenue_rules(raw_items: List[Dict[str, Any]]) -> Tuple[RevenueRuleDefinition, ...]:
    return tuple(
        RevenueRuleDefinition(
            rule_id=str(item["rule_id"]),
            category=str(item["category"]),
            numerator_categories=tuple(str(c) for c in item.get("numerator_categories") or ()),
            denominator_field=str(item["denominator_field"]),
            threshold_pct=float(item["threshold_pct"]),
            comparator=str(item["comparator"]),
            linked_registry_rule_id=str(item["linked_registry_rule_id"]),
        )
        for item in raw_items
    )


def _parse_methodology_business_rules(
    methodology_id: str,
    raw: Dict[str, Any],
) -> MethodologyBusinessRules:
    return MethodologyBusinessRules(
        methodology_id=methodology_id,
        version=str(raw.get("version") or ""),
        business_screen_complete_methodology=bool(
            raw.get("business_screen_complete_methodology", False)
        ),
        prohibited_categories=tuple(str(c) for c in raw.get("prohibited_categories") or ()),
        revenue_rules=_parse_revenue_rules(raw.get("revenue_rules") or []),
        sector_rule_id=str(raw.get("sector_rule_id") or f"{methodology_id}.sector_exclusions"),
        description_rule_id=str(
            raw.get("description_rule_id") or f"{methodology_id}.description_keywords"
        ),
        sic_rule_id=str(raw.get("sic_rule_id") or f"{methodology_id}.sic_exclusions"),
    )


@lru_cache(maxsize=1)
def load_business_rules_registry() -> BusinessRulesRegistry:
    try:
        payload = json.loads(_BUSINESS_RULES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BusinessRulesRegistryError(
            f"Unable to load business rules registry: {_BUSINESS_RULES_PATH}"
        ) from exc

    keyword_raw = payload.get("shared_keyword_policy") or {}
    shared_keyword_policy = SharedKeywordPolicy(
        negation_patterns=tuple(str(p).lower() for p in keyword_raw.get("negation_patterns") or ()),
        fail_patterns=_parse_keyword_patterns(keyword_raw.get("fail_patterns") or []),
        review_patterns=_parse_keyword_patterns(keyword_raw.get("review_patterns") or []),
    )
    structured_raw = payload.get("structured_sector_labels") or {}
    definitive: dict[str, tuple[str, ...]] = {}
    review_required: dict[str, tuple[str, ...]] = {}
    for category, labels in structured_raw.items():
        if isinstance(labels, dict):
            definitive[str(category)] = tuple(
                str(label).lower() for label in labels.get("definitive") or ()
            )
            review_required[str(category)] = tuple(
                str(label).lower() for label in labels.get("review_required") or ()
            )
        else:
            definitive[str(category)] = tuple(str(label).lower() for label in labels)
    structured_sector_labels = StructuredSectorLabels(
        definitive=definitive,
        review_required=review_required,
    )
    methodologies = {
        str(methodology_id): _parse_methodology_business_rules(methodology_id, raw)
        for methodology_id, raw in (payload.get("methodologies") or {}).items()
    }
    return BusinessRulesRegistry(
        version=str(payload.get("version") or ""),
        shared_keyword_policy=shared_keyword_policy,
        structured_sector_labels=structured_sector_labels,
        methodologies=methodologies,
    )


@lru_cache(maxsize=1)
def load_sic_mappings() -> Tuple[SicMappingEntry, ...]:
    try:
        payload = json.loads(_SIC_MAPPING_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BusinessRulesRegistryError(
            f"Unable to load SIC mapping registry: {_SIC_MAPPING_PATH}"
        ) from exc

    entries: list[SicMappingEntry] = []
    for raw in payload.get("mappings") or []:
        sic_range = raw.get("sic_range") or {}
        entries.append(
            SicMappingEntry(
                category=str(raw["category"]),
                description=str(raw.get("description") or ""),
                match_strength=str(raw.get("match_strength") or "review_required"),
                sic_code=str(raw["sic_code"]) if raw.get("sic_code") is not None else None,
                sic_range_start=str(sic_range["start"]) if sic_range.get("start") else None,
                sic_range_end=str(sic_range["end"]) if sic_range.get("end") else None,
            )
        )
    return tuple(entries)


def get_methodology_business_rules(methodology_id: str) -> Optional[MethodologyBusinessRules]:
    registry = load_business_rules_registry()
    return registry.methodologies.get(methodology_id)


def resolve_sic_mapping(sic_code: Optional[str]) -> Optional[Tuple[str, str]]:
    if sic_code is None:
        return None
    normalized = str(sic_code).strip()
    if not normalized:
        return None
    normalized = normalized.zfill(4) if normalized.isdigit() else normalized

    for entry in load_sic_mappings():
        if entry.sic_code is not None and entry.sic_code.zfill(4) == normalized.zfill(4):
            return entry.category, entry.match_strength
        if entry.sic_range_start and entry.sic_range_end and normalized.isdigit():
            start = int(entry.sic_range_start)
            end = int(entry.sic_range_end)
            code_int = int(normalized)
            if start <= code_int <= end:
                return entry.category, entry.match_strength
    return None


def resolve_sic_category(sic_code: Optional[str]) -> Optional[str]:
    mapping = resolve_sic_mapping(sic_code)
    return mapping[0] if mapping is not None else None
