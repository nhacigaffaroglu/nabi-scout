"""REIT / real_estate evidence. No name, SPRE, or mandate inference.

instrument_type=REIT is the current Security Master slot that maps to
economic real_estate. U.S. listing evidence currently writes EQUITY for
common stock with a CIK, including names that contain REIT.

Until legal form and economic layer are separate fields, and lookthrough
can join official SEDOL/CUSIP rather than ticker-only holdings, REIT
facts must not be persisted. OpenFIGI securityType=REIT may be recorded
as a probe observation only.
"""

from __future__ import annotations

from typing import Any

from services.security_master_contract import (
    INSTRUMENT_EQUITY,
    INSTRUMENT_REIT,
    INSTRUMENT_UNKNOWN,
    SOURCE_US_LISTING,
)

EXPLICIT_REIT_TYPES = frozenset({"REIT", "REIT EQUITY"})

# Listing EQUITY is not silently replaced. REIT ingest stays closed.
REIT_MODEL_GAP = True
REIT_MODEL_GAP_REASON = (
    "instrument_type cannot hold both legal common-stock form and economic "
    "real_estate; lookthrough resolves persisted ticker, not official SEDOL/"
    "CUSIP; us_listing EQUITY must not be overwritten."
)
PERSIST_OPENFIGI_REIT = False

INSUFFICIENT_ALONE = frozenset(
    {
        "SPRE",
        "REIT",
        "REALTY",
        "REAL ESTATE",
        "PROPERTY",
        "PROPERTIES",
        "GAYRIMENKUL",
    }
)


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().upper().replace("_", " ").split())


def is_explicit_structured_reit(*values: Any) -> bool:
    for value in values:
        if _norm(value) in EXPLICIT_REIT_TYPES:
            return True
    return False


def name_is_not_evidence(security_name: Any) -> bool:
    del security_name
    return True


def spre_membership_is_not_evidence(fund_symbol: Any) -> bool:
    del fund_symbol
    return True


def classify_from_name_or_fund(*_args: Any, **_kwargs: Any) -> str:
    """Forbidden path. Always UNKNOWN."""
    return INSTRUMENT_UNKNOWN


def listing_equity_is_not_reit(instrument_type: Any, *, source: Any = None) -> bool:
    """True when a listing EQUITY fact must remain EQUITY."""
    if str(instrument_type or "").strip().upper() != INSTRUMENT_EQUITY:
        return False
    if source is None:
        return True
    return str(source or "").strip() == SOURCE_US_LISTING


def may_persist_reit_fact() -> bool:
    return (not REIT_MODEL_GAP) and PERSIST_OPENFIGI_REIT


def persist_blocked_reason() -> str:
    if REIT_MODEL_GAP:
        return REIT_MODEL_GAP_REASON
    if not PERSIST_OPENFIGI_REIT:
        return "OPENFIGI_REIT_PERSIST_DISABLED"
    return ""
