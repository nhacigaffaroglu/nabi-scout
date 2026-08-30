"""Official Turkish fund economic-exposure classification.

Uses accepted KAP mandate + PDR only. Does not score FI, run 8E, or allocate.
cash_like is not portfolio CASH.
"""

from __future__ import annotations

from typing import Optional

from services.fund_product_contract import (
    LAYER_CASH_LIKE,
    REGION_TR,
    OfficialFundEconomicClassification,
    OfficialFundMandate,
    PROVIDER_KAP_FUND,
)
from services.official_kap_pdr import asset_group_weights, explicit_subgroup_weights
from services.security_identity_contract import ECONOMIC_LAYERS

OFFICIAL_GEOGRAPHIES = frozenset({REGION_TR, "TURKIYE"})
EVIDENCE_MANDATE = "official_kap_mandate"
EVIDENCE_PDR = "official_kap_pdr"


def classify_official_turkiye_fund_exposure(
    mandate: Optional[OfficialFundMandate],
    pdr,
) -> Optional[OfficialFundEconomicClassification]:
    """Fail closed when official mandate or official PDR is missing."""
    if mandate is None or pdr is None or not getattr(pdr, "holdings", None):
        return None
    try:
        mandate.validate()
    except ValueError:
        return None
    layer = str(mandate.primary_layer or "").strip().lower()
    if layer not in ECONOMIC_LAYERS:
        return None
    geography = str(mandate.region or "").strip().upper()
    if geography not in OFFICIAL_GEOGRAPHIES:
        return None
    weights = getattr(pdr, "weights", None)
    if weights is None or not bool(getattr(weights, "weight_reconciled", False)):
        return None
    groups = asset_group_weights(pdr)
    if not groups:
        return None
    lookthrough = tuple(sorted(groups.items(), key=lambda item: (-item[1], item[0])))
    subgroups: tuple[tuple[str, float], ...] = ()
    if layer == "sukuk":
        public = explicit_subgroup_weights(pdr, "Kamu Kesimi")
        private = explicit_subgroup_weights(pdr, "Özel Sektör")
        if public or private:
            subgroups = (("Kamu Kesimi", public), ("Özel Sektör", private))
    limitations = ["PRIMARY_DISTINCT_FROM_LOOKTHROUGH"]
    if layer == LAYER_CASH_LIKE:
        limitations.append("NOT_PORTFOLIO_CASH")
    return OfficialFundEconomicClassification(
        symbol=mandate.symbol,
        instrument="FUND",
        primary_exposure=layer,
        geography=REGION_TR,
        lookthrough_weights=lookthrough,
        subgroup_weights=subgroups,
        confidence="MEDIUM",
        source=PROVIDER_KAP_FUND,
        source_url=mandate.source_url,
        as_of=getattr(pdr, "report_period", None) or getattr(pdr, "report_date", None),
        evidence_basis=(EVIDENCE_MANDATE, EVIDENCE_PDR),
        ready=True,
        limitations=tuple(limitations),
    )


def official_economic_exposure_available(classification: Optional[OfficialFundEconomicClassification]) -> bool:
    return bool(classification is not None and classification.ready)
