from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from itertools import combinations
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

import requests

from services.participation_msci_revenue_mapper import (
    is_prohibited_mapping,
    map_revenue_member_to_msci,
)
from services.participation_revenue_attribution_contract import (
    ATTRIBUTION_FAIL_CLOSED,
    ATTRIBUTION_INSUFFICIENT_DATA,
    ATTRIBUTION_SUCCESS,
    MAPPING_AMBIGUOUS,
    PARTITION_AMBIGUOUS,
    PARTITION_COMPLETE,
    PARTITION_OVERLAPPING,
    PARTITION_PARTIAL,
    PARTITION_UNUSABLE,
    RevenueAttributionItem,
    RevenueAttributionView,
)
from services.sec_filing_cache import (
    AttributionCacheKey,
    FilingCacheKey,
    get_sec_filing_cache,
)
from services.sec_inline_xbrl_parser import (
    InlineXbrlContext,
    InlineXbrlFact,
    ParsedInlineXbrlDocument,
    _currency_from_unit,
    _member_label,
    conflicting_duplicate_keys,
    deduplicate_facts,
    is_denominator_concept,
    is_revenue_concept,
    parse_inline_xbrl_document,
    select_target_period_end,
)
from services.sec_primary_filing_resolver import (
    SECPrimaryFilingRef,
    resolve_latest_annual_filing,
)

logger = logging.getLogger(__name__)

_PARTITION_TOLERANCE = 0.02
_AXIS_PRIORITY = (
    "StatementBusinessSegmentsAxis",
    "ProductOrServiceAxis",
    "StatementGeographicalAxis",
)

LOG_FILING_FETCH_FAILED = "filing_fetch_failed"
LOG_INLINE_PARSE_FAILED = "inline_xbrl_parse_failed"
LOG_NO_REVENUE_FACTS = "no_revenue_facts"
LOG_PARTITION_INCOMPLETE = "partition_incomplete"
LOG_PARTITION_OVERLAP = "partition_overlap"
LOG_MAPPING_AMBIGUOUS = "mapping_ambiguous"
LOG_ATTRIBUTION_SUCCESS = "attribution_success"
LOG_ATTRIBUTION_FAIL_CLOSED = "attribution_fail_closed"


@dataclass(frozen=True)
class AxisPartitionEvaluation:
    axis: str
    status: str
    members: Tuple[RevenueAttributionItem, ...]
    partition_sum: Optional[float]
    coverage: Optional[float]
    limitations: Tuple[str, ...]


def _normalize_member_key(member: str) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", str(member or "").lower())
    return " ".join(text.split())


def _subset_covers_denominator(
    items: Sequence[RevenueAttributionItem],
    denominator: float,
) -> Optional[Tuple[RevenueAttributionItem, ...]]:
    if not items or denominator <= 0:
        return None
    ranked = sorted(items, key=lambda item: item.amount, reverse=True)
    search_pool = ranked[: min(len(ranked), 12)]
    best: Optional[Tuple[RevenueAttributionItem, ...]] = None
    best_gap = float("inf")

    for size in range(1, min(len(search_pool), 8) + 1):
        for combo in combinations(search_pool, size):
            total = sum(item.amount for item in combo)
            gap = abs(total - denominator) / denominator
            if gap > _PARTITION_TOLERANCE:
                continue
            if any(item.mapping_status == MAPPING_AMBIGUOUS for item in combo):
                continue
            if best is None or gap < best_gap or (
                abs(gap - best_gap) < 1e-9 and len(combo) < len(best)
            ):
                best = combo
                best_gap = gap
    return best


def _context_matches_period(
    context: InlineXbrlContext,
    target_end: Optional[str],
) -> bool:
    if not target_end:
        return context.is_annual
    end = context.period_end
    return bool(end and end[:10] == target_end[:10])


def _consolidated_denominator(
    document: ParsedInlineXbrlDocument,
    *,
    target_end: Optional[str],
) -> Tuple[Optional[float], str, Optional[str]]:
    candidates: list[tuple[float, str, str, int]] = []
    for fact in document.facts:
        if not is_denominator_concept(fact.concept_local):
            continue
        context = document.contexts.get(fact.context_id)
        if context is None or context.has_segment_dimension:
            continue
        if not _context_matches_period(context, target_end):
            continue
        if fact.normalized_value is None or fact.normalized_value <= 0:
            continue
        candidates.append(
            (
                fact.normalized_value,
                fact.concept,
                fact.context_id,
                len(context.dimensions),
            )
        )
    if not candidates:
        return None, "", None
    zero_dim = [row for row in candidates if row[3] == 0]
    pool = zero_dim or candidates
    value, concept, context_id, _ = max(pool, key=lambda row: row[0])
    return value, concept, context_id


def _facts_for_axis(
    document: ParsedInlineXbrlDocument,
    *,
    axis_local: str,
    target_end: Optional[str],
) -> Tuple[InlineXbrlFact, ...]:
    rows: list[InlineXbrlFact] = []
    for fact in document.facts:
        if not is_revenue_concept(fact.concept_local):
            continue
        context = document.contexts.get(fact.context_id)
        if context is None or not _context_matches_period(context, target_end):
            continue
        member = context.axis_member(axis_local)
        if not member:
            continue
        if fact.normalized_value is None or fact.normalized_value < 0:
            continue
        rows.append(fact)
    return deduplicate_facts(tuple(rows), document.contexts)


def _build_axis_partition(
    document: ParsedInlineXbrlDocument,
    *,
    axis_local: str,
    target_end: Optional[str],
    denominator: Optional[float],
    filing_ref: SECPrimaryFilingRef,
    methodology_version: str,
    prohibited_categories: Sequence[str],
) -> AxisPartitionEvaluation:
    facts = _facts_for_axis(
        document,
        axis_local=axis_local,
        target_end=target_end,
    )
    if not facts:
        return AxisPartitionEvaluation(
            axis=axis_local,
            status=PARTITION_UNUSABLE,
            members=(),
            partition_sum=None,
            coverage=None,
            limitations=("No revenue facts for axis.",),
        )

    if conflicting_duplicate_keys(facts, document.contexts):
        return AxisPartitionEvaluation(
            axis=axis_local,
            status=PARTITION_AMBIGUOUS,
            members=(),
            partition_sum=None,
            coverage=None,
            limitations=("Conflicting duplicate inline XBRL facts.",),
        )

    by_member: Dict[str, InlineXbrlFact] = {}
    for fact in facts:
        context = document.contexts[fact.context_id]
        member = context.axis_member(axis_local) or ""
        key = _normalize_member_key(member)
        if not key:
            continue
        existing = by_member.get(key)
        if existing is None or (fact.normalized_value or 0) > (existing.normalized_value or 0):
            by_member[key] = fact

    items: list[RevenueAttributionItem] = []
    for fact in by_member.values():
        context = document.contexts[fact.context_id]
        member = context.axis_member(axis_local) or ""
        reported = _member_label(member, document.labels)
        mapping = map_revenue_member_to_msci(
            reported,
            methodology_version=methodology_version,
            prohibited_categories=prohibited_categories,
        )
        items.append(
            RevenueAttributionItem(
                reported_label=reported,
                normalized_label=reported.lower(),
                concept=fact.concept,
                axis=axis_local,
                member=member,
                amount=float(fact.normalized_value or 0),
                mapping_status=mapping.mapping_status,
                msci_category=mapping.msci_category,
                mapping_rule_id=mapping.rule_id,
                rationale=mapping.rationale,
                source=filing_ref.filing_url,
                context_id=fact.context_id,
                unit=fact.unit_ref,
                currency=_currency_from_unit(fact.unit_ref, document.units),
            )
        )

    partition_sum = sum(item.amount for item in items)
    coverage = None
    limitations: list[str] = []
    status = PARTITION_UNUSABLE

    if denominator and denominator > 0:
        coverage = partition_sum / denominator
        gap = abs(partition_sum - denominator) / denominator
        if gap <= _PARTITION_TOLERANCE:
            status = PARTITION_COMPLETE
        elif coverage > 1.0 + _PARTITION_TOLERANCE:
            subset = _subset_covers_denominator(items, denominator)
            if subset is not None:
                items = list(subset)
                partition_sum = sum(item.amount for item in items)
                coverage = partition_sum / denominator
                gap = abs(partition_sum - denominator) / denominator
                status = PARTITION_COMPLETE if gap <= _PARTITION_TOLERANCE else PARTITION_OVERLAPPING
            else:
                status = PARTITION_OVERLAPPING
                limitations.append("Revenue axes overlap; attribution not safely computable.")
        elif coverage > 1.0:
            subset = _subset_covers_denominator(items, denominator)
            if subset is not None and len(subset) < len(items):
                items = list(subset)
                partition_sum = sum(item.amount for item in items)
                coverage = partition_sum / denominator
                gap = abs(partition_sum - denominator) / denominator
                if gap <= _PARTITION_TOLERANCE:
                    status = PARTITION_COMPLETE
        elif coverage < 1.0 - _PARTITION_TOLERANCE:
            status = PARTITION_PARTIAL
            limitations.append("SEC 10-K revenue partition incomplete.")
        else:
            status = PARTITION_COMPLETE
    else:
        limitations.append("Missing consolidated revenue denominator.")

    if any(item.mapping_status == MAPPING_AMBIGUOUS for item in items):
        status = PARTITION_AMBIGUOUS
        limitations.append("One or more revenue categories are ambiguous under MSCI taxonomy.")

    return AxisPartitionEvaluation(
        axis=axis_local,
        status=status,
        members=tuple(sorted(items, key=lambda item: item.reported_label.lower())),
        partition_sum=partition_sum,
        coverage=coverage,
        limitations=tuple(dict.fromkeys(limitations)),
    )


def _discover_axes(document: ParsedInlineXbrlDocument) -> Tuple[str, ...]:
    axes: set[str] = set()
    for context in document.contexts.values():
        for axis, _member in context.dimensions:
            local = axis.split(":")[-1]
            if local.endswith("Axis"):
                axes.add(local)
    ordered = [axis for axis in _AXIS_PRIORITY if axis in axes]
    for axis in sorted(axes):
        if axis not in ordered:
            ordered.append(axis)
    return tuple(ordered)


def _select_axis_partition(
    evaluations: Sequence[AxisPartitionEvaluation],
) -> Optional[AxisPartitionEvaluation]:
    complete = [item for item in evaluations if item.status == PARTITION_COMPLETE]
    if not complete:
        return None
    for preferred in _AXIS_PRIORITY:
        for item in complete:
            if item.axis == preferred:
                return item
    return complete[0]


def _compute_prohibited_revenue(items: Sequence[RevenueAttributionItem]) -> float:
    total = 0.0
    for item in items:
        mapping = map_revenue_member_to_msci(item.reported_label)
        if is_prohibited_mapping(mapping):
            total += item.amount
    return total


def build_revenue_attribution_from_document(
    document: ParsedInlineXbrlDocument,
    *,
    symbol: str,
    filing_ref: SECPrimaryFilingRef,
    methodology_id: str,
    methodology_version: str,
    prohibited_categories: Sequence[str] = (),
    preferred_period_end: Optional[str] = None,
) -> RevenueAttributionView:
    target_end = select_target_period_end(
        document.contexts,
        preferred_end=preferred_period_end,
    )
    denominator, denominator_concept, denominator_context = _consolidated_denominator(
        document,
        target_end=target_end,
    )
    if denominator is None:
        logger.info("%s symbol=%s cik=%s", LOG_NO_REVENUE_FACTS, symbol, filing_ref.cik)
        return RevenueAttributionView(
            symbol=symbol,
            cik=filing_ref.cik,
            methodology=methodology_id,
            methodology_version=methodology_version,
            screening_period=target_end or "",
            filing_accession=filing_ref.accession_number,
            filing_form=filing_ref.form,
            filing_date=filing_ref.filing_date,
            filing_url=filing_ref.filing_url,
            primary_document=filing_ref.primary_document,
            denominator_name=denominator_concept,
            denominator_value=None,
            currency="USD",
            selected_axis="",
            partition_status=PARTITION_UNUSABLE,
            partition_sum=None,
            partition_coverage=None,
            status=ATTRIBUTION_INSUFFICIENT_DATA,
            limitations=("Missing consolidated revenue denominator.",),
            log_reason=LOG_NO_REVENUE_FACTS,
        )

    axes = _discover_axes(document)
    evaluations = [
        _build_axis_partition(
            document,
            axis_local=axis,
            target_end=target_end,
            denominator=denominator,
            filing_ref=filing_ref,
            methodology_version=methodology_version,
            prohibited_categories=prohibited_categories,
        )
        for axis in axes
    ]
    selected = _select_axis_partition(evaluations)

    if selected is None:
        best = evaluations[0] if evaluations else None
        status = PARTITION_UNUSABLE
        limitations = ("SEC 10-K revenue partition incomplete.",)
        log_reason = LOG_PARTITION_INCOMPLETE
        if evaluations:
            overlapping = [item for item in evaluations if item.status == PARTITION_OVERLAPPING]
            if overlapping:
                status = PARTITION_OVERLAPPING
                limitations = overlapping[0].limitations
                log_reason = LOG_PARTITION_OVERLAP
            elif any(item.status == PARTITION_AMBIGUOUS for item in evaluations):
                status = PARTITION_AMBIGUOUS
                limitations = ("One or more revenue categories are ambiguous under MSCI taxonomy.",)
                log_reason = LOG_MAPPING_AMBIGUOUS
            elif best is not None:
                status = best.status
                limitations = best.limitations
        logger.info("%s symbol=%s reason=%s", LOG_ATTRIBUTION_FAIL_CLOSED, symbol, log_reason)
        return RevenueAttributionView(
            symbol=symbol,
            cik=filing_ref.cik,
            methodology=methodology_id,
            methodology_version=methodology_version,
            screening_period=target_end or "",
            filing_accession=filing_ref.accession_number,
            filing_form=filing_ref.form,
            filing_date=filing_ref.filing_date,
            filing_url=filing_ref.filing_url,
            primary_document=filing_ref.primary_document,
            denominator_name=denominator_concept,
            denominator_value=denominator,
            currency="USD",
            selected_axis=best.axis if best else "",
            partition_status=status,
            partition_sum=best.partition_sum if best else None,
            partition_coverage=best.coverage if best else None,
            status=ATTRIBUTION_FAIL_CLOSED,
            limitations=limitations,
            log_reason=log_reason,
            provenance=(
                ("denominator_concept", denominator_concept),
                ("denominator_context", denominator_context or ""),
                ("filing_accession", filing_ref.accession_number),
                ("filing_url", filing_ref.filing_url),
            ),
        )

    prohibited_revenue = _compute_prohibited_revenue(selected.members)
    prohibited_ratio = (
        prohibited_revenue / denominator if denominator > 0 else None
    )
    if any(item.mapping_status == MAPPING_AMBIGUOUS for item in selected.members):
        logger.info("%s symbol=%s", LOG_MAPPING_AMBIGUOUS, symbol)
        return RevenueAttributionView(
            symbol=symbol,
            cik=filing_ref.cik,
            methodology=methodology_id,
            methodology_version=methodology_version,
            screening_period=target_end or "",
            filing_accession=filing_ref.accession_number,
            filing_form=filing_ref.form,
            filing_date=filing_ref.filing_date,
            filing_url=filing_ref.filing_url,
            primary_document=filing_ref.primary_document,
            denominator_name=denominator_concept,
            denominator_value=denominator,
            currency="USD",
            selected_axis=selected.axis,
            partition_status=PARTITION_AMBIGUOUS,
            partition_sum=selected.partition_sum,
            partition_coverage=selected.coverage,
            items=selected.members,
            prohibited_revenue=prohibited_revenue,
            prohibited_ratio=prohibited_ratio,
            status=ATTRIBUTION_FAIL_CLOSED,
            limitations=("One or more revenue categories are ambiguous under MSCI taxonomy.",),
            log_reason=LOG_MAPPING_AMBIGUOUS,
        )

    from services.participation_revenue_granularity import finalize_attribution_view

    logger.info(
        "%s symbol=%s axis=%s coverage=%.4f",
        LOG_ATTRIBUTION_SUCCESS,
        symbol,
        selected.axis,
        selected.coverage or 0,
    )
    draft = RevenueAttributionView(
        symbol=symbol,
        cik=filing_ref.cik,
        methodology=methodology_id,
        methodology_version=methodology_version,
        screening_period=target_end or "",
        filing_accession=filing_ref.accession_number,
        filing_form=filing_ref.form,
        filing_date=filing_ref.filing_date,
        filing_url=filing_ref.filing_url,
        primary_document=filing_ref.primary_document,
        denominator_name=denominator_concept,
        denominator_value=denominator,
        currency="USD",
        selected_axis=selected.axis,
        partition_status=PARTITION_COMPLETE,
        partition_sum=selected.partition_sum,
        partition_coverage=selected.coverage,
        items=selected.members,
        prohibited_revenue=prohibited_revenue,
        prohibited_ratio=prohibited_ratio,
        status=ATTRIBUTION_SUCCESS,
        confidence="HIGH",
        log_reason=LOG_ATTRIBUTION_SUCCESS,
        provenance=(
            ("denominator_concept", denominator_concept),
            ("denominator_context", denominator_context or ""),
            ("selected_axis", selected.axis),
            ("filing_accession", filing_ref.accession_number),
            ("filing_url", filing_ref.filing_url),
        ),
    )
    return finalize_attribution_view(draft)


def fetch_primary_filing_html(
    sec_client: Any,
    filing_ref: SECPrimaryFilingRef,
    *,
    cache: Optional[Any] = None,
) -> bytes:
    cache = cache or get_sec_filing_cache()
    cache_key = FilingCacheKey.build(
        cik=filing_ref.cik,
        accession=filing_ref.accession_number,
        primary_document=filing_ref.primary_document,
    )
    cached = cache.get_filing_html(cache_key)
    if cached is not None:
        return cached

    try:
        response = sec_client.session.get(filing_ref.filing_url, timeout=sec_client.timeout)
    except requests.RequestException as exc:
        logger.info("%s url=%s error=%s", LOG_FILING_FETCH_FAILED, filing_ref.filing_url, exc.__class__.__name__)
        raise

    if response.status_code != 200:
        logger.info("%s url=%s status=%s", LOG_FILING_FETCH_FAILED, filing_ref.filing_url, response.status_code)
        raise RuntimeError(f"SEC filing HTTP {response.status_code}")

    content = response.content
    cache.set_filing_html(cache_key, content)
    return content


def resolve_inline_xbrl_revenue_attribution(
    *,
    symbol: str,
    cik: int | str,
    sec_client: Any,
    methodology_id: str = "msci_islamic_index_series",
    methodology_version: str = "2025-05",
    prohibited_categories: Sequence[str] = (),
    preferred_period_end: Optional[str] = None,
    cache: Optional[Any] = None,
) -> RevenueAttributionView:
    cache = cache or get_sec_filing_cache()
    try:
        submissions = sec_client.company_submissions(cik)
    except Exception:
        logger.info("%s symbol=%s cik=%s", LOG_FILING_FETCH_FAILED, symbol, cik)
        return RevenueAttributionView(
            symbol=symbol,
            cik=str(cik),
            methodology=methodology_id,
            methodology_version=methodology_version,
            screening_period="",
            filing_accession="",
            filing_form="",
            filing_date="",
            filing_url="",
            primary_document="",
            denominator_name="",
            denominator_value=None,
            currency="USD",
            selected_axis="",
            partition_status=PARTITION_UNUSABLE,
            partition_sum=None,
            partition_coverage=None,
            status=ATTRIBUTION_FAIL_CLOSED,
            limitations=("Inline XBRL filing unavailable.",),
            log_reason=LOG_FILING_FETCH_FAILED,
        )

    filing_ref = resolve_latest_annual_filing(submissions, cik=cik)
    if filing_ref is None:
        return RevenueAttributionView(
            symbol=symbol,
            cik=str(cik),
            methodology=methodology_id,
            methodology_version=methodology_version,
            screening_period="",
            filing_accession="",
            filing_form="",
            filing_date="",
            filing_url="",
            primary_document="",
            denominator_name="",
            denominator_value=None,
            currency="USD",
            selected_axis="",
            partition_status=PARTITION_UNUSABLE,
            partition_sum=None,
            partition_coverage=None,
            status=ATTRIBUTION_FAIL_CLOSED,
            limitations=("No valid 10-K filing found.",),
            log_reason=LOG_FILING_FETCH_FAILED,
        )

    attr_key = AttributionCacheKey.build(
        cik=filing_ref.cik,
        accession=filing_ref.accession_number,
        methodology_version=f"{methodology_version}+granularity-v1",
    )
    cached_view = cache.get_attribution(attr_key)
    if cached_view is not None:
        return cached_view

    try:
        html = fetch_primary_filing_html(sec_client, filing_ref, cache=cache)
        document = parse_inline_xbrl_document(html)
    except Exception:
        logger.info("%s symbol=%s accession=%s", LOG_INLINE_PARSE_FAILED, symbol, filing_ref.accession_number)
        return RevenueAttributionView(
            symbol=symbol,
            cik=filing_ref.cik,
            methodology=methodology_id,
            methodology_version=methodology_version,
            screening_period="",
            filing_accession=filing_ref.accession_number,
            filing_form=filing_ref.form,
            filing_date=filing_ref.filing_date,
            filing_url=filing_ref.filing_url,
            primary_document=filing_ref.primary_document,
            denominator_name="",
            denominator_value=None,
            currency="USD",
            selected_axis="",
            partition_status=PARTITION_UNUSABLE,
            partition_sum=None,
            partition_coverage=None,
            status=ATTRIBUTION_FAIL_CLOSED,
            limitations=("Inline XBRL filing unavailable.",),
            log_reason=LOG_INLINE_PARSE_FAILED,
        )

    view = build_revenue_attribution_from_document(
        document,
        symbol=symbol,
        filing_ref=filing_ref,
        methodology_id=methodology_id,
        methodology_version=methodology_version,
        prohibited_categories=prohibited_categories,
        preferred_period_end=preferred_period_end,
    )
    cache.set_attribution(attr_key, view)
    return view
