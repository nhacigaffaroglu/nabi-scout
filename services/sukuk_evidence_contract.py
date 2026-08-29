"""Explicit instrument-type evidence. No name, mandate, or SPSK inference.

A security is SUKUK only when a structured fact says so. Membership in SPSK,
issuer geography, coupon shape, or the words certificate/trust/finance are
not evidence.
"""

from __future__ import annotations

from typing import Any, Optional

from services.security_master_contract import (
    INSTRUMENT_FIXED_INCOME,
    INSTRUMENT_SUKUK,
    INSTRUMENT_UNKNOWN,
)

EXPLICIT_SUKUK_TYPES = frozenset(
    {
        "SUKUK",
        "ISLAMIC SUKUK",
        "SUKUK CERTIFICATE",
    }
)
EXPLICIT_FIXED_INCOME_TYPES = frozenset(
    {
        "FIXED_INCOME",
        "FIXED INCOME",
        "BOND",
        "GOVERNMENT BOND",
        "CORPORATE BOND",
        "NOTE",
        "TREASURY",
    }
)

INSUFFICIENT_ALONE = frozenset(
    {
        "SPSK",
        "CERTIFICATE",
        "TRUST",
        "FINANCE",
        "ISLAMIC BOND",
        "ISLAMIC",
        "COUPON",
        "MATURITY",
    }
)


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().upper().replace("_", " ").split())


def explicit_instrument_from_structured_type(value: Any) -> Optional[str]:
    """Return SUKUK / FIXED_INCOME only for structured type tokens."""
    text = _norm(value)
    if not text:
        return None
    compact = text.replace(" ", "_")
    if text in EXPLICIT_SUKUK_TYPES or compact == "SUKUK":
        return INSTRUMENT_SUKUK
    if text in EXPLICIT_FIXED_INCOME_TYPES or compact in {
        "FIXED_INCOME",
        "FIXEDINCOME",
    }:
        return INSTRUMENT_FIXED_INCOME
    return None


def name_is_not_evidence(security_name: Any) -> bool:
    """Names never classify. Exposed so tests can lock the rule."""
    del security_name
    return True


def spsk_membership_is_not_evidence(fund_symbol: Any) -> bool:
    del fund_symbol
    return True


def classify_from_name_or_fund(*_args: Any, **_kwargs: Any) -> str:
    """Forbidden path. Always UNKNOWN."""
    return INSTRUMENT_UNKNOWN


def evidence_is_explicit(instrument_type: Any, *, structured_type: Any = None) -> bool:
    resolved = explicit_instrument_from_structured_type(structured_type)
    if resolved is None:
        return False
    return str(instrument_type or "").strip().upper() == resolved
