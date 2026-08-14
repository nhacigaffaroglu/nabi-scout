from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class MethodologyRegistryError(ValueError):
    pass


@dataclass(frozen=True)
class MethodologySourceDocument:
    title: str
    url: str
    published: Optional[str] = None
    notes: Optional[str] = None


@dataclass(frozen=True)
class MethodologyRuleDefinition:
    rule_id: str
    screen: str
    numerator: str
    denominator: str
    threshold_pct: Optional[float]
    comparator: Optional[str]
    measurement_period: Optional[str]
    notes: Optional[str] = None
    entry_buffer_pct: Optional[float] = None
    financial_ratio_threshold_pct: Optional[float] = None
    exit_buffer_pct: Optional[float] = None
    screening_context_thresholds: Tuple[Tuple[str, float], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class MethodologyDefinition:
    methodology_id: str
    label: str
    version: str
    asset_scope: Tuple[str, ...]
    source_reference: str
    denominator_policy: str
    notes: str
    financial_screen_complete_methodology: bool = False
    rules: Tuple[MethodologyRuleDefinition, ...] = field(default_factory=tuple)
    active: bool = True
    archived: bool = False
    effective_date: Optional[str] = None
    implementation_review: Optional[str] = None
    default_screening_context: str = "NEW_ENTRY"
    source_documents: Tuple[MethodologySourceDocument, ...] = field(default_factory=tuple)


_REGISTRY_PATH = (
    Path(__file__).resolve().parent.parent
    / "config"
    / "participation_methodologies"
    / "registry.json"
)


def _parse_source_documents(raw_items: Any) -> Tuple[MethodologySourceDocument, ...]:
    if not isinstance(raw_items, list):
        return ()
    documents: list[MethodologySourceDocument] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        if not title or not url:
            continue
        documents.append(
            MethodologySourceDocument(
                title=title,
                url=url,
                published=str(item["published"]).strip() if item.get("published") else None,
                notes=str(item["notes"]).strip() if item.get("notes") else None,
            )
        )
    return tuple(documents)


def _parse_rule(raw: Dict[str, Any]) -> MethodologyRuleDefinition:
    threshold = raw.get("threshold_pct")
    context_thresholds = raw.get("screening_context_thresholds") or {}
    parsed_context_thresholds = tuple(
        (str(context), float(value))
        for context, value in context_thresholds.items()
        if value is not None
    )
    return MethodologyRuleDefinition(
        rule_id=str(raw["rule_id"]),
        screen=str(raw.get("screen") or ""),
        numerator=str(raw.get("numerator") or ""),
        denominator=str(raw.get("denominator") or ""),
        threshold_pct=float(threshold) if threshold is not None else None,
        comparator=raw.get("comparator"),
        measurement_period=raw.get("measurement_period"),
        notes=raw.get("notes"),
        entry_buffer_pct=(
            float(raw["entry_buffer_pct"]) if raw.get("entry_buffer_pct") is not None else None
        ),
        financial_ratio_threshold_pct=(
            float(raw["financial_ratio_threshold_pct"])
            if raw.get("financial_ratio_threshold_pct") is not None
            else None
        ),
        exit_buffer_pct=(
            float(raw["exit_buffer_pct"]) if raw.get("exit_buffer_pct") is not None else None
        ),
        screening_context_thresholds=parsed_context_thresholds,
    )


def _parse_methodology(raw: Dict[str, Any]) -> MethodologyDefinition:
    rules = tuple(_parse_rule(item) for item in raw.get("rules") or [])
    return MethodologyDefinition(
        methodology_id=str(raw["methodology_id"]),
        label=str(raw.get("label") or raw["methodology_id"]),
        version=str(raw.get("version") or ""),
        asset_scope=tuple(str(item) for item in raw.get("asset_scope") or ()),
        source_reference=str(raw.get("source_reference") or ""),
        denominator_policy=str(raw.get("denominator_policy") or ""),
        notes=str(raw.get("notes") or ""),
        financial_screen_complete_methodology=bool(
            raw.get("financial_screen_complete_methodology", False)
        ),
        rules=rules,
        active=bool(raw.get("active", True)),
        archived=bool(raw.get("archived", False)),
        effective_date=str(raw["effective_date"]).strip() if raw.get("effective_date") else None,
        implementation_review=(
            str(raw["implementation_review"]).strip()
            if raw.get("implementation_review")
            else None
        ),
        default_screening_context=str(raw.get("default_screening_context") or "NEW_ENTRY"),
        source_documents=_parse_source_documents(raw.get("source_documents")),
    )


@lru_cache(maxsize=1)
def _load_registry_payload() -> Dict[str, Any]:
    try:
        payload = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise MethodologyRegistryError(
            f"Methodology registry not found: {_REGISTRY_PATH}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise MethodologyRegistryError(
            "Methodology registry JSON is invalid."
        ) from exc
    if not isinstance(payload, dict):
        raise MethodologyRegistryError("Methodology registry root must be an object.")
    return payload


@lru_cache(maxsize=1)
def _load_methodologies() -> Tuple[MethodologyDefinition, ...]:
    payload = _load_registry_payload()
    raw_items = payload.get("methodologies")
    if not isinstance(raw_items, list) or not raw_items:
        raise MethodologyRegistryError("Methodology registry must list methodologies.")

    parsed = tuple(_parse_methodology(item) for item in raw_items)
    keys = [(item.methodology_id, item.version) for item in parsed]
    if len(set(keys)) != len(keys):
        raise MethodologyRegistryError("Methodology id+version pairs must be unique.")
    for item in parsed:
        if not item.version:
            raise MethodologyRegistryError(
                f"Methodology {item.methodology_id} missing version."
            )
    return parsed


def get_default_equity_methodology_version() -> str:
    payload = _load_registry_payload()
    default_version = str(payload.get("default_equity_methodology_version") or "").strip()
    if not default_version:
        raise MethodologyRegistryError("default_equity_methodology_version is not configured.")
    return default_version


def get_methodology(
    methodology_id: str,
    *,
    version: Optional[str] = None,
) -> Optional[MethodologyDefinition]:
    normalized = str(methodology_id or "").strip()
    if not normalized:
        return None
    if version is not None:
        target_version = str(version).strip()
        for item in _load_methodologies():
            if item.methodology_id == normalized and item.version == target_version:
                return item
        return None

    payload = _load_registry_payload()
    default_id = str(payload.get("default_equity_methodology_id") or "").strip()
    if normalized == default_id:
        target_version = get_default_equity_methodology_version()
        for item in _load_methodologies():
            if item.methodology_id == normalized and item.version == target_version:
                return item
        return None

    active_matches = [
        item
        for item in _load_methodologies()
        if item.methodology_id == normalized and item.active
    ]
    if len(active_matches) == 1:
        return active_matches[0]
    if active_matches:
        return active_matches[0]
    for item in _load_methodologies():
        if item.methodology_id == normalized:
            return item
    return None


def list_methodologies(*, include_archived: bool = False) -> List[MethodologyDefinition]:
    items = list(_load_methodologies())
    if include_archived:
        return items
    return [item for item in items if item.active and not item.archived]


def list_methodology_versions(methodology_id: str) -> Tuple[MethodologyDefinition, ...]:
    normalized = str(methodology_id or "").strip()
    return tuple(
        item for item in _load_methodologies() if item.methodology_id == normalized
    )


def get_default_equity_methodology_id() -> str:
    payload = _load_registry_payload()
    default_id = str(payload.get("default_equity_methodology_id") or "").strip()
    if not default_id:
        raise MethodologyRegistryError("default_equity_methodology_id is not configured.")
    if get_methodology(default_id) is None:
        raise MethodologyRegistryError(
            f"default_equity_methodology_id is unknown: {default_id}"
        )
    return default_id


def get_default_equity_methodology() -> MethodologyDefinition:
    methodology = get_methodology(get_default_equity_methodology_id())
    if methodology is None:
        raise MethodologyRegistryError("Default equity methodology is not available.")
    return methodology


def clear_registry_cache_for_tests() -> None:
    _load_registry_payload.cache_clear()
    _load_methodologies.cache_clear()
