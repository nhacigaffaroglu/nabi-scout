"""Positive U.S. listing evidence for Security Master.

Nasdaq ETF Y/N + SEC CIK join + existing eligibility filters.
Name/suffix exclusions are filters, not positive REIT/sukuk proof.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from services.security_master_contract import INSTRUMENT_EQUITY, INSTRUMENT_ETF
from services.universe_listing_identity import (
    excluded_instrument_reason,
    listing_identity,
    normalize_us_exchange,
)


def listing_instrument_type(row: Mapping[str, Any]) -> Optional[str]:
    """Return EQUITY or ETF only when structured listing evidence proves it."""
    identity = listing_identity(row.get("symbol") or row.get("ticker"))
    if not identity:
        return None
    is_etf = bool(row.get("is_etf"))
    company_name = row.get("company_name") or row.get("name") or ""
    exchange_security_name = row.get("exchange_security_name") or ""
    if is_etf:
        return INSTRUMENT_ETF
    reason = excluded_instrument_reason(
        symbol=identity,
        company_name=company_name,
        exchange_security_name=exchange_security_name,
        is_etf=False,
    )
    if reason:
        return None
    if not str(row.get("cik") or "").strip():
        return None
    return INSTRUMENT_EQUITY


def listing_index_key(row: Mapping[str, Any]) -> str:
    return listing_identity(row.get("symbol") or row.get("ticker"))


def listing_exchange(row: Mapping[str, Any]) -> str:
    return normalize_us_exchange(row.get("exchange"))
