"""Bridge BIST business facts into existing Participation business inputs.

Does not evaluate or persist a Participation verdict. Does not fill sector
from a single segment. US symbols are refused.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable, Optional

from services.bist_business_contract import (
    BistBusinessBundle,
    BistParticipationReadiness,
    BistRawBusinessSegment,
    BistRawBusinessTotals,
    READINESS_COMPLETE,
    READINESS_NONE,
    READINESS_PARTIAL,
)
from services.bist_business_normalization import normalize_bist_business
from services.participation_business_contract import (
    BusinessActivityEvidence,
    BusinessRevenueEvidence,
)
from services.participation_financial_contract import ParticipationFinancialInputs
from services.participation_intelligence_contract import CONFIDENCE_HIGH, CONFIDENCE_LOW
from services.security_master_contract import RESOLUTION_RESOLVED, SOURCE_BIST
from services.security_master_service import SecurityMasterService


FINAL_PARTICIPATION_DISABLED = "FINAL_PARTICIPATION_DISABLED_NO_LIVE_OFFICIAL_EVIDENCE"


class BistBusinessIdentityError(ValueError):
    """BIST business facts require a resolved bist_listing identity."""


def resolve_bist_business_identity(
    symbol: str,
    *,
    security_master: Optional[SecurityMasterService] = None,
) -> Any:
    master = security_master or SecurityMasterService()
    resolution = master.resolve_security(symbol)
    if resolution.status != RESOLUTION_RESOLVED or resolution.source != SOURCE_BIST:
        raise BistBusinessIdentityError(
            f"{symbol} is not a resolved bist_listing identity; BIST business facts are refused."
        )
    return resolution


def build_bist_business_bundle(
    symbol: str,
    segments: Iterable[BistRawBusinessSegment],
    totals: Optional[BistRawBusinessTotals],
    *,
    security_master: Optional[SecurityMasterService] = None,
) -> BistBusinessBundle:
    resolution = resolve_bist_business_identity(symbol, security_master=security_master)
    return normalize_bist_business(
        symbol=resolution.identifier,
        identity_source=SOURCE_BIST,
        segments=segments,
        totals=totals,
    )


def _as_of_date(raw: Optional[str]) -> Optional[date]:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def business_evidence_from_bist(bundle: BistBusinessBundle) -> BusinessActivityEvidence:
    """Existing BusinessActivityEvidence only. No screen. No company-wide sector guess."""
    warnings: list[str] = []
    if bundle.unknown_revenue is not None or bundle.unknown_share is not None:
        warnings.append("Unknown segment revenue remains visible and is not renormalized.")
    if bundle.limitation:
        warnings.append(bundle.limitation)
    segments = tuple(
        BusinessRevenueEvidence(
            category=item.canonical_category,
            segment_name=item.segment_name,
            revenue_value=item.revenue,
            revenue_pct=item.revenue_share,
            source=item.source,
            source_date=_as_of_date(item.as_of),
            confidence=CONFIDENCE_HIGH
            if item.mapping_rule == "EXPLICIT_CODE_MAP"
            else CONFIDENCE_LOW,
        )
        for item in bundle.segments
    )
    refs = [
        ("identity", bundle.identity_source),
        ("mapping", "bist_business_code_map"),
    ]
    if bundle.source_document_id:
        refs.append(("source_document", bundle.source_document_id))
    compatible_total = all(
        item.revenue is None or item.revenue_share is not None for item in bundle.segments
    )
    return BusinessActivityEvidence(
        symbol=bundle.symbol,
        reported_total_revenue=bundle.total_revenue if compatible_total else None,
        revenue_segments=segments,
        source=bundle.source,
        source_date=_as_of_date(bundle.as_of),
        evidence_refs=tuple(refs),
        warnings=tuple(warnings),
    )


def _financial_readiness(inputs: Optional[ParticipationFinancialInputs]) -> str:
    if inputs is None:
        return READINESS_NONE
    present = [
        inputs.total_revenue,
        inputs.total_assets,
        inputs.total_debt,
        inputs.cash,
    ]
    filled = sum(1 for item in present if item is not None)
    if filled == 0:
        return READINESS_NONE
    if filled < 4 or inputs.non_permissible_revenue is None:
        return READINESS_PARTIAL
    return READINESS_COMPLETE


def combine_bist_participation_readiness(
    *,
    symbol: str,
    identity_source: str,
    financial_inputs: Optional[ParticipationFinancialInputs] = None,
    business_bundle: Optional[BistBusinessBundle] = None,
) -> BistParticipationReadiness:
    financial = _financial_readiness(financial_inputs)
    business = business_bundle.readiness if business_bundle is not None else READINESS_NONE
    return BistParticipationReadiness(
        symbol=symbol,
        identity_source=identity_source,
        financial_input_readiness=financial,
        business_input_readiness=business,
        final_participation_ready=False,
        limitation=FINAL_PARTICIPATION_DISABLED,
    )
