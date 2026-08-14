from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping, Optional, Sequence, Tuple

from services.participation_business_contract import (
    BusinessActivityEvidence,
    BusinessRevenueEvidence,
)
from services.participation_business_evidence_resolver import (
    build_business_activity_evidence_from_candidate,
)
from services.participation_sec_segment_resolver import merge_revenue_segment_sources


def _optional_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _profile_field(profile: Mapping[str, Any], *keys: str) -> Optional[str]:
    for key in keys:
        value = profile.get(key)
        text = _optional_text(value)
        if text:
            return text
    return None


def enrich_business_activity_evidence(
    candidate: Mapping[str, Any],
    *,
    sec_metadata: Optional[Mapping[str, Any]] = None,
    fmp_profile: Optional[Mapping[str, Any]] = None,
    revenue_segments: Sequence[BusinessRevenueEvidence] = (),
    reported_total_revenue: Optional[float] = None,
) -> BusinessActivityEvidence:
    base = build_business_activity_evidence_from_candidate(candidate)
    warnings = list(base.warnings)
    evidence_refs = list(base.evidence_refs)

    sic_code = base.sic_code
    sic_description = base.sic_description
    sector = base.sector
    industry = base.industry
    description = base.business_description
    source = base.source

    if sec_metadata:
        sec_sic = _optional_text(sec_metadata.get("sic_code"))
        sec_sic_desc = _optional_text(sec_metadata.get("sic_description"))
        if sec_sic:
            sic_code = sec_sic
            evidence_refs.append(("sic_code", sec_sic))
            source = "sec_entity_metadata+candidate_record"
        if sec_sic_desc:
            sic_description = sec_sic_desc
            evidence_refs.append(("sic_description", sec_sic_desc))

    if fmp_profile:
        fmp_sector = _profile_field(fmp_profile, "sector", "sectorTheme")
        fmp_industry = _profile_field(fmp_profile, "industry")
        fmp_description = _profile_field(fmp_profile, "description")
        fmp_sic = _profile_field(fmp_profile, "sicCode", "sic")

        if fmp_sic and sic_code is None:
            sic_code = fmp_sic
            evidence_refs.append(("sic_code", fmp_sic))
            source = "fmp_profile+candidate_record"
        if fmp_sector:
            if sector is None:
                sector = fmp_sector
                evidence_refs.append(("sector", fmp_sector))
            elif sector.lower() != fmp_sector.lower():
                warnings.append(
                    "FMP sektör etiketi aday kaydından farklı; aday kaydı öncelikli."
                )
        if fmp_industry:
            if industry is None:
                industry = fmp_industry
                evidence_refs.append(("industry", fmp_industry))
        if fmp_description and description is None:
            description = fmp_description
            evidence_refs.append(("description", "fmp.profile"))

    if sic_code is None:
        warnings.append("SIC kodu yapılandırılmış kaynaklardan alınamadı.")

    merged_segments = merge_revenue_segment_sources(
        revenue_segments if revenue_segments else (),
        base.revenue_segments,
    )

    reported_total_revenue = reported_total_revenue if reported_total_revenue is not None else base.reported_total_revenue

    return BusinessActivityEvidence(
        symbol=base.symbol,
        company_name=base.company_name or _optional_text((fmp_profile or {}).get("companyName")),
        sector=sector,
        industry=industry if industry and industry != sector else None,
        sic_code=sic_code,
        sic_description=sic_description,
        business_description=description,
        reported_total_revenue=reported_total_revenue,
        revenue_segments=merged_segments,
        source=source,
        source_date=base.source_date,
        evidence_refs=tuple(dict.fromkeys(evidence_refs)),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def derive_non_permissible_revenue_amount(
    total_revenue: Optional[float],
    revenue_segments: Sequence[BusinessRevenueEvidence],
    *,
    numerator_categories: Sequence[str] = ("non_permissible",),
) -> Tuple[Optional[float], Tuple[str, ...]]:
    if total_revenue is None or total_revenue <= 0:
        return None, ("Toplam gelir kanıtı olmadan yasaklı gelir tutarı türetilmedi.",)

    matched_segments = []
    for segment in revenue_segments:
        category = str(segment.category or "").lower()
        name = str(segment.segment_name or "").lower()
        if not any(cat.lower() in category or cat.lower() in name for cat in numerator_categories):
            continue
        matched_segments.append(segment)

    if not matched_segments:
        return None, ("Yasaklı gelir segment kanıtı sağlanmadı.",)

    total_pct = 0.0
    has_pct = False
    absolute_total = 0.0
    has_absolute = False
    for segment in matched_segments:
        if segment.revenue_pct is not None:
            has_pct = True
            total_pct += float(segment.revenue_pct)
        if segment.revenue_value is not None:
            has_absolute = True
            absolute_total += float(segment.revenue_value)

    if has_absolute:
        return absolute_total, ()
    if has_pct:
        return total_revenue * (total_pct / 100.0), (
            "Yasaklı gelir tutarı segment yüzdesi × toplam gelirden türetildi.",
        )
    return None, (
        "Segment kanıtında güvenilir yüzde veya tutar bulunamadı.",
    )
