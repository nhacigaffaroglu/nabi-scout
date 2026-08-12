from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class MethodologyRegistryError(ValueError):
    pass


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


_REGISTRY_PATH = (
    Path(__file__).resolve().parent.parent
    / "config"
    / "participation_methodologies"
    / "registry.json"
)


def _parse_rule(raw: Dict[str, Any]) -> MethodologyRuleDefinition:
    threshold = raw.get("threshold_pct")
    return MethodologyRuleDefinition(
        rule_id=str(raw["rule_id"]),
        screen=str(raw.get("screen") or ""),
        numerator=str(raw.get("numerator") or ""),
        denominator=str(raw.get("denominator") or ""),
        threshold_pct=float(threshold) if threshold is not None else None,
        comparator=raw.get("comparator"),
        measurement_period=raw.get("measurement_period"),
        notes=raw.get("notes"),
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
    ids = [item.methodology_id for item in parsed]
    if len(set(ids)) != len(ids):
        raise MethodologyRegistryError("Methodology IDs must be unique.")
    for item in parsed:
        if not item.version:
            raise MethodologyRegistryError(
                f"Methodology {item.methodology_id} missing version."
            )
    return parsed


def list_methodologies() -> List[MethodologyDefinition]:
    return list(_load_methodologies())


def get_methodology(methodology_id: str) -> Optional[MethodologyDefinition]:
    normalized = str(methodology_id or "").strip()
    if not normalized:
        return None
    for item in _load_methodologies():
        if item.methodology_id == normalized:
            return item
    return None


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
