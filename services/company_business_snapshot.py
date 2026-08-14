from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from services.company_intelligence_constants import PROVIDER_NAME
from services.company_intelligence_contract import (
    BusinessSnapshot,
    IntelligenceProvenance,
)
from services.company_intelligence_data import CompanyProviderBundle
from services.company_intelligence_utils import safe_float


def build_business_snapshot(bundle: CompanyProviderBundle) -> BusinessSnapshot:
    profile = bundle.profile or {}
    return BusinessSnapshot(
        symbol=bundle.symbol,
        company_name=profile.get("companyName") or profile.get("symbol"),
        sector=profile.get("sector"),
        industry=profile.get("industry"),
        exchange=profile.get("exchangeShortName") or profile.get("exchange"),
        market_cap=safe_float(profile.get("marketCap") or profile.get("mktCap")),
        currency=profile.get("currency"),
        country=profile.get("country"),
        description=profile.get("description"),
        ceo=profile.get("ceo"),
        website=profile.get("website"),
        reporting_currency=profile.get("currency"),
        provenance=IntelligenceProvenance(
            provider=PROVIDER_NAME,
            data_family="profile",
            retrieved_at=bundle.retrieved_at,
        ),
    )
