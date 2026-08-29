"""Controlled Signal Intelligence source registry.

Authority is derived from registered source_id / source_type only.
Display names, follower counts, and engagement never grant authority.
Social accounts stay TIER 4 discovery even when independently confirmed
events become VERIFIED via a different authoritative source.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional

from services.signal_intelligence_contract import (
    SOURCE_ANALYST,
    SOURCE_EXCHANGE_DISCLOSURE,
    SOURCE_FINANCIAL_PUBLICATION,
    SOURCE_ISSUER_FILING,
    SOURCE_KAP,
    SOURCE_NEWSWIRE,
    SOURCE_OFFICIAL_IR,
    SOURCE_OTHER,
    SOURCE_REGULATOR,
    SOURCE_RESEARCH,
    SOURCE_SEC,
    SOURCE_SOCIAL_FORUM,
    SOURCE_SOCIAL_OTHER,
    SOURCE_SOCIAL_REDDIT,
    SOURCE_SOCIAL_X,
    SOURCE_TYPES,
    TIER_1_PRIMARY,
    TIER_1_SOURCE_TYPES,
    TIER_2_HIGH_QUALITY_SECONDARY,
    TIER_2_SOURCE_TYPES,
    TIER_3_SECONDARY_ANALYSIS,
    TIER_3_SOURCE_TYPES,
    TIER_4_SOCIAL_DISCOVERY,
    TIER_4_SOURCE_TYPES,
)


@dataclass(frozen=True)
class SourceRegistration:
    source_id: str
    source_type: str
    authority: str
    display_name: str
    discovery_only: bool = False


# Named social accounts of interest. Discovery / context only.
SOCIAL_DISCOVERY_ACCOUNTS: tuple[SourceRegistration, ...] = (
    SourceRegistration("x:bugra_kurtoglu", SOURCE_SOCIAL_X, TIER_4_SOCIAL_DISCOVERY, "@bugra_kurtoglu", True),
    SourceRegistration("x:bist_katilim", SOURCE_SOCIAL_X, TIER_4_SOCIAL_DISCOVERY, "@bist_katilim", True),
    SourceRegistration("x:hkhhedefportfoy", SOURCE_SOCIAL_X, TIER_4_SOCIAL_DISCOVERY, "@HKHHedefPortfoy", True),
    SourceRegistration("x:fbcfon", SOURCE_SOCIAL_X, TIER_4_SOCIAL_DISCOVERY, "@fbcfon", True),
    SourceRegistration("x:itfo_", SOURCE_SOCIAL_X, TIER_4_SOCIAL_DISCOVERY, "@itfo_", True),
)

_PRIMARY: tuple[SourceRegistration, ...] = (
    SourceRegistration("sec", SOURCE_SEC, TIER_1_PRIMARY, "SEC EDGAR"),
    SourceRegistration("kap", SOURCE_KAP, TIER_1_PRIMARY, "KAP"),
    SourceRegistration("issuer_filing", SOURCE_ISSUER_FILING, TIER_1_PRIMARY, "Issuer regulatory filing"),
    SourceRegistration("exchange_disclosure", SOURCE_EXCHANGE_DISCLOSURE, TIER_1_PRIMARY, "Exchange disclosure"),
    SourceRegistration("official_ir", SOURCE_OFFICIAL_IR, TIER_1_PRIMARY, "Official issuer IR"),
    SourceRegistration("regulator", SOURCE_REGULATOR, TIER_1_PRIMARY, "Official regulator"),
    SourceRegistration("newswire", SOURCE_NEWSWIRE, TIER_2_HIGH_QUALITY_SECONDARY, "Major financial newswire"),
    SourceRegistration("financial_publication", SOURCE_FINANCIAL_PUBLICATION, TIER_2_HIGH_QUALITY_SECONDARY, "Established financial publication"),
    SourceRegistration("research", SOURCE_RESEARCH, TIER_3_SECONDARY_ANALYSIS, "Research commentary"),
    SourceRegistration("analyst", SOURCE_ANALYST, TIER_3_SECONDARY_ANALYSIS, "Analyst commentary"),
)

SOURCE_REGISTRY: Mapping[str, SourceRegistration] = {
    item.source_id: item for item in (*_PRIMARY, *SOCIAL_DISCOVERY_ACCOUNTS)
}


def normalize_source_type(source_type: Optional[str]) -> str:
    text = str(source_type or "").strip().upper()
    if text in SOURCE_TYPES:
        return text
    return SOURCE_OTHER


def authority_for_source_type(source_type: Optional[str]) -> str:
    normalized = normalize_source_type(source_type)
    if normalized in TIER_1_SOURCE_TYPES:
        return TIER_1_PRIMARY
    if normalized in TIER_2_SOURCE_TYPES:
        return TIER_2_HIGH_QUALITY_SECONDARY
    if normalized in TIER_3_SOURCE_TYPES:
        return TIER_3_SECONDARY_ANALYSIS
    if normalized in TIER_4_SOURCE_TYPES:
        return TIER_4_SOCIAL_DISCOVERY
    return TIER_4_SOCIAL_DISCOVERY


def resolve_source(source_id: Optional[str], source_type: Optional[str] = None) -> SourceRegistration:
    key = str(source_id or "").strip().lower()
    registered = SOURCE_REGISTRY.get(key)
    if registered is not None:
        return registered
    normalized_type = normalize_source_type(source_type)
    return SourceRegistration(
        source_id=key or "unknown",
        source_type=normalized_type,
        authority=authority_for_source_type(normalized_type),
        display_name=key or "unknown",
        discovery_only=normalized_type in TIER_4_SOURCE_TYPES,
    )


def is_social_source(source_type: Optional[str]) -> bool:
    return normalize_source_type(source_type) in TIER_4_SOURCE_TYPES
