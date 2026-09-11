"""FUND17B explicit portfolio-context bridge.

Transforms a human-approved, research-only portfolio context source into the
exact FUND17 portfolio context contract.

No portfolio reads, no implicit Wealth OS access, no scoring, no ranking,
no recommendation, no trades/orders, and no production persistence.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping


INPUT_SCHEMA = "fund17b_portfolio_context_source_1"
OUTPUT_SCHEMA = "fund17_portfolio_context_1"


class PortfolioContextBridgeError(ValueError):
    """Fail-closed FUND17B contract violation."""


def _as_dict(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PortfolioContextBridgeError(f"{field}_must_be_object")
    return dict(value)


def _as_string_list(value: Any, *, field: str) -> list[str]:
    if not isinstance(value, list):
        raise PortfolioContextBridgeError(f"{field}_must_be_list")

    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise PortfolioContextBridgeError(f"{field}_item_must_be_string")
        clean = item.strip()
        if not clean:
            raise PortfolioContextBridgeError(f"{field}_item_empty")
        out.append(clean)
    return out


def _validate_as_of(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PortfolioContextBridgeError("as_of_invalid")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PortfolioContextBridgeError("as_of_invalid") from exc
    return value


def build_fund17_portfolio_context(
    source_context: Mapping[str, Any],
) -> dict[str, Any]:
    source = _as_dict(source_context, field="source_context")

    if source.get("schema_version") != INPUT_SCHEMA:
        raise PortfolioContextBridgeError("unsupported_source_schema")

    if source.get("human_approved") is not True:
        raise PortfolioContextBridgeError("source_not_human_approved")

    if source.get("research_only") is not True:
        raise PortfolioContextBridgeError("source_research_only_not_true")

    if source.get("execution_authority") is not False:
        raise PortfolioContextBridgeError(
            "source_execution_authority_not_false"
        )

    if source.get("production_persist") is not False:
        raise PortfolioContextBridgeError(
            "source_production_persist_not_false"
        )

    source_system = source.get("source_system")
    if not isinstance(source_system, str) or not source_system.strip():
        raise PortfolioContextBridgeError("source_system_invalid")

    _validate_as_of(source.get("as_of"))

    desired_roles = _as_string_list(
        source.get("desired_roles"),
        field="desired_roles",
    )
    existing_exposures = _as_string_list(
        source.get("existing_exposures"),
        field="existing_exposures",
    )
    constraints = _as_string_list(
        source.get("constraints"),
        field="constraints",
    )

    if not desired_roles:
        raise PortfolioContextBridgeError("desired_roles_empty")
    if not existing_exposures:
        raise PortfolioContextBridgeError("existing_exposures_empty")
    if not constraints:
        raise PortfolioContextBridgeError("constraints_empty")

    notes = source.get("notes")
    if notes is not None and not isinstance(notes, str):
        raise PortfolioContextBridgeError("notes_must_be_string_or_null")

    return {
        "schema_version": OUTPUT_SCHEMA,
        "human_supplied": True,
        "research_only": True,
        "execution_authority": False,
        "desired_roles": desired_roles,
        "existing_exposures": existing_exposures,
        "constraints": constraints,
        "notes": notes,
    }
