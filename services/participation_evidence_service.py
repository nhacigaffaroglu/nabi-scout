from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from services.participation_business_contract import BusinessRevenueEvidence
from services.participation_market_cap_resolver import (
    apply_market_cap_evidence_to_inputs,
    resolve_historical_market_cap_evidence,
)
from services.participation_sec_segment_resolver import (
    extract_revenue_segments_from_sec,
    revenue_segments_to_business_evidence,
)


@dataclass(frozen=True)
class ParticipationEvidenceBundle:
    fmp_profile: Dict[str, Any] = field(default_factory=dict)
    sec_metadata: Dict[str, Optional[str]] = field(default_factory=dict)
    revenue_segments: Tuple[BusinessRevenueEvidence, ...] = field(default_factory=tuple)
    market_cap_evidence: Any = None
    provider_calls: Dict[str, int] = field(default_factory=dict)
    warnings: Tuple[str, ...] = field(default_factory=tuple)


def _optional_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_participation_evidence_bundle(
    symbol: str,
    *,
    fmp_client: Any = None,
    sec_client: Any = None,
    cik: Optional[int | str] = None,
    sec_company_facts_payload: Optional[Mapping[str, Any]] = None,
    sec_financials: Optional[Mapping[str, Any]] = None,
    prohibited_categories: Sequence[str] = (),
) -> ParticipationEvidenceBundle:
    normalized = str(symbol or "").strip().upper()
    calls: Dict[str, int] = {}
    warnings: list[str] = []
    profile: Dict[str, Any] = {}
    sec_metadata: Dict[str, Optional[str]] = {}
    revenue_segments: Tuple[BusinessRevenueEvidence, ...] = ()

    if sec_company_facts_payload:
        from services.sec_financial_client import SECFinancialClient

        if sec_client is not None and cik is not None:
            sec_metadata, metadata_evidence = sec_client.resolve_entity_metadata(
                dict(sec_company_facts_payload),
                cik=cik,
            )
            for key, value in metadata_evidence:
                if key == "sic_source":
                    sec_metadata = {**sec_metadata, "sic_source": value}
            if any(key == "sic_source" and value == "sec_submissions" for key, value in metadata_evidence):
                calls["sec_submissions"] = calls.get("sec_submissions", 0) + 1
        else:
            sec_metadata = SECFinancialClient.extract_entity_metadata(
                dict(sec_company_facts_payload)
            )
        raw_segments = extract_revenue_segments_from_sec(
            sec_company_facts_payload,
            sec_financials=sec_financials,
        )
        if raw_segments:
            revenue_segments = revenue_segments_to_business_evidence(
                raw_segments,
                prohibited_categories=prohibited_categories,
            )
            calls["sec_revenue_segments"] = 1
        elif sec_financials and sec_financials.get("revenue"):
            warnings.append("SEC toplam gelir mevcut ancak yapılandırılmış segment ayrımı bulunamadı.")

    market_cap_evidence = None
    if fmp_client is not None:
        try:
            profile = fmp_client.profile(normalized) or {}
            calls["profile"] = calls.get("profile", 0) + 1
        except Exception as exc:
            warnings.append(f"FMP profil verisi alınamadı: {exc.__class__.__name__}")
            profile = {}

        shares = _optional_float(
            profile.get("sharesOutstanding") or profile.get("shares_outstanding")
        )
        market_cap = _optional_float(profile.get("marketCap") or profile.get("mktCap"))
        if shares is None and market_cap is not None:
            price = _optional_float(profile.get("price"))
            if price and price > 0:
                shares = market_cap / price

        if shares is not None and shares > 0:
            market_cap_evidence = resolve_historical_market_cap_evidence(
                symbol=normalized,
                fmp_client=fmp_client,
                shares_outstanding=shares,
                profile_market_cap=market_cap,
            )
            for key, value in market_cap_evidence.provider_calls.items():
                calls[key] = calls.get(key, 0) + value
            warnings.extend(market_cap_evidence.limitations)

    return ParticipationEvidenceBundle(
        fmp_profile=profile,
        sec_metadata=sec_metadata,
        revenue_segments=revenue_segments,
        market_cap_evidence=market_cap_evidence,
        provider_calls=calls,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def merge_participation_financial_inputs(
    inputs,
    *,
    evidence_bundle: ParticipationEvidenceBundle,
    non_permissible_revenue: Optional[float] = None,
    market_capitalization: Optional[float] = None,
):
    from dataclasses import replace

    merged = inputs
    if market_capitalization is not None and merged.market_capitalization is None:
        merged = replace(merged, market_capitalization=market_capitalization)
    if evidence_bundle.market_cap_evidence is not None:
        merged = apply_market_cap_evidence_to_inputs(
            merged,
            evidence_bundle.market_cap_evidence,
        )
    if non_permissible_revenue is not None:
        merged = replace(merged, non_permissible_revenue=non_permissible_revenue)
    return merged
