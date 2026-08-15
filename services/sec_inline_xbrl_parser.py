from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

_REVENUE_CONCEPT_PATTERNS = (
    re.compile(r"revenuefromcontractwithcustomer", re.I),
    re.compile(r"salesrevenue", re.I),
    re.compile(r"^revenues?$", re.I),
    re.compile(r"revenuefromexternal", re.I),
)

_CONSOLIDATED_DENOMINATOR_PATTERNS = (
    re.compile(r"revenuefromcontractwithcustomerexcludingassessedtax", re.I),
    re.compile(r"^revenues?$", re.I),
    re.compile(r"salesrevenuenet", re.I),
)

_AXIS_PRIORITY = (
    "StatementBusinessSegmentsAxis",
    "ProductOrServiceAxis",
    "StatementGeographicalAxis",
)

_ANNUAL_MIN_DAYS = 300
_ANNUAL_MAX_DAYS = 430


@dataclass(frozen=True)
class InlineXbrlFact:
    concept: str
    context_id: str
    unit_ref: str
    raw_value: str
    normalized_value: Optional[float]
    scale: int
    decimals: Optional[str]
    format_attr: str
    element_tag: str

    @property
    def concept_local(self) -> str:
        return self.concept.split(":")[-1] if self.concept else ""


@dataclass(frozen=True)
class InlineXbrlContext:
    context_id: str
    entity: str
    period_start: Optional[str]
    period_end_date: Optional[str]
    instant: Optional[str]
    dimensions: Tuple[Tuple[str, str], ...]

    @property
    def is_annual(self) -> bool:
        if self.instant:
            return True
        if not self.period_start or not self.period_end_date:
            return False
        try:
            days = (
                date.fromisoformat(self.period_end_date[:10])
                - date.fromisoformat(self.period_start[:10])
            ).days
        except ValueError:
            return False
        return _ANNUAL_MIN_DAYS <= days <= _ANNUAL_MAX_DAYS

    @property
    def period_end(self) -> Optional[str]:
        if self.period_end_date:
            return self.period_end_date[:10]
        if self.instant:
            return self.instant[:10]
        return None

    def axis_member(self, axis_local: str) -> Optional[str]:
        for axis, member in self.dimensions:
            if axis.split(":")[-1] == axis_local:
                return member
        return None

    @property
    def has_segment_dimension(self) -> bool:
        return bool(self.dimensions)


@dataclass(frozen=True)
class ParsedInlineXbrlDocument:
    contexts: Dict[str, InlineXbrlContext]
    units: Dict[str, str]
    facts: Tuple[InlineXbrlFact, ...]
    labels: Dict[str, str]


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    if ":" in tag:
        return tag.rsplit(":", 1)[-1]
    return tag


def _parse_numeric(raw: str, *, scale: int = 0, is_negative: bool = False) -> Optional[float]:
    text = str(raw or "").strip()
    if not text or text in {"—", "-", "–"}:
        return None
    text = text.replace(",", "").replace(" ", "")
    if text.startswith("(") and text.endswith(")"):
        text = text[1:-1]
        is_negative = True
    try:
        value = float(text)
    except ValueError:
        return None
    if scale:
        value *= 10 ** scale
    if is_negative:
        value = -value
    return value


def _extract_attribute(element: ET.Element, name: str, default: str = "") -> str:
    for key, value in element.attrib.items():
        if _local_name(key) == name:
            return str(value)
    return default


def _parse_contexts(root: ET.Element) -> Dict[str, InlineXbrlContext]:
    contexts: Dict[str, InlineXbrlContext] = {}
    for element in root.iter():
        if _local_name(element.tag) != "context":
            continue
        context_id = _extract_attribute(element, "id")
        if not context_id:
            continue
        entity = ""
        period_start = None
        period_end = None
        instant = None
        dimensions: list[tuple[str, str]] = []
        for child in element.iter():
            tag = _local_name(child.tag)
            if tag == "identifier":
                entity = (child.text or "").strip()
            elif tag == "startDate" and child.text:
                period_start = child.text.strip()
            elif tag == "endDate" and child.text:
                period_end = child.text.strip()
            elif tag == "instant" and child.text:
                instant = child.text.strip()
            elif tag == "explicitMember":
                dim = _extract_attribute(child, "dimension")
                member = (child.text or "").strip()
                if dim and member:
                    dimensions.append((dim, member))
        contexts[context_id] = InlineXbrlContext(
            context_id=context_id,
            entity=entity,
            period_start=period_start,
            period_end_date=period_end,
            instant=instant,
            dimensions=tuple(dimensions),
        )
    return contexts


def _parse_units(root: ET.Element) -> Dict[str, str]:
    units: Dict[str, str] = {}
    for element in root.iter():
        if _local_name(element.tag) != "unit":
            continue
        unit_id = _extract_attribute(element, "id")
        if not unit_id:
            continue
        for child in element.iter():
            if _local_name(child.tag) == "measure" and child.text:
                units[unit_id] = child.text.strip()
                break
    return units


def _parse_labels(root: ET.Element) -> Dict[str, str]:
    labels: Dict[str, str] = {}
    for element in root.iter():
        if _local_name(element.tag) != "label":
            continue
        label_id = _extract_attribute(element, "label")
        role = _extract_attribute(element, "role")
        text = (element.text or "").strip()
        if not label_id or not text:
            continue
        if "terse" in role.lower() or "label" in role.lower() or label_id not in labels:
            labels[label_id] = text
    return labels


def _parse_facts(root: ET.Element) -> Tuple[InlineXbrlFact, ...]:
    facts: list[InlineXbrlFact] = []
    for element in root.iter():
        tag = _local_name(element.tag)
        if tag not in {"nonFraction", "nonNumeric"}:
            continue
        if tag != "nonFraction":
            continue
        concept = _extract_attribute(element, "name")
        context_id = _extract_attribute(element, "contextRef")
        unit_ref = _extract_attribute(element, "unitRef")
        scale_text = _extract_attribute(element, "scale") or "0"
        decimals = _extract_attribute(element, "decimals") or None
        format_attr = _extract_attribute(element, "format")
        sign = _extract_attribute(element, "sign")
        raw_value = (element.text or "").strip()
        if not concept or not context_id:
            continue
        try:
            scale = int(scale_text)
        except ValueError:
            scale = 0
        is_negative = sign == "-"
        normalized = _parse_numeric(raw_value, scale=scale, is_negative=is_negative)
        facts.append(
            InlineXbrlFact(
                concept=concept,
                context_id=context_id,
                unit_ref=unit_ref,
                raw_value=raw_value,
                normalized_value=normalized,
                scale=scale,
                decimals=decimals,
                format_attr=format_attr,
                element_tag=tag,
            )
        )
    return tuple(facts)


def parse_inline_xbrl_document(content: bytes | str) -> ParsedInlineXbrlDocument:
    text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else content
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        wrapped = f"<root>{text}</root>"
        root = ET.fromstring(wrapped)
    contexts = _parse_contexts(root)
    units = _parse_units(root)
    labels = _parse_labels(root)
    facts = _parse_facts(root)
    return ParsedInlineXbrlDocument(
        contexts=contexts,
        units=units,
        facts=facts,
        labels=labels,
    )


def _concept_matches(patterns: Sequence[re.Pattern[str]], concept_local: str) -> bool:
    return any(pattern.search(concept_local) for pattern in patterns)


def _member_label(member: str, labels: Mapping[str, str]) -> str:
    if not member:
        return ""
    if member in labels:
        return labels[member]
    local = member.split(":")[-1]
    if local.endswith("Member"):
        local = local[: -len("Member")]
    cleaned = re.sub(r"([a-z])([A-Z])", r"\1 \2", local)
    cleaned = re.sub(r"and", " and ", cleaned, flags=re.I)
    cleaned = cleaned.replace("_", " ").replace("-", " ")
    return " ".join(cleaned.split())


def _currency_from_unit(unit_ref: str, units: Mapping[str, str]) -> str:
    measure = units.get(unit_ref) or ""
    if measure.startswith("iso4217:"):
        return measure.split(":", 1)[-1]
    if measure.startswith("USD"):
        return "USD"
    return "USD"


def is_revenue_concept(concept_local: str) -> bool:
    return _concept_matches(_REVENUE_CONCEPT_PATTERNS, concept_local)


def is_denominator_concept(concept_local: str) -> bool:
    return _concept_matches(_CONSOLIDATED_DENOMINATOR_PATTERNS, concept_local)


def select_target_period_end(
    contexts: Mapping[str, InlineXbrlContext],
    *,
    preferred_end: Optional[str] = None,
) -> Optional[str]:
    annual_ends: list[str] = []
    for context in contexts.values():
        if not context.is_annual:
            continue
        end = context.period_end
        if end:
            annual_ends.append(end[:10])
    if not annual_ends:
        return preferred_end
    if preferred_end:
        preferred = preferred_end[:10]
        if preferred in annual_ends:
            return preferred
    return max(annual_ends)


def deduplicate_facts(
    facts: Sequence[InlineXbrlFact],
    contexts: Mapping[str, InlineXbrlContext],
) -> Tuple[InlineXbrlFact, ...]:
    grouped: Dict[tuple, list[InlineXbrlFact]] = {}
    for fact in facts:
        context = contexts.get(fact.context_id)
        if context is None:
            continue
        member_key = tuple(context.dimensions)
        key = (
            fact.concept_local.lower(),
            fact.context_id,
            member_key,
            fact.unit_ref,
        )
        grouped.setdefault(key, []).append(fact)

    selected: list[InlineXbrlFact] = []
    for key, group in grouped.items():
        if len(group) == 1:
            selected.append(group[0])
            continue
        values = {item.normalized_value for item in group if item.normalized_value is not None}
        if len(values) > 1:
            continue
        selected.append(group[0])
    return tuple(selected)


def conflicting_duplicate_keys(
    facts: Sequence[InlineXbrlFact],
    contexts: Mapping[str, InlineXbrlContext],
) -> Tuple[tuple, ...]:
    grouped: Dict[tuple, set] = {}
    for fact in facts:
        context = contexts.get(fact.context_id)
        if context is None:
            continue
        key = (
            fact.concept_local.lower(),
            fact.context_id,
            tuple(context.dimensions),
            fact.unit_ref,
        )
        if fact.normalized_value is None:
            continue
        grouped.setdefault(key, set()).add(fact.normalized_value)
    return tuple(key for key, values in grouped.items() if len(values) > 1)
