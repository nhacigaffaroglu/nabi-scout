from __future__ import annotations

CONFIGURED_PARTICIPATION_CATALOG: dict[str, tuple[str, int]] = {
    "SPUS": ("Uygun", 100),
    "HLAL": ("Uygun", 100),
    "SPSK": ("Uygun", 100),
}

CATALOG_NAME = "CONFIGURED_PARTICIPATION_CATALOG"


def normalize_catalog_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper()


def is_configured_participation_symbol(symbol: str) -> bool:
    return normalize_catalog_symbol(symbol) in CONFIGURED_PARTICIPATION_CATALOG


def configured_participation_for_symbol(symbol: str) -> tuple[str, int] | None:
    return CONFIGURED_PARTICIPATION_CATALOG.get(normalize_catalog_symbol(symbol))
