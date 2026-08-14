from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from services.company_intelligence_constants import MIN_PEER_SAMPLE_SIZE, PROVIDER_NAME
from services.company_intelligence_contract import (
    IntelligenceObservation,
    IntelligenceProvenance,
    PeerComparisonRow,
    PeerSection,
)
from services.company_intelligence_data import CompanyProviderBundle
from services.company_intelligence_utils import median_value, percentile_rank, safe_float


def _peer_metric_values(
    bundle: CompanyProviderBundle,
    *,
    company_value: Optional[float],
    extractor,
) -> Tuple[List[float], List[str]]:
    values: List[float] = []
    unavailable: List[str] = []
    for peer in bundle.peers:
        ratios = bundle.peer_ratios_ttm.get(peer) or {}
        profile = bundle.peer_profiles.get(peer) or {}
        value = extractor(ratios, profile)
        if value is None:
            unavailable.append(peer)
        else:
            values.append(value)
    return values, unavailable


def build_peer_intelligence(bundle: CompanyProviderBundle) -> PeerSection:
    if not bundle.peers:
        return PeerSection(
            peer_selection_method="provider_stock_peers",
            peer_symbols=(),
            unavailable_peers=(),
            comparisons=(),
            observations=(),
            limitations=("Rakip listesi sağlayıcıdan alınamadı.",),
            provenance=IntelligenceProvenance(
                provider=PROVIDER_NAME,
                data_family="stock_peers",
                retrieved_at=bundle.retrieved_at,
            ),
        )

    company_ratios = bundle.ratios_ttm or {}
    comparisons: List[PeerComparisonRow] = []
    observations: List[IntelligenceObservation] = []

    metric_specs = (
        ("pe_ratio", lambda ratios, profile: safe_float(ratios.get("priceToEarningsRatioTTM"))),
        ("price_to_sales", lambda ratios, profile: safe_float(ratios.get("priceToSalesRatioTTM"))),
        ("roe", lambda ratios, profile: safe_float(ratios.get("returnOnEquityTTM"))),
    )

    for metric_name, extractor in metric_specs:
        company_value = extractor(company_ratios, bundle.profile)

        peer_values, _ = _peer_metric_values(bundle, company_value=company_value, extractor=extractor)
        peer_median = median_value(peer_values)
        difference = None
        if company_value is not None and peer_median is not None:
            difference = company_value - peer_median
        percentile = percentile_rank(company_value, peer_values) if peer_values else None
        rank = None
        limitations: Tuple[str, ...] = ()
        if len(peer_values) < MIN_PEER_SAMPLE_SIZE:
            limitations = ("Rakip örneklem boyutu yetersiz; sıralama üretilmedi.",)
        elif company_value is not None:
            rank = sum(1 for value in peer_values if value <= company_value) + 1

        comparisons.append(
            PeerComparisonRow(
                metric=metric_name,
                company_value=company_value,
                peer_median=peer_median,
                difference=difference,
                percentile=percentile,
                rank=rank,
                peer_count=len(peer_values),
                limitations=limitations,
            )
        )

        if (
            metric_name == "roe"
            and company_value is not None
            and peer_median is not None
            and len(peer_values) >= MIN_PEER_SAMPLE_SIZE
        ):
            if company_value > peer_median:
                observations.append(
                    IntelligenceObservation(
                        code="PROFITABILITY_ABOVE_PEER_MEDIAN",
                        status="FACT",
                        statement="Faaliyet marjı rakip medyanının üzerinde.",
                        metric=metric_name,
                        value=company_value,
                        comparison_value=peer_median,
                        source=PROVIDER_NAME,
                        confidence="MEDIUM",
                    )
                )
            elif company_value < peer_median:
                observations.append(
                    IntelligenceObservation(
                        code="PROFITABILITY_BELOW_PEER_MEDIAN",
                        status="FACT",
                        statement="Faaliyet marjı rakip medyanının altında.",
                        metric=metric_name,
                        value=company_value,
                        comparison_value=peer_median,
                        source=PROVIDER_NAME,
                        confidence="MEDIUM",
                    )
                )

    return PeerSection(
        peer_selection_method="provider_stock_peers",
        peer_symbols=tuple(bundle.peers),
        unavailable_peers=tuple(
            peer for peer in bundle.peers if peer not in bundle.peer_ratios_ttm
        ),
        comparisons=tuple(comparisons),
        observations=tuple(observations),
        limitations=(),
        provenance=IntelligenceProvenance(
            provider=PROVIDER_NAME,
            data_family="peer_comparison",
            retrieved_at=bundle.retrieved_at,
        ),
    )
