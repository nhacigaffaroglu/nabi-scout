"""Controlled approved cohort for US Security Intelligence refresh.

This module defines the production-approved refresh boundary.
Adding a symbol here is an explicit production scope change.
"""

from __future__ import annotations

from typing import Iterable


APPROVED_US_SI_REFRESH_COHORT: tuple[str, ...] = ("CRM", "ADBE", "MU", "BIIB")

MAX_APPROVED_US_SI_REFRESH_COHORT = 10


def approved_us_si_refresh_symbols() -> tuple[str, ...]:
    """Return the immutable approved US SI refresh cohort."""
    return APPROVED_US_SI_REFRESH_COHORT


def validate_approved_us_si_refresh_cohort(
    symbols: Iterable[str] | None = None,
) -> tuple[str, ...]:
    """Validate and normalize the controlled production cohort."""
    raw = tuple(
        str(symbol).strip().upper()
        for symbol in (
            APPROVED_US_SI_REFRESH_COHORT
            if symbols is None
            else symbols
        )
        if str(symbol).strip()
    )

    if not raw:
        raise ValueError("approved US SI refresh cohort is empty")

    if len(raw) > MAX_APPROVED_US_SI_REFRESH_COHORT:
        raise ValueError(
            "approved US SI refresh cohort exceeds "
            f"{MAX_APPROVED_US_SI_REFRESH_COHORT} symbols"
        )

    if len(set(raw)) != len(raw):
        raise ValueError("approved US SI refresh cohort contains duplicates")

    for symbol in raw:
        if not symbol.replace(".", "").replace("-", "").isalnum():
            raise ValueError(
                f"invalid approved US SI refresh symbol: {symbol}"
            )

    return raw
