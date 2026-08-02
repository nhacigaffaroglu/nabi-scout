from __future__ import annotations

import re
from typing import Dict


EXCLUDED_NAME_PATTERNS = (
    r"\bacquisition\b",
    r"\bblank check\b",
    r"\bspac\b",
    r"\bwarrant(s)?\b",
    r"\bunit(s)?\b",
    r"\bright(s)?\b",
    r"\bpreferred\b",
    r"\bdepositary share(s)?\b",
    r"\bnote(s)? due\b",
    r"\bbond(s)?\b",
    r"\bdebenture(s)?\b",
)

EXCLUDED_SYMBOL_SUFFIXES = (
    "W",
    "WS",
    "WT",
    "U",
    "R",
    "P",
)

COMMON_STOCK_TERMS = (
    "common stock",
    "common shares",
    "ordinary shares",
    "class a",
    "class b",
)


def classify_security(
    *,
    symbol: str,
    company_name: str | None,
    is_etf: bool = False,
) -> Dict[str, object]:
    symbol_text = (symbol or "").strip().upper()
    name_text = (company_name or "").strip().lower()

    if is_etf:
        return {
            "security_type": "ETF",
            "is_investable_common": False,
            "exclude_reason": None,
        }

    for pattern in EXCLUDED_NAME_PATTERNS:
        if re.search(pattern, name_text):
            return {
                "security_type": "EXCLUDED",
                "is_investable_common": False,
                "exclude_reason": f"Name pattern: {pattern}",
            }

    if any(
        symbol_text.endswith(suffix)
        for suffix in EXCLUDED_SYMBOL_SUFFIXES
    ):
        return {
            "security_type": "POSSIBLE_SPECIAL_SECURITY",
            "is_investable_common": False,
            "exclude_reason": "Special security suffix",
        }

    if any(term in name_text for term in COMMON_STOCK_TERMS):
        return {
            "security_type": "COMMON_STOCK",
            "is_investable_common": True,
            "exclude_reason": None,
        }

    return {
        "security_type": "COMMON_STOCK",
        "is_investable_common": True,
        "exclude_reason": None,
    }
