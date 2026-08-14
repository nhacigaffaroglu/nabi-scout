from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from services.participation_intelligence_contract import CONFIDENCE_HIGH, CONFIDENCE_LOW, CONFIDENCE_MEDIUM
from services.participation_revenue_segment_contract import (
    CLASSIFICATION_NON_PERMISSIBLE,
    CLASSIFICATION_UNKNOWN,
    RevenueSegmentEvidence,
    SOURCE_TYPE_SEC_XBRL,
)
from services.participation_business_contract import BusinessRevenueEvidence

_US_GAAP_SEGMENT_REVENUE_TAGS = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
    "RevenueFromExternalCustomers",
    "SalesRevenueGoodsNet",
    "SalesRevenueServicesNet",
)

_IFRS_SEGMENT_REVENUE_TAGS = (
    "Revenue",
    "RevenueFromContractsWithCustomers",
)


from services.participation_segment_classifier import classify_segments

_ANNUAL_FORMS = frozenset({"10-K", "10-K/A", "20-F", "40-F"})


def _annual_duration_days(start: str, end: str) -> Optional[int]:
    try:
        return (date.fromisoformat(end) - date.fromisoformat(start)).days
    except ValueError:
        return None


def _is_annual_entry(item: Mapping[str, Any]) -> bool:
    if item.get("form") not in _ANNUAL_FORMS:
        return False
    start = item.get("start")
    end = item.get("end")
    if not start or not end:
        return False
    days = _annual_duration_days(str(start), str(end))
    return days is not None and 300 <= days <= 430


def _normalize_segment_key(label: str) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", str(label or "").strip().lower())
    return " ".join(text.split())


def _segment_label_from_entry(item: Mapping[str, Any]) -> Optional[str]:
    for key in ("segment", "dim", "axis", "member"):
        value = item.get(key)
        if value not in (None, ""):
            text = str(value).strip()
            if text.lower() not in {"all", "total", "consolidated", "company total"}:
                return text
    return None


def _extract_dimensional_segments(
    facts: Mapping[str, Any],
    tags: Sequence[str],
    currency_units: Sequence[str],
    *,
    total_revenue: Optional[float],
    fiscal_period_end: Optional[str],
) -> List[RevenueSegmentEvidence]:
    segments_by_key: Dict[str, Dict[str, Any]] = {}

    for tag in tags:
        tag_payload = facts.get(tag) or {}
        units = tag_payload.get("units") or {}
        for unit in currency_units:
            for item in units.get(unit) or []:
                if not _is_annual_entry(item):
                    continue
                if fiscal_period_end and str(item.get("end") or "")[:10] != str(fiscal_period_end)[:10]:
                    continue
                segment_label = _segment_label_from_entry(item)
                if segment_label is None:
                    continue
                value = item.get("val")
                try:
                    amount = float(value)
                except (TypeError, ValueError):
                    continue
                if amount < 0:
                    continue
                key = _normalize_segment_key(segment_label)
                existing = segments_by_key.get(key)
                filed = str(item.get("filed") or "")
                if existing is None or filed > str(existing.get("filed") or ""):
                    segments_by_key[key] = {
                        "segment_name": segment_label,
                        "revenue_amount": amount,
                        "filed": filed,
                        "end": str(item.get("end") or ""),
                        "tag": tag,
                    }

    if not segments_by_key:
        return []

    segment_total = sum(row["revenue_amount"] for row in segments_by_key.values())
    denominator = total_revenue if total_revenue and total_revenue > 0 else segment_total
    coverage_pct = (segment_total / denominator * 100.0) if denominator > 0 else 0.0
    limitations: list[str] = []
    if total_revenue and segment_total > 0:
        gap = abs(total_revenue - segment_total) / total_revenue * 100.0
        if gap > 5.0:
            limitations.append(
                "Segment toplamı ile bildirilen toplam gelir arasında anlamlı fark var."
            )
    if coverage_pct < 80.0 and total_revenue:
        limitations.append("Segment kapsamı toplam gelirin %80'inden az.")

    results: list[RevenueSegmentEvidence] = []
    for index, (key, row) in enumerate(sorted(segments_by_key.items())):
        pct = None
        if denominator > 0:
            pct = row["revenue_amount"] / denominator * 100.0
        results.append(
            RevenueSegmentEvidence(
                segment_id=f"sec-seg-{index + 1}",
                segment_name=str(row["segment_name"]),
                revenue_amount=float(row["revenue_amount"]),
                revenue_pct=pct,
                fiscal_period=str(row["end"])[:10] if row.get("end") else fiscal_period_end,
                filing_date=str(row.get("filed") or "")[:10] or None,
                source="SEC",
                source_type=SOURCE_TYPE_SEC_XBRL,
                confidence=CONFIDENCE_HIGH if not limitations else CONFIDENCE_MEDIUM,
                limitations=tuple(limitations),
            )
        )
    return results


def extract_revenue_segments_from_sec(
    payload: Mapping[str, Any],
    *,
    sec_financials: Optional[Mapping[str, Any]] = None,
) -> Tuple[RevenueSegmentEvidence, ...]:
    all_facts = payload.get("facts") or {}
    sec_financials = sec_financials or {}
    fiscal_period_end = sec_financials.get("financial_period_end")
    total_revenue = sec_financials.get("revenue")
    currency = sec_financials.get("financial_currency") or "USD"
    taxonomy = sec_financials.get("financial_taxonomy") or "us-gaap"

    if taxonomy == "ifrs-full":
        facts = all_facts.get("ifrs-full") or {}
        tags = _IFRS_SEGMENT_REVENUE_TAGS
    else:
        facts = all_facts.get("us-gaap") or {}
        tags = _US_GAAP_SEGMENT_REVENUE_TAGS

    if not facts:
        return ()

    currency_units = [currency]
    raw_segments = _extract_dimensional_segments(
        facts,
        tags,
        currency_units,
        total_revenue=total_revenue,
        fiscal_period_end=fiscal_period_end,
    )
    return tuple(raw_segments)


def revenue_segments_to_business_evidence(
    segments: Sequence[RevenueSegmentEvidence],
    *,
    prohibited_categories: Sequence[str] = (),
) -> Tuple[BusinessRevenueEvidence, ...]:
    classified = classify_segments(segments, prohibited_categories=prohibited_categories)
    business_segments: list[BusinessRevenueEvidence] = []
    for segment in classified:
        category = segment.category or "unknown"
        if segment.classification_code == CLASSIFICATION_NON_PERMISSIBLE:
            category = "non_permissible"
        elif segment.classification_code == CLASSIFICATION_UNKNOWN:
            category = "unknown"
        business_segments.append(
            BusinessRevenueEvidence(
                category=category,
                segment_name=segment.segment_name,
                revenue_value=segment.revenue_amount,
                revenue_pct=segment.revenue_pct,
                source=segment.source,
                source_date=(
                    date.fromisoformat(segment.fiscal_period[:10])
                    if segment.fiscal_period and len(segment.fiscal_period) >= 10
                    else None
                ),
                confidence=segment.confidence,
            )
        )
    return tuple(business_segments)


def merge_revenue_segment_sources(
    *sources: Sequence[BusinessRevenueEvidence],
) -> Tuple[BusinessRevenueEvidence, ...]:
    merged: dict[str, BusinessRevenueEvidence] = {}
    for collection in sources:
        for segment in collection:
            key = segment.segment_name.strip().lower()
            if not key:
                continue
            existing = merged.get(key)
            if existing is None or (segment.revenue_value or 0) > (existing.revenue_value or 0):
                merged[key] = segment
    return tuple(merged.values())
