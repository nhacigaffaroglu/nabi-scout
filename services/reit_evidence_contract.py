"""REIT / real_estate evidence. No name, SPRE, or mandate inference.

instrument_type remains a legal/listing fact. OpenFIGI securityType=REIT
may establish economic_layer=real_estate through SecurityIdentityService.
It must not overwrite us_listing EQUITY with instrument_type=REIT.
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

# Instrument REIT writes stay closed. Economic real_estate may persist.
REIT_MODEL_GAP = False
REIT_INSTRUMENT_PERSIST = False
PERSIST_OPENFIGI_REIT = False
PERSIST_OPENFIGI_REIT_ECONOMIC = True
REIT_MODEL_GAP_REASON = ""
REIT_INSTRUMENT_BLOCK_REASON = (
    "instrument_type=REIT is not written; listing EQUITY is preserved and "
    "economic_layer=real_estate is stored separately."
)

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
    return False


def may_persist_reit_economic() -> bool:
    return PERSIST_OPENFIGI_REIT_ECONOMIC and not REIT_INSTRUMENT_PERSIST


def persist_blocked_reason() -> str:
    return REIT_INSTRUMENT_BLOCK_REASON


def persist_economic_blocked_reason() -> str:
    if not PERSIST_OPENFIGI_REIT_ECONOMIC:
        return "OPENFIGI_REIT_ECONOMIC_PERSIST_DISABLED"
    if REIT_INSTRUMENT_PERSIST:
        return "INSTRUMENT_REIT_PERSIST_MUST_STAY_OFF"
    return ""
