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

# Warrant series suffixes only; bare P/U/R/W matching catches normal tickers
# such as SAP, COP, ACIW, and ACIU.
COMPOUND_SYMBOL_SUFFIXES = (
    "WS",
    "WT",
)

COMMON_STOCK_TERMS = (
    "common stock",
    "common shares",
    "ordinary shares",
    "ordinary share",
    "class a",
    "class b",
    "american depositary",
    "adr",
    "ads",
    "depositary receipt",
)

SPECIAL_SYMBOL_PATTERN = re.compile(
    r"(?:[.-][WURP](?:[RST])?)$"
)


def _has_special_symbol_suffix(symbol_text: str) -> bool:
    if SPECIAL_SYMBOL_PATTERN.search(symbol_text):
        return True

    for suffix in COMPOUND_SYMBOL_SUFFIXES:
        if (
            symbol_text.endswith(suffix)
            and len(symbol_text) > len(suffix) + 2
        ):
            return True

    return False


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
            "issuer_category": "FUND",
        }

    for pattern in EXCLUDED_NAME_PATTERNS:
        if re.search(pattern, name_text):
            return {
                "security_type": "EXCLUDED",
                "is_investable_common": False,
                "exclude_reason": f"Name pattern: {pattern}",
                "issuer_category": "SPECIAL_SECURITY",
            }

    if _has_special_symbol_suffix(symbol_text):
        return {
            "security_type": "POSSIBLE_SPECIAL_SECURITY",
            "is_investable_common": False,
            "exclude_reason": "Special security suffix",
            "issuer_category": "SPECIAL_SECURITY",
        }

    if any(term in name_text for term in COMMON_STOCK_TERMS):
        return {
            "security_type": "COMMON_STOCK",
            "is_investable_common": True,
            "exclude_reason": None,
            "issuer_category": "OPERATING_COMPANY",
        }

    return {
        "security_type": "COMMON_STOCK",
        "is_investable_common": True,
        "exclude_reason": None,
        "issuer_category": "OPERATING_COMPANY",
    }
