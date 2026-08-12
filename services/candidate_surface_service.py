from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional

NON_EQUITY_ASSET_TYPES = frozenset({
    "ETF",
    "FON",
    "FUND",
    "SUKUK",
})

NON_EQUITY_SECURITY_TYPES = frozenset({
    "ETF",
    "FON",
    "FUND",
})

NON_EQUITY_ISSUER_CATEGORIES = frozenset({
    "FUND",
    "SPECIAL_SECURITY",
})

CLASSIFICATION_FIELDS = (
    "asset_type",
    "is_etf",
    "issuer_category",
    "security_type",
)


def _normalize_token(value: Any) -> str:
    return str(value or "").strip().upper()


def is_equity_candidate_surface_eligible(
    candidate: Optional[Mapping[str, Any]],
) -> bool:
    """Return True when a candidate row may appear in equity-oriented UI surfaces."""
    if not candidate:
        return False

    if candidate.get("is_etf") is True:
        return False

    asset_type = _normalize_token(candidate.get("asset_type"))
    if asset_type in NON_EQUITY_ASSET_TYPES:
        return False

    security_type = _normalize_token(candidate.get("security_type"))
    if security_type in NON_EQUITY_SECURITY_TYPES:
        return False

    issuer_category = _normalize_token(candidate.get("issuer_category"))
    if issuer_category in NON_EQUITY_ISSUER_CATEGORIES:
        return False

    return True


def _classification_field_missing(
    candidate: Mapping[str, Any],
    field: str,
) -> bool:
    if field not in candidate or candidate.get(field) is None:
        return True
    if field == "is_etf":
        return False
    return not str(candidate.get(field) or "").strip()


def needs_classification_backfill(candidate: Optional[Mapping[str, Any]]) -> bool:
    if not candidate:
        return False
    symbol = str(candidate.get("symbol") or "").strip().upper()
    if not symbol:
        return False
    return any(
        _classification_field_missing(candidate, field)
        for field in CLASSIFICATION_FIELDS
    )


def enrich_candidate_classification(
    candidate: Optional[Mapping[str, Any]],
    persisted: Optional[Mapping[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not candidate:
        return None
    enriched = dict(candidate)
    if not persisted:
        return enriched

    for field in CLASSIFICATION_FIELDS:
        if not _classification_field_missing(enriched, field):
            continue
        if field not in persisted or persisted.get(field) is None:
            continue
        if field != "is_etf" and not str(persisted.get(field) or "").strip():
            continue
        enriched[field] = persisted[field]

    return enriched


def enrich_candidate_classification_from_db(
    candidate: Optional[Mapping[str, Any]],
    get_by_symbol,
) -> Optional[Dict[str, Any]]:
    if not candidate:
        return None
    if not needs_classification_backfill(candidate):
        return dict(candidate)

    symbol = str(candidate.get("symbol") or "").strip().upper()
    if not symbol:
        return dict(candidate)

    persisted = get_by_symbol(symbol)
    return enrich_candidate_classification(candidate, persisted)


def filter_equity_candidate_surface(
    candidates: Iterable[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    return [
        dict(candidate)
        for candidate in candidates
        if is_equity_candidate_surface_eligible(candidate)
    ]
