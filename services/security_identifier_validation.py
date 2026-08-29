"""Mechanical identifier validation. No instrument-type inference.

A CUSIP column value is not a CUSIP until check-digit evidence says so.
SEDOL-shaped text is not a SEDOL until the check digit matches.
Ticker-shaped text is not a listing ticker without format evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

USABILITY_VALID_CUSIP = "VALID_CUSIP"
USABILITY_VALID_SEDOL = "VALID_SEDOL"
USABILITY_VALID_ISIN = "VALID_ISIN"
USABILITY_LISTING_TICKER = "LISTING_TICKER"
USABILITY_UNVERIFIED = "UNVERIFIED_IDENTIFIER"
USABILITY_MISSING = "MISSING"

# Typical U.S. listing ticker: 1–5 alphanumerics, optional share-class suffix.
_LISTING_TICKER_RE = re.compile(r"^[A-Z]{1,5}(?:-[A-Z]{1,2})?$")
_SEDOL_CHARS = re.compile(r"^[0-9BCDFGHJKLMNPQRSTVWXYZ]{7}$")
_CUSIP_CHARS = re.compile(r"^[0-9A-Z*@#]{9}$")
_ISIN_CHARS = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")


@dataclass(frozen=True)
class IdentifierAssessment:
    raw: str
    usability: str
    identifier: Optional[str]
    identifier_type: Optional[str]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw": self.raw,
            "usability": self.usability,
            "identifier": self.identifier,
            "identifier_type": self.identifier_type,
            "reason": self.reason,
        }


def _normalize(raw: Any) -> str:
    return str(raw or "").strip().upper().replace(" ", "")


def cusip_check_digit(body8: str) -> Optional[str]:
    text = _normalize(body8)
    if len(text) != 8:
        return None
    total = 0
    for index, char in enumerate(text):
        if char.isdigit():
            value = int(char)
        elif char.isalpha():
            value = ord(char) - 55
        elif char == "*":
            value = 36
        elif char == "@":
            value = 37
        elif char == "#":
            value = 38
        else:
            return None
        if index % 2 == 1:
            value *= 2
        total += value // 10 + value % 10
    return str((10 - (total % 10)) % 10)


def is_valid_cusip(raw: Any) -> bool:
    text = _normalize(raw)
    if not _CUSIP_CHARS.fullmatch(text):
        return False
    expected = cusip_check_digit(text[:8])
    return expected is not None and expected == text[8]


def sedol_check_digit(body6: str) -> Optional[str]:
    text = _normalize(body6)
    if len(text) != 6 or not re.fullmatch(r"[0-9BCDFGHJKLMNPQRSTVWXYZ]{6}", text):
        return None
    weights = (1, 3, 1, 7, 3, 9)
    total = 0
    for char, weight in zip(text, weights):
        value = int(char) if char.isdigit() else ord(char) - 55
        total += value * weight
    return str((10 - (total % 10)) % 10)


def is_valid_sedol(raw: Any) -> bool:
    text = _normalize(raw)
    if not _SEDOL_CHARS.fullmatch(text):
        return False
    expected = sedol_check_digit(text[:6])
    return expected is not None and expected == text[6]


def _isin_digit_string(text: str) -> Optional[str]:
    digits = []
    for char in text:
        if char.isdigit():
            digits.append(char)
        elif char.isalpha():
            digits.append(str(ord(char) - 55))
        else:
            return None
    return "".join(digits)


def isin_check_digit(body11: str) -> Optional[str]:
    text = _normalize(body11)
    if len(text) != 11:
        return None
    expanded = _isin_digit_string(text)
    if expanded is None:
        return None
    total = 0
    reverse = list(reversed(expanded))
    for index, char in enumerate(reverse):
        value = int(char)
        if index % 2 == 0:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return str((10 - (total % 10)) % 10)


def is_valid_isin(raw: Any) -> bool:
    text = _normalize(raw)
    if not _ISIN_CHARS.fullmatch(text):
        return False
    expected = isin_check_digit(text[:11])
    return expected is not None and expected == text[11]


def is_listing_ticker_format(raw: Any) -> bool:
    text = _normalize(raw).replace(".", "-")
    if not text or not _LISTING_TICKER_RE.fullmatch(text):
        return False
    if is_valid_sedol(text) or is_valid_cusip(text) or is_valid_isin(text):
        return False
    return True


def assess_identifier(raw: Any) -> IdentifierAssessment:
    text = _normalize(raw)
    if not text:
        return IdentifierAssessment("", USABILITY_MISSING, None, None, "EMPTY")
    if is_valid_isin(text):
        return IdentifierAssessment(text, USABILITY_VALID_ISIN, text, "ISIN", "ISIN_CHECK_DIGIT")
    if is_valid_cusip(text):
        return IdentifierAssessment(text, USABILITY_VALID_CUSIP, text, "CUSIP", "CUSIP_CHECK_DIGIT")
    if is_valid_sedol(text):
        return IdentifierAssessment(text, USABILITY_VALID_SEDOL, text, "SEDOL", "SEDOL_CHECK_DIGIT")
    if is_listing_ticker_format(text):
        return IdentifierAssessment(
            text.replace(".", "-"),
            USABILITY_LISTING_TICKER,
            text.replace(".", "-"),
            "TICKER",
            "LISTING_TICKER_FORMAT",
        )
    return IdentifierAssessment(text, USABILITY_UNVERIFIED, None, None, "NO_FORMAT_EVIDENCE")


def assess_official_holding_identifiers(
    *,
    ticker: Any,
    cusip_raw: Any,
) -> IdentifierAssessment:
    """Prefer CUSIP-column check-digit, then ticker-column check-digit/format.

    The official CUSIP column is not trusted as CUSIP without validation.
    """
    cusip = assess_identifier(cusip_raw)
    if cusip.usability in {
        USABILITY_VALID_CUSIP,
        USABILITY_VALID_SEDOL,
        USABILITY_VALID_ISIN,
    }:
        return cusip
    ticker_assessment = assess_identifier(ticker)
    if ticker_assessment.usability != USABILITY_MISSING:
        if cusip.usability == USABILITY_UNVERIFIED and ticker_assessment.usability == USABILITY_UNVERIFIED:
            return IdentifierAssessment(
                _normalize(cusip_raw) or _normalize(ticker),
                USABILITY_UNVERIFIED,
                None,
                None,
                "NO_FORMAT_EVIDENCE",
            )
        return ticker_assessment
    if cusip.usability == USABILITY_MISSING:
        return cusip
    return cusip
