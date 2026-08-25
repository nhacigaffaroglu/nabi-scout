from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Tuple

from services.participation_revenue_attribution_contract import (
    ATTRIBUTION_FAIL_CLOSED,
    ATTRIBUTION_SUCCESS,
    MAPPING_AMBIGUOUS,
    PARTITION_COMPLETE,
    PROHIBITED_MAPPING_STATUSES,
    RevenueAttributionItem,
    RevenueAttributionView,
)

GRANULARITY_ACTIVITY_SPECIFIC = "ACTIVITY_SPECIFIC"
GRANULARITY_PRODUCT_SERVICE_SPECIFIC = "PRODUCT_SERVICE_SPECIFIC"
GRANULARITY_BUSINESS_LINE_SPECIFIC = "BUSINESS_LINE_SPECIFIC"
GRANULARITY_BROAD_OPERATING_SEGMENT = "BROAD_OPERATING_SEGMENT"
GRANULARITY_GEOGRAPHIC = "GEOGRAPHIC"
GRANULARITY_UNKNOWN = "UNKNOWN"

ATTRIBUTION_QUALITY_HIGH = "HIGH"
ATTRIBUTION_QUALITY_MEDIUM = "MEDIUM"
ATTRIBUTION_QUALITY_INSUFFICIENT = "INSUFFICIENT"

_GRANULARITY_RANK = {
    GRANULARITY_UNKNOWN: 0,
    GRANULARITY_GEOGRAPHIC: 1,
    GRANULARITY_BROAD_OPERATING_SEGMENT: 2,
    GRANULARITY_BUSINESS_LINE_SPECIFIC: 3,
    GRANULARITY_PRODUCT_SERVICE_SPECIFIC: 4,
    GRANULARITY_ACTIVITY_SPECIFIC: 5,
}

_POLICY_PATH = (
    Path(__file__).resolve().parent.parent
    / "config"
    / "participation_revenue_granularity_policy.json"
)

_PARTITION_TOLERANCE = 0.02

LIMITATION_BROAD_PARTITION = (
    "Gelir kırılımı toplam geliri kapsıyor ancak faaliyetleri katılım kriterleri "
    "açısından yeterli ayrıntıda ayırmıyor."
)
LIMITATION_MATERIAL_OTHER = (
    "Gelir kırılımında önemli 'Diğer' kalemi bulunduğu için otomatik sıfır "
    "yasaklı gelir sonucu üretilemedi."
)
_LIMITATION_BROAD_PARTITION_TR = LIMITATION_BROAD_PARTITION
_LIMITATION_MATERIAL_OTHER_TR = LIMITATION_MATERIAL_OTHER


@dataclass(frozen=True)
class MemberGranularityResult:
    granularity: str
    rule_id: str
    rationale: str


@dataclass(frozen=True)
class SafeZeroEvaluation:
    allowed: bool
    partition_granularity: str
    attribution_quality: str
    limitations: Tuple[str, ...]
    has_material_other_bucket: bool = False


def _normalize_label(text: str) -> str:
    lowered = str(text or "").strip().lower()
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return " ".join(lowered.split())


@lru_cache(maxsize=1)
def _load_policy() -> dict[str, Any]:
    return json.loads(_POLICY_PATH.read_text(encoding="utf-8"))


def classify_member_granularity(
    reported_label: str,
    *,
    axis: str = "",
) -> MemberGranularityResult:
    policy = _load_policy()
    normalized = _normalize_label(reported_label)
    if not normalized:
        return MemberGranularityResult(
            granularity=GRANULARITY_UNKNOWN,
            rule_id="gran.unlabeled",
            rationale="Revenue member label is empty.",
        )

    for item in policy.get("member_label_rules") or ():
        pattern = str(item.get("pattern") or "").lower()
        if pattern and pattern in normalized:
            return MemberGranularityResult(
                granularity=str(item["granularity"]),
                rule_id=str(item["rule_id"]),
                rationale=f"Member label matched granularity rule {item['rule_id']}.",
            )

    axis_local = str(axis or "").split(":")[-1]
    axis_defaults = policy.get("axis_defaults") or {}
    if axis_local in axis_defaults:
        return MemberGranularityResult(
            granularity=str(axis_defaults[axis_local]),
            rule_id=f"gran.axis.{axis_local}",
            rationale=f"Axis default granularity for {axis_local}.",
        )

    return MemberGranularityResult(
        granularity=GRANULARITY_UNKNOWN,
        rule_id="gran.unmapped",
        rationale="Member granularity could not be classified deterministically.",
    )


def _weakest_granularity(*levels: str) -> str:
    if not levels:
        return GRANULARITY_UNKNOWN
    return min(levels, key=lambda level: _GRANULARITY_RANK.get(level, 0))


def partition_granularity_from_items(
    items: Sequence[RevenueAttributionItem],
    *,
    selected_axis: str = "",
) -> str:
    if not items:
        return GRANULARITY_UNKNOWN
    levels = [
        classify_member_granularity(item.reported_label, axis=item.axis or selected_axis).granularity
        for item in items
    ]
    return _weakest_granularity(*levels)


def _is_standalone_other_label(normalized_label: str) -> bool:
    policy = _load_policy()
    for pattern in policy.get("standalone_other_label_patterns") or ():
        if re.search(str(pattern), normalized_label, flags=re.I):
            return True
    return False


def _is_conservative_other_label(normalized_label: str) -> bool:
    policy = _load_policy()
    for pattern in policy.get("conservative_other_label_patterns") or ():
        if str(pattern).lower() in normalized_label:
            return True
    return False


def has_material_other_bucket(
    items: Sequence[RevenueAttributionItem],
    *,
    denominator: Optional[float],
) -> bool:
    if not items or not denominator or denominator <= 0:
        return False
    policy = _load_policy()
    threshold = float(policy.get("material_other_share_of_denominator") or 0.05)
    for item in items:
        normalized = _normalize_label(item.reported_label)
        if not (_is_standalone_other_label(normalized) or _is_conservative_other_label(normalized)):
            continue
        if item.amount / denominator >= threshold:
            return True
    return False


def attribution_quality_for_view(view: RevenueAttributionView) -> str:
    if view.partition_status != PARTITION_COMPLETE:
        return ATTRIBUTION_QUALITY_INSUFFICIENT
    if not view.items:
        return ATTRIBUTION_QUALITY_INSUFFICIENT
    if any(item.mapping_status == MAPPING_AMBIGUOUS for item in view.items):
        return ATTRIBUTION_QUALITY_INSUFFICIENT
    if view.denominator_value is None or view.denominator_value <= 0:
        return ATTRIBUTION_QUALITY_INSUFFICIENT
    coverage = view.partition_coverage
    if coverage is None or abs(coverage - 1.0) > _PARTITION_TOLERANCE:
        return ATTRIBUTION_QUALITY_INSUFFICIENT

    prohibited = view.prohibited_revenue or 0.0
    if prohibited > 0:
        return ATTRIBUTION_QUALITY_MEDIUM

    safe_zero = can_conclude_zero_prohibited_revenue(view)
    if safe_zero.allowed:
        return ATTRIBUTION_QUALITY_HIGH
    if view.partition_granularity in {
        GRANULARITY_BROAD_OPERATING_SEGMENT,
        GRANULARITY_GEOGRAPHIC,
        GRANULARITY_UNKNOWN,
    }:
        return ATTRIBUTION_QUALITY_MEDIUM
    return ATTRIBUTION_QUALITY_INSUFFICIENT


def can_conclude_zero_prohibited_revenue(
    view: RevenueAttributionView,
    *,
    business_activity_fail: bool = False,
) -> SafeZeroEvaluation:
    limitations: list[str] = []
    partition_granularity = view.partition_granularity or partition_granularity_from_items(
        view.items,
        selected_axis=view.selected_axis,
    )

    if business_activity_fail:
        return SafeZeroEvaluation(
            allowed=False,
            partition_granularity=partition_granularity,
            attribution_quality=ATTRIBUTION_QUALITY_INSUFFICIENT,
            limitations=("Independent prohibited-business finding blocks revenue PASS.",),
        )

    if view.partition_status != PARTITION_COMPLETE:
        limitations.append("SEC 10-K revenue partition incomplete.")
        return SafeZeroEvaluation(
            allowed=False,
            partition_granularity=partition_granularity,
            attribution_quality=ATTRIBUTION_QUALITY_INSUFFICIENT,
            limitations=tuple(limitations),
        )

    if view.denominator_value is None or view.denominator_value <= 0:
        limitations.append("Missing consolidated revenue denominator.")
        return SafeZeroEvaluation(
            allowed=False,
            partition_granularity=partition_granularity,
            attribution_quality=ATTRIBUTION_QUALITY_INSUFFICIENT,
            limitations=tuple(limitations),
        )

    coverage = view.partition_coverage
    if coverage is None or abs(coverage - 1.0) > _PARTITION_TOLERANCE:
        limitations.append("SEC 10-K revenue partition incomplete.")
        return SafeZeroEvaluation(
            allowed=False,
            partition_granularity=partition_granularity,
            attribution_quality=ATTRIBUTION_QUALITY_INSUFFICIENT,
            limitations=tuple(limitations),
        )

    if not view.items:
        limitations.append("No revenue partition items available.")
        return SafeZeroEvaluation(
            allowed=False,
            partition_granularity=partition_granularity,
            attribution_quality=ATTRIBUTION_QUALITY_INSUFFICIENT,
            limitations=tuple(limitations),
        )

    if any(item.mapping_status == MAPPING_AMBIGUOUS for item in view.items):
        limitations.append("One or more revenue categories are ambiguous under MSCI taxonomy.")
        return SafeZeroEvaluation(
            allowed=False,
            partition_granularity=partition_granularity,
            attribution_quality=ATTRIBUTION_QUALITY_INSUFFICIENT,
            limitations=tuple(limitations),
        )

    material_other = has_material_other_bucket(view.items, denominator=view.denominator_value)
    if material_other:
        limitations.append(_LIMITATION_MATERIAL_OTHER_TR)
        return SafeZeroEvaluation(
            allowed=False,
            partition_granularity=partition_granularity,
            attribution_quality=ATTRIBUTION_QUALITY_INSUFFICIENT,
            limitations=tuple(limitations),
            has_material_other_bucket=True,
        )

    policy = _load_policy()
    eligible = frozenset(policy.get("safe_zero_eligible_granularities") or ())
    if partition_granularity not in eligible:
        limitations.append(_LIMITATION_BROAD_PARTITION_TR)
        quality = ATTRIBUTION_QUALITY_MEDIUM
        if partition_granularity == GRANULARITY_UNKNOWN:
            quality = ATTRIBUTION_QUALITY_INSUFFICIENT
        return SafeZeroEvaluation(
            allowed=False,
            partition_granularity=partition_granularity,
            attribution_quality=quality,
            limitations=tuple(limitations),
        )

    quality = ATTRIBUTION_QUALITY_HIGH
    return SafeZeroEvaluation(
        allowed=True,
        partition_granularity=partition_granularity,
        attribution_quality=quality,
        limitations=(),
    )


def _prefer_granularity_eligible_subset(
    view: RevenueAttributionView,
) -> RevenueAttributionView:
    from dataclasses import replace
    from itertools import combinations

    if not view.items or not view.denominator_value:
        return view
    if can_conclude_zero_prohibited_revenue(view).allowed:
        return view

    denominator = float(view.denominator_value)
    ranked = sorted(view.items, key=lambda item: item.amount, reverse=True)
    search_pool = ranked[: min(len(ranked), 12)]
    best: Optional[Tuple[RevenueAttributionItem, ...]] = None
    best_gap = float("inf")

    for size in range(1, min(len(search_pool), 8) + 1):
        for combo in combinations(search_pool, size):
            total = sum(item.amount for item in combo)
            gap = abs(total - denominator) / denominator
            if gap > _PARTITION_TOLERANCE:
                continue
            candidate = replace(
                view,
                items=combo,
                partition_sum=total,
                partition_coverage=total / denominator,
                partition_granularity=partition_granularity_from_items(
                    combo,
                    selected_axis=view.selected_axis,
                ),
            )
            if can_conclude_zero_prohibited_revenue(candidate).allowed:
                if gap < best_gap or (abs(gap - best_gap) < 1e-9 and len(combo) < len(best or ())):
                    best = combo
                    best_gap = gap

    if best is None:
        return view
    total = sum(item.amount for item in best)
    return replace(
        view,
        items=best,
        partition_sum=total,
        partition_coverage=total / denominator,
        partition_granularity=partition_granularity_from_items(
            best,
            selected_axis=view.selected_axis,
        ),
    )


def finalize_attribution_view(view: RevenueAttributionView) -> RevenueAttributionView:
    from dataclasses import replace

    view = _prefer_granularity_eligible_subset(view)
    partition_granularity = partition_granularity_from_items(
        view.items,
        selected_axis=view.selected_axis,
    )
    prohibited = view.prohibited_revenue
    if prohibited is None:
        prohibited = sum(
            item.amount
            for item in view.items
            if item.mapping_status in PROHIBITED_MAPPING_STATUSES
        )

    if prohibited and prohibited > 0:
        ratio = (
            prohibited / view.denominator_value
            if view.denominator_value and view.denominator_value > 0
            else None
        )
        quality = ATTRIBUTION_QUALITY_MEDIUM
        return replace(
            view,
            partition_granularity=partition_granularity,
            attribution_quality=quality,
            prohibited_revenue=prohibited,
            prohibited_ratio=ratio,
            status=ATTRIBUTION_SUCCESS,
            confidence="MEDIUM",
        )

    safe_zero = can_conclude_zero_prohibited_revenue(
        replace(view, partition_granularity=partition_granularity, prohibited_revenue=0.0),
    )
    if safe_zero.allowed:
        ratio = 0.0 if view.denominator_value else None
        return replace(
            view,
            partition_granularity=partition_granularity,
            attribution_quality=safe_zero.attribution_quality,
            prohibited_revenue=0.0,
            prohibited_ratio=ratio,
            status=ATTRIBUTION_SUCCESS,
            confidence="HIGH",
            limitations=view.limitations,
        )

    return replace(
        view,
        partition_granularity=partition_granularity,
        attribution_quality=safe_zero.attribution_quality,
        prohibited_revenue=None,
        prohibited_ratio=None,
        status=ATTRIBUTION_FAIL_CLOSED,
        confidence="LOW",
        limitations=tuple(dict.fromkeys((*view.limitations, *safe_zero.limitations))),
        log_reason="attribution_granularity_insufficient",
    )


def granularity_label_tr(granularity: str) -> str:
    mapping = {
        GRANULARITY_ACTIVITY_SPECIFIC: "Faaliyet düzeyinde",
        GRANULARITY_PRODUCT_SERVICE_SPECIFIC: "Ürün/hizmet düzeyinde",
        GRANULARITY_BUSINESS_LINE_SPECIFIC: "İş kolu düzeyinde",
        GRANULARITY_BROAD_OPERATING_SEGMENT: "Geniş operasyon segmenti",
        GRANULARITY_GEOGRAPHIC: "Coğrafi bölge",
        GRANULARITY_UNKNOWN: "Belirlenemedi",
    }
    return mapping.get(granularity, granularity)


def attribution_quality_label_tr(quality: str) -> str:
    mapping = {
        ATTRIBUTION_QUALITY_HIGH: "Yüksek",
        ATTRIBUTION_QUALITY_MEDIUM: "Orta",
        ATTRIBUTION_QUALITY_INSUFFICIENT: "Yetersiz",
    }
    return mapping.get(quality, quality)
