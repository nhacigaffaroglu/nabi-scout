"""Deterministic KAP fund-page slug from official fund code + official title.

The slug is derived from the same fund's official KAP title, not by fuzzy
matching across funds. Identity matching remains fund-code only.
"""

from __future__ import annotations

import re

from services.official_kap_pdr import _fold
from services.official_tefas import normalize_fund_code

_NON_SLUG = re.compile(r"[^a-z0-9]+")


def kap_official_slug(fund_code: str, official_title: str) -> str:
    code = normalize_fund_code(fund_code).lower()
    title = _NON_SLUG.sub("-", _fold(official_title)).strip("-")
    if not code or not title:
        return ""
    return f"{code}-{title}"


def kap_ozet_url(fund_code: str, official_title: str) -> str:
    slug = kap_official_slug(fund_code, official_title)
    if not slug:
        return ""
    return f"https://www.kap.org.tr/tr/fon-bilgileri/ozet/{slug}"


def kap_genel_url(fund_code: str, official_title: str) -> str:
    slug = kap_official_slug(fund_code, official_title)
    if not slug:
        return ""
    return f"https://www.kap.org.tr/tr/fon-bilgileri/genel/{slug}"
