"""Hand official KAP business evidence into existing BIST business facts.

Does not persist a Participation verdict. Does not change 8E / SI / US.
"""

from __future__ import annotations

from typing import Iterable, Optional

from services.bist_business_bridge import (
    build_bist_business_bundle,
    business_evidence_from_bist,
    combine_bist_participation_readiness,
)
from services.bist_business_contract import (
    BIST_BUSINESS_SOURCE_OFFICIAL,
    BistBusinessBundle,
    BistRawBusinessSegment,
    BistRawBusinessTotals,
)
from services.kap_financial_normalization import period_compatibility
from services.kap_public_business_contract import (
    COVERAGE_CURRENCY_MISMATCH,
    COVERAGE_MISSING_FINANCIAL_TOTAL,
    COVERAGE_OK,
    COVERAGE_PERIOD_INCOMPATIBLE,
    GAP_AVAILABLE_FROM_PUBLIC_KAP,
    GAP_METHODOLOGY_UNRESOLVED,
    GAP_REQUIRES_OTHER_PUBLIC_SOURCE,
    PARTICIPATION_FINANCIAL_GAP_FIELDS,
    SHADOW_RESULT_KIND,
    KapBusinessScreenShadow,
    KapFinancialGap,
    KapPublicBusinessDocument,
    KapPublicRevenueCoverage,
)
from services.participation_business_engine import evaluate_business_activity
from services.participation_financial_contract import ParticipationFinancialInputs
from services.security_intelligence_contract import PERIOD_INCOMPATIBLE
from services.security_master_contract import SOURCE_BIST
from services.security_master_service import SecurityMasterService


# Observed on public KAP FR pages. Not mapped into Participation this sprint.
_AR_CONCEPTS = (
    "ifrs-full_CurrentTradeReceivables",
    "ifrs-full_NoncurrentTradeReceivables",
)
_CASH_CONCEPTS = ("ifrs-full_CashAndCashEquivalents",)
_SECURITY_CONCEPTS = (
    "kap-fr_OtherCurrentFinancialInvestments",
    "kap-fr_CurrentFinancialAssetsMeasuredAtAmortisedCost",
    "ifrs-full_CurrentFinancialAssetsAtFairValueThroughProfitOrLoss",
)
_BORROWING_CONCEPTS = (
    "ifrs-full_LongtermBorrowings",
    "kap-fr_CurrentBorrowingsFromUnrelatedParties",
    "kap-fr_CurrentPortionOfNoncurrentBorrowings",
    "kap-fr_LongTermBorrowingsFromUnrelatedParties",
)


def _present(observed: Iterable[str], candidates: Iterable[str]) -> tuple[str, ...]:
    have = {item.lower() for item in observed}
    return tuple(item for item in candidates if item.lower() in have)


def _scaled(raw: Optional[float], scale: Optional[int]) -> Optional[float]:
    if raw is None:
        return None
    if scale in {None, 0}:
        return raw
    return raw * scale


def raw_segments_from_public(
    document: KapPublicBusinessDocument,
) -> tuple[tuple[BistRawBusinessSegment, ...], Optional[BistRawBusinessTotals]]:
    """BistRawBusinessSegment handoff. No category mapping."""
    segments = tuple(
        BistRawBusinessSegment(
            symbol=document.symbol,
            issuer_id=document.disclosure_id,
            segment_code=None,
            segment_name=item.segment_name,
            raw_category=item.breakdown_kind,
            revenue=_scaled(item.raw_revenue, item.unit_scale or document.unit_scale),
            currency=item.currency or document.currency,
            period=item.period or document.period,
            period_end=item.period_end or document.period_end,
            source=BIST_BUSINESS_SOURCE_OFFICIAL,
            source_document_id=item.source_document_id or document.disclosure_id,
            as_of=item.period_end or document.period_end,
            provenance={
                **dict(item.provenance or {}),
                "source_url": item.source_url or document.source_url,
                "location": item.location,
                "raw_revenue": item.raw_revenue,
                "unit_scale": item.unit_scale or document.unit_scale,
                "unit_label": item.unit_label or document.unit_label,
                "activity_description": item.activity_description,
                "structured_segment_taxonomy": document.structured_segment_taxonomy,
            },
        )
        for item in document.segments
    )
    totals = None
    scaled_total = _scaled(document.official_total_revenue, document.unit_scale)
    if document.official_total_revenue is not None or document.period:
        totals = BistRawBusinessTotals(
            symbol=document.symbol,
            total_revenue=scaled_total,
            currency=document.currency,
            period=document.period,
            period_end=document.period_end,
            source=BIST_BUSINESS_SOURCE_OFFICIAL,
            source_document_id=document.disclosure_id,
            as_of=document.period_end,
        )
    return segments, totals


def build_public_bist_business_bundle(
    document: KapPublicBusinessDocument,
    *,
    security_master: Optional[SecurityMasterService] = None,
) -> BistBusinessBundle:
    segments, totals = raw_segments_from_public(document)
    return build_bist_business_bundle(
        document.symbol,
        segments,
        totals,
        security_master=security_master,
    )


def cross_check_with_1e(
    document: KapPublicBusinessDocument,
    *,
    financial_total_revenue: Optional[float],
    financial_period: str,
    financial_currency: str,
) -> KapPublicRevenueCoverage:
    """Compare official segment total with canonical 1E revenue. No forced equality."""
    segment_total = _scaled(document.official_total_revenue, document.unit_scale)
    period_match = (
        bool(document.period)
        and bool(financial_period)
        and period_compatibility(document.period, financial_period) != PERIOD_INCOMPATIBLE
        and document.period.upper() == financial_period.upper()
    )
    currency_match = (
        bool(document.currency)
        and bool(financial_currency)
        and document.currency.upper() == financial_currency.upper()
    )
    if not period_match:
        return KapPublicRevenueCoverage(
            symbol=document.symbol,
            coverage_ratio=None,
            unexplained_remainder=None,
            segment_revenue_total=segment_total,
            financial_total_revenue=financial_total_revenue,
            status=COVERAGE_PERIOD_INCOMPATIBLE,
            period_match=False,
            currency_match=currency_match,
            used_1e_denominator_for_shares=False,
        )
    if not currency_match:
        return KapPublicRevenueCoverage(
            symbol=document.symbol,
            coverage_ratio=None,
            unexplained_remainder=None,
            segment_revenue_total=segment_total,
            financial_total_revenue=financial_total_revenue,
            status=COVERAGE_CURRENCY_MISMATCH,
            period_match=True,
            currency_match=False,
            used_1e_denominator_for_shares=False,
        )
    if financial_total_revenue is None or financial_total_revenue == 0:
        return KapPublicRevenueCoverage(
            symbol=document.symbol,
            coverage_ratio=None,
            unexplained_remainder=None,
            segment_revenue_total=segment_total,
            financial_total_revenue=financial_total_revenue,
            status=COVERAGE_MISSING_FINANCIAL_TOTAL,
            period_match=True,
            currency_match=True,
            used_1e_denominator_for_shares=False,
        )
    if segment_total is None:
        remainder = financial_total_revenue
        return KapPublicRevenueCoverage(
            symbol=document.symbol,
            coverage_ratio=0.0,
            unexplained_remainder=remainder,
            segment_revenue_total=None,
            financial_total_revenue=financial_total_revenue,
            status=COVERAGE_OK,
            period_match=True,
            currency_match=True,
            used_1e_denominator_for_shares=False,
        )
    return KapPublicRevenueCoverage(
        symbol=document.symbol,
        coverage_ratio=segment_total / financial_total_revenue,
        unexplained_remainder=financial_total_revenue - segment_total,
        segment_revenue_total=segment_total,
        financial_total_revenue=financial_total_revenue,
        status=COVERAGE_OK,
        period_match=True,
        currency_match=True,
        used_1e_denominator_for_shares=False,
    )


def shadow_business_screen(
    bundle: BistBusinessBundle,
    *,
    methodology_id: str = "msci_islamic_index_series",
) -> KapBusinessScreenShadow:
    """Read-only engine consumption check. Not a published Participation status."""
    evidence = business_evidence_from_bist(bundle)
    result = evaluate_business_activity(methodology_id, evidence)
    return KapBusinessScreenShadow(
        result_kind=SHADOW_RESULT_KIND,
        symbol=result.symbol,
        overall_outcome=result.overall_outcome,
        evidence_completeness=result.evidence_completeness,
        methodology_complete=result.methodology_complete,
        persisted=False,
        not_participation_status=True,
        warnings=result.warnings,
    )


def public_participation_readiness(
    bundle: BistBusinessBundle,
    financial_inputs: Optional[ParticipationFinancialInputs] = None,
):
    return combine_bist_participation_readiness(
        symbol=bundle.symbol,
        identity_source=SOURCE_BIST,
        financial_inputs=financial_inputs,
        business_bundle=bundle,
    )


def inventory_participation_financial_gaps(
    observed_concepts: Iterable[str],
) -> tuple[KapFinancialGap, ...]:
    """Read-only 1G inventory. Does not implement new financial sources."""
    observed = tuple(observed_concepts)
    cash = _present(observed, _CASH_CONCEPTS)
    securities = _present(observed, _SECURITY_CONCEPTS)
    ar = _present(observed, _AR_CONCEPTS)
    debt = _present(observed, _BORROWING_CONCEPTS)
    return (
        KapFinancialGap(
            field="cash_and_interest_bearing_securities",
            status=GAP_METHODOLOGY_UNRESOLVED,
            observed_concepts=cash + securities,
            likely_public_source="KAP FR taxonomy: cash + current financial assets",
            note=(
                "Cash is public. Interest-bearing securities are not a single "
                "verified KAP concept; fund/equity vs deposit split is unresolved."
            ),
        ),
        KapFinancialGap(
            field="accounts_receivable",
            status=GAP_AVAILABLE_FROM_PUBLIC_KAP if ar else GAP_REQUIRES_OTHER_PUBLIC_SOURCE,
            observed_concepts=ar,
            likely_public_source="KAP FR taxonomy: ifrs-full_CurrentTradeReceivables",
            note="Observed on public FR pages. Not mapped into Participation this sprint.",
        ),
        KapFinancialGap(
            field="non_permissible_revenue",
            status=GAP_METHODOLOGY_UNRESOLVED,
            observed_concepts=(),
            likely_public_source="Official business notes + finance-income notes",
            note="Not a KAP line item. Finance-sector template lines are not NPR.",
        ),
        KapFinancialGap(
            field="interest_bearing_debt",
            status=GAP_METHODOLOGY_UNRESOLVED,
            observed_concepts=debt,
            likely_public_source="KAP FR taxonomy: borrowings / debt instruments",
            note="Borrowings are public. Interest-bearing vs lease/other split is unresolved.",
        ),
        KapFinancialGap(
            field="market_capitalization",
            status=GAP_REQUIRES_OTHER_PUBLIC_SOURCE,
            observed_concepts=(),
            likely_public_source="BIST public market price × shares",
            note="Not present on KAP financial-report taxonomy.",
        ),
        KapFinancialGap(
            field="average_market_cap_24m",
            status=GAP_REQUIRES_OTHER_PUBLIC_SOURCE,
            observed_concepts=(),
            likely_public_source="BIST public price history",
            note="Not present on KAP financial-report taxonomy.",
        ),
    )


def gap_fields() -> tuple[str, ...]:
    return PARTICIPATION_FINANCIAL_GAP_FIELDS
