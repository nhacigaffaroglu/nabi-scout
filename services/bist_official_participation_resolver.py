"""Deterministic official BIST evidence resolver. Shadow only. No persist."""

from __future__ import annotations

from typing import Iterable, Optional

from services.bist_katilim_tum_contract import (
    MEMBERSHIP_MEMBER,
    MEMBERSHIP_SOURCE_UNAVAILABLE,
    BistKatilimMembership,
    BistKatilimTumSnapshot,
)
from services.bist_katilim_tum_parser import canonicalize_bist_series_code
from services.bist_official_participation_contract import (
    EVIDENCE_INCOMPLETE,
    EVIDENCE_OFFICIAL_ELIGIBILITY,
    EVIDENCE_UNAVAILABLE,
    LIMITATION_READ_ONLY,
    PERIOD_COMPARABLE,
    PERIOD_MISMATCH,
    PERIOD_UNKNOWN,
    SHADOW_IDENTITY_REJECTED,
    SHADOW_INSUFFICIENT,
    SHADOW_METHODOLOGY_DECISION_REQUIRED,
    SHADOW_NOT_COMPUTED,
    BistKatilimUniverseAudit,
    BistOfficialParticipationEvidence,
)
from services.bist_symbol_mapping import canonical_bist_identity
from services.kap_kafif_contract import KapKafifDocument
from services.security_master_contract import SOURCE_BIST


def _identity_is_bist(symbol: str, identity_source: str) -> bool:
    if str(identity_source or "").strip() == SOURCE_BIST:
        return True
    return canonical_bist_identity(symbol) is not None


def compare_kafif_to_financial_period(
    kafif: Optional[KapKafifDocument],
    *,
    financial_period: str = "",
    financial_period_end: str = "",
) -> str:
    if kafif is None:
        return PERIOD_UNKNOWN
    if not financial_period:
        return PERIOD_UNKNOWN
    kafif_period = str(kafif.period or "").upper()
    report_period = str(financial_period or "").upper()
    if kafif_period and kafif_period == report_period:
        if financial_period_end and kafif.financial_year and financial_period_end.startswith(kafif.financial_year):
            return PERIOD_COMPARABLE
        if not financial_period_end:
            return PERIOD_COMPARABLE
    if {kafif_period, report_period} == {"FY", "YTD"}:
        return PERIOD_MISMATCH
    if kafif_period and report_period and kafif_period != report_period:
        return PERIOD_MISMATCH
    return PERIOD_UNKNOWN


def resolve_official_bist_participation_evidence(
    *,
    symbol: str,
    identity_source: str,
    membership: Optional[BistKatilimMembership],
    kafif: Optional[KapKafifDocument],
    financial_period: str = "",
    financial_period_end: str = "",
) -> BistOfficialParticipationEvidence:
    canon = canonicalize_bist_series_code(symbol)
    if not _identity_is_bist(canon, identity_source):
        return BistOfficialParticipationEvidence(
            symbol=canon,
            identity_source=identity_source,
            membership=None,
            kafif=None,
            official_eligibility=EVIDENCE_UNAVAILABLE,
            kafif_evidence_complete=False,
            nabi_participation_shadow=SHADOW_IDENTITY_REJECTED,
            period_vs_financial_report=PERIOD_UNKNOWN,
            limitation="BIST membership/KAFİF evidence rejects non-BIST identity.",
            persisted=False,
        )

    period_vs = compare_kafif_to_financial_period(
        kafif,
        financial_period=financial_period,
        financial_period_end=financial_period_end,
    )
    kafif_complete = bool(kafif is not None and kafif.complete)
    source_down = membership is not None and membership.status == MEMBERSHIP_SOURCE_UNAVAILABLE
    if source_down and kafif is None:
        official = EVIDENCE_UNAVAILABLE
        shadow = SHADOW_INSUFFICIENT
    elif membership is not None and membership.status == MEMBERSHIP_MEMBER and kafif_complete:
        official = EVIDENCE_OFFICIAL_ELIGIBILITY
        # Existing NABI methodology does not authorize BIST/KAFİF to emit Uygun.
        shadow = SHADOW_METHODOLOGY_DECISION_REQUIRED
    else:
        official = EVIDENCE_INCOMPLETE
        shadow = SHADOW_INSUFFICIENT

    return BistOfficialParticipationEvidence(
        symbol=canon,
        identity_source=identity_source or SOURCE_BIST,
        membership=membership,
        kafif=kafif,
        official_eligibility=official,
        kafif_evidence_complete=kafif_complete,
        nabi_participation_shadow=shadow,
        period_vs_financial_report=period_vs,
        financial_report_period=financial_period,
        limitation=LIMITATION_READ_ONLY,
        persisted=False,
        provenance={
            "official_vs_nabi_not_collapsed": True,
            "nabi_status_not_persisted": True,
            "shadow": SHADOW_NOT_COMPUTED if shadow != SHADOW_METHODOLOGY_DECISION_REQUIRED else shadow,
        },
    )


def audit_katilim_universe(
    snapshot: BistKatilimTumSnapshot,
    security_master_symbols: Iterable[str],
) -> BistKatilimUniverseAudit:
    known = {canonicalize_bist_series_code(item) for item in security_master_symbols if item}
    matched: list[str] = []
    unmatched: list[str] = []
    issues: list[str] = []
    for member in snapshot.members:
        if member.series_code.endswith(".E") and member.symbol != canonicalize_bist_series_code(member.series_code):
            issues.append(f"normalization:{member.series_code}")
        if member.symbol in known:
            matched.append(member.symbol)
        else:
            unmatched.append(member.symbol)
    return BistKatilimUniverseAudit(
        member_count=len(snapshot.members),
        matched_security_master=tuple(sorted(matched)),
        unmatched_symbols=tuple(sorted(unmatched)),
        normalization_issues=tuple(issues),
    )
