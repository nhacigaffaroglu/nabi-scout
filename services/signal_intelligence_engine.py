"""Deterministic Signal Intelligence engine.

No LLM. No sentiment. No provider calls. No Participation / NABI Score
mutation. Missing evidence stays missing. Conflict stays CONFLICTING.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Optional, Sequence

from services.signal_intelligence_contract import (
    CHANGE_NEW_MATERIAL_SIGNAL,
    CHANGE_SIGNAL_CONFLICT_DETECTED,
    CHANGE_SIGNAL_VERIFIED,
    CONFLICTING,
    CORROBORATED,
    DIRECTION_MIXED,
    DIRECTION_NEGATIVE,
    DIRECTION_NEUTRAL,
    DIRECTION_POSITIVE,
    DIRECTION_UNKNOWN,
    EVENT_ANALYST_ACTION,
    EVENT_ASSET_SALE,
    EVENT_BONUS_ISSUE,
    EVENT_BUYBACK,
    EVENT_CAPITAL_INCREASE,
    EVENT_CREDIT_RATING,
    EVENT_CYBER_SECURITY,
    EVENT_DEBT_FINANCING,
    EVENT_DIVIDEND,
    EVENT_FINANCIAL_STATEMENT,
    EVENT_GUIDANCE,
    EVENT_KAP_DISCLOSURE,
    EVENT_LEGAL_REGULATORY,
    EVENT_MAJOR_CONTRACT,
    EVENT_MANAGEMENT_CHANGE,
    EVENT_MERGER_ACQUISITION,
    EVENT_NEWS,
    EVENT_OPERATIONAL_INCIDENT,
    EVENT_OTHER,
    EVENT_SEC_FILING,
    EVENT_SOCIAL_SIGNAL,
    EVENT_SPLIT,
    EVENT_TYPES,
    EVENT_UNKNOWN,
    MATERIAL_LEVELS,
    MATERIALITY_CRITICAL,
    MATERIALITY_HIGH,
    MATERIALITY_LOW,
    MATERIALITY_MEDIUM,
    MATERIALITY_UNKNOWN,
    RawSignalInput,
    REJECTED,
    SIGNAL_CONTRACT_VERSION,
    SIGNAL_ENGINE_VERSION,
    SecuritySignal,
    SignalEvidence,
    SignalEvent,
    SignalIntelligenceContext,
    SignalSnapshotRefs,
    STRENGTH_MODERATE,
    STRENGTH_STRONG,
    STRENGTH_UNKNOWN,
    STRENGTH_WEAK,
    SUBTYPE_BANKRUPTCY,
    SUBTYPE_DIVIDEND_CUT,
    SUBTYPE_DIVIDEND_INCREASE,
    SUBTYPE_DIVIDEND_SUSPEND,
    SUBTYPE_FORM_10K,
    SUBTYPE_FORM_20F,
    SUBTYPE_FORM_8K,
    SUBTYPE_GUIDANCE_CUT,
    SUBTYPE_GUIDANCE_RAISE,
    SUBTYPE_GUIDANCE_WITHDRAW,
    SUBTYPE_RATING_DOWNGRADE,
    SUBTYPE_RATING_UPGRADE,
    SUBTYPE_ROUTINE_FILING,
    SUBTYPE_SANCTION,
    TIER_1_PRIMARY,
    TIER_1_SOURCE_TYPES,
    TIER_2_HIGH_QUALITY_SECONDARY,
    TIER_3_SECONDARY_ANALYSIS,
    TIER_4_SOCIAL_DISCOVERY,
    UNVERIFIED,
    VERIFIED,
)
from services.signal_source_registry import is_social_source, resolve_source


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
_MATERIAL_RATIO = 0.10
_FRESHNESS_STRONG_DAYS = 180
_OPPOSITE = {DIRECTION_POSITIVE: DIRECTION_NEGATIVE, DIRECTION_NEGATIVE: DIRECTION_POSITIVE}


def normalize_symbol(symbol: Optional[str]) -> str:
    return str(symbol or "").strip().upper()


def normalize_factual_subject(value: Optional[str]) -> str:
    return " ".join(str(value or "").lower().split())


def classify_event_type(value: Optional[str]) -> str:
    text = str(value or "").strip().upper()
    if text in EVENT_TYPES:
        return text
    if not text:
        return EVENT_UNKNOWN
    return EVENT_OTHER


def canonical_event_date(value: Optional[str]) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    if _DATE_RE.match(text):
        return text[:10]
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.date().isoformat()


def _event_date_key(raw: RawSignalInput) -> str:
    return canonical_event_date(raw.effective_time) or canonical_event_date(raw.event_time) or "UNDATED"


def normalize_logical_event_key(value: Optional[str]) -> str:
    return " ".join(str(value or "").strip().lower().split())


def authoritative_event_id(raw: RawSignalInput) -> Optional[str]:
    """SEC accession, KAP disclosure id, or issuer/exchange/regulator event id.

    A TIER 1 evidence external_id is treated as the authoritative event id
    when authoritative_event_id is omitted. Newswire/social article ids are
    never promoted to event identity.
    """
    explicit = str(raw.authoritative_event_id or "").strip()
    if explicit:
        return explicit
    source = resolve_source(raw.source_id, raw.source_type)
    external = str(raw.external_id or "").strip()
    if external and source.source_type in TIER_1_SOURCE_TYPES:
        return external
    return None


def event_identity(raw: RawSignalInput) -> str:
    """Stable event identity. Never headline-only.

    1. Authoritative external event id
    2. Authoritative composite when logical_event_key is present
    3. Canonical fingerprint fallback
    """
    symbol = normalize_symbol(raw.symbol)
    event_type = classify_event_type(raw.event_type)
    source = resolve_source(raw.source_id, raw.source_type)
    auth_id = authoritative_event_id(raw)
    logical_key = normalize_logical_event_key(raw.logical_event_key)
    if auth_id and logical_key:
        digest = hashlib.sha256(
            f"{symbol}|{auth_id}|{logical_key}".encode("utf-8")
        ).hexdigest()[:32]
        return f"evt:{digest}"
    if auth_id:
        digest = hashlib.sha256(f"{symbol}|{auth_id}".encode("utf-8")).hexdigest()[:32]
        return f"evt:{digest}"
    subject = normalize_factual_subject(raw.factual_subject)
    if subject:
        digest = hashlib.sha256(
            f"{symbol}|{event_type}|{_event_date_key(raw)}|{subject}".encode("utf-8")
        ).hexdigest()[:32]
        return f"evt:{digest}"
    digest = hashlib.sha256(
        f"{symbol}|{event_type}|{_event_date_key(raw)}|{source.source_id}|{raw.external_id or ''}|{raw.raw_reference or ''}".encode("utf-8")
    ).hexdigest()[:32]
    return f"evt:{digest}"


def evidence_identity(raw: RawSignalInput, event_id: str) -> str:
    if raw.evidence_id:
        return str(raw.evidence_id).strip()
    source = resolve_source(raw.source_id, raw.source_type)
    external = str(raw.external_id or "").strip()
    if external:
        digest = hashlib.sha256(
            f"{source.source_type}|{external}".encode("utf-8")
        ).hexdigest()[:32]
        return f"evd:{digest}"
    digest = hashlib.sha256(
        f"{event_id}|{source.source_id}|{raw.source_url or ''}|{raw.raw_reference or ''}".encode("utf-8")
    ).hexdigest()[:32]
    return f"evd:{digest}"


def evidence_verification(raw: RawSignalInput, authority: str) -> str:
    if raw.rejected:
        return REJECTED
    if is_social_source(raw.source_type) or authority == TIER_4_SOCIAL_DISCOVERY:
        return UNVERIFIED
    if authority == TIER_1_PRIMARY:
        return VERIFIED
    if authority == TIER_2_HIGH_QUALITY_SECONDARY:
        return UNVERIFIED
    return UNVERIFIED


def _authoritative_evidence(items: Sequence[SignalEvidence]) -> tuple[SignalEvidence, ...]:
    return tuple(item for item in items if item.source_authority == TIER_1_PRIMARY and item.verification_status == VERIFIED)


def resolve_event_verification(items: Sequence[SignalEvidence]) -> str:
    if any(item.verification_status == REJECTED for item in items) and not _authoritative_evidence(items):
        return REJECTED
    if _authoritative_evidence(items):
        return VERIFIED
    secondary = [
        item
        for item in items
        if item.source_authority == TIER_2_HIGH_QUALITY_SECONDARY and item.verification_status != REJECTED
    ]
    independent = {item.source_id for item in secondary}
    if len(independent) >= 2:
        return CORROBORATED
    return UNVERIFIED


def resolve_event_authority(items: Sequence[SignalEvidence]) -> str:
    ranks = {
        TIER_1_PRIMARY: 4,
        TIER_2_HIGH_QUALITY_SECONDARY: 3,
        TIER_3_SECONDARY_ANALYSIS: 2,
        TIER_4_SOCIAL_DISCOVERY: 1,
    }
    if not items:
        return TIER_4_SOCIAL_DISCOVERY
    return max((item.source_authority for item in items), key=lambda item: ranks.get(item, 0))


def resolve_direction(*, event_type: str, event_subtype: Optional[str]) -> str:
    subtype = str(event_subtype or "").strip().upper()
    if subtype in {SUBTYPE_DIVIDEND_INCREASE, SUBTYPE_GUIDANCE_RAISE, SUBTYPE_RATING_UPGRADE}:
        return DIRECTION_POSITIVE
    if subtype in {
        SUBTYPE_DIVIDEND_CUT,
        SUBTYPE_DIVIDEND_SUSPEND,
        SUBTYPE_GUIDANCE_CUT,
        SUBTYPE_GUIDANCE_WITHDRAW,
        SUBTYPE_RATING_DOWNGRADE,
        SUBTYPE_BANKRUPTCY,
        SUBTYPE_SANCTION,
    }:
        return DIRECTION_NEGATIVE
    if event_type == EVENT_BUYBACK:
        return DIRECTION_POSITIVE
    if event_type in {EVENT_CAPITAL_INCREASE, EVENT_DEBT_FINANCING, EVENT_CYBER_SECURITY, EVENT_OPERATIONAL_INCIDENT}:
        return DIRECTION_NEGATIVE
    if event_type in {EVENT_MERGER_ACQUISITION, EVENT_ASSET_SALE}:
        return DIRECTION_MIXED
    if event_type in {EVENT_MANAGEMENT_CHANGE, EVENT_SOCIAL_SIGNAL, EVENT_OTHER, EVENT_UNKNOWN, EVENT_NEWS}:
        return DIRECTION_UNKNOWN
    if event_type == EVENT_DIVIDEND and not subtype:
        return DIRECTION_NEUTRAL
    if event_type in {EVENT_FINANCIAL_STATEMENT, EVENT_SEC_FILING, EVENT_ANALYST_ACTION}:
        return DIRECTION_NEUTRAL
    return DIRECTION_UNKNOWN


def resolve_materiality(
    *,
    event_type: str,
    event_subtype: Optional[str],
    verification: str,
    authority: str,
    contract_value: Optional[float] = None,
    revenue: Optional[float] = None,
    period_compatible: bool = False,
) -> tuple[str, tuple[str, ...]]:
    reasons: list[str] = []
    subtype = str(event_subtype or "").strip().upper()
    if verification == REJECTED:
        return MATERIALITY_UNKNOWN, ("REJECTED_EVIDENCE",)
    if event_type in {EVENT_OTHER, EVENT_UNKNOWN, EVENT_SOCIAL_SIGNAL}:
        return MATERIALITY_UNKNOWN, ("INSUFFICIENT_EVENT_CLASS",)
    if verification == UNVERIFIED and authority in {TIER_3_SECONDARY_ANALYSIS, TIER_4_SOCIAL_DISCOVERY}:
        return MATERIALITY_UNKNOWN, ("UNVERIFIED_NON_AUTHORITATIVE",)
    if subtype == SUBTYPE_BANKRUPTCY and authority == TIER_1_PRIMARY and verification == VERIFIED:
        return MATERIALITY_CRITICAL, ("AUTHORITATIVE_BANKRUPTCY",)
    if subtype == SUBTYPE_SANCTION and authority == TIER_1_PRIMARY and verification == VERIFIED:
        return MATERIALITY_CRITICAL, ("AUTHORITATIVE_SANCTION",)
    if subtype == SUBTYPE_GUIDANCE_WITHDRAW and verification in {VERIFIED, CORROBORATED}:
        return MATERIALITY_HIGH, ("GUIDANCE_WITHDRAWAL",)
    if event_type == EVENT_MERGER_ACQUISITION and verification == VERIFIED and authority == TIER_1_PRIMARY:
        return MATERIALITY_HIGH, ("AUTHORITATIVE_COMBINATION",)
    if event_type in {EVENT_CYBER_SECURITY, EVENT_OPERATIONAL_INCIDENT} and verification == VERIFIED:
        return MATERIALITY_HIGH, ("AUTHORITATIVE_INCIDENT",)
    if event_type == EVENT_LEGAL_REGULATORY and subtype == SUBTYPE_SANCTION:
        return MATERIALITY_HIGH, ("REGULATORY_SANCTION",)
    if event_type == EVENT_GUIDANCE and subtype in {SUBTYPE_GUIDANCE_CUT, SUBTYPE_GUIDANCE_WITHDRAW}:
        return MATERIALITY_HIGH if verification in {VERIFIED, CORROBORATED} else MATERIALITY_MEDIUM, ("GUIDANCE_REDUCTION",)
    if event_type == EVENT_MAJOR_CONTRACT:
        if (
            contract_value is not None
            and revenue is not None
            and revenue > 0
            and period_compatible
        ):
            ratio = contract_value / revenue
            reasons.append("CONTRACT_REVENUE_RATIO")
            if ratio >= _MATERIAL_RATIO:
                return MATERIALITY_HIGH, tuple(reasons + ["RATIO_MATERIAL"])
            return MATERIALITY_LOW, tuple(reasons + ["RATIO_IMMATERIAL"])
        return MATERIALITY_UNKNOWN, ("MISSING_MATERIALITY_DENOMINATOR",)
    if event_type == EVENT_FINANCIAL_STATEMENT or subtype in {SUBTYPE_FORM_10K, SUBTYPE_FORM_20F, SUBTYPE_ROUTINE_FILING}:
        return MATERIALITY_LOW, ("ROUTINE_FILING_PUBLICATION",)
    if event_type in {EVENT_SEC_FILING, EVENT_KAP_DISCLOSURE} and subtype == SUBTYPE_FORM_8K and verification == VERIFIED:
        return MATERIALITY_MEDIUM, ("AUTHORITATIVE_8K",)
    if event_type in {EVENT_DIVIDEND, EVENT_BUYBACK, EVENT_SPLIT, EVENT_BONUS_ISSUE}:
        return MATERIALITY_MEDIUM if verification == VERIFIED else MATERIALITY_LOW, ("CAPITAL_ACTION",)
    if event_type == EVENT_ANALYST_ACTION:
        return MATERIALITY_LOW, ("ANALYST_SECONDARY",)
    if event_type == EVENT_MANAGEMENT_CHANGE:
        return MATERIALITY_LOW if verification == VERIFIED else MATERIALITY_UNKNOWN, ("MANAGEMENT_CHANGE_UNSPECIFIED",)
    if event_type == EVENT_NEWS:
        return MATERIALITY_LOW, ("GENERIC_NEWS",)
    if verification == CORROBORATED and event_type in {EVENT_MERGER_ACQUISITION, EVENT_GUIDANCE}:
        return MATERIALITY_MEDIUM, ("SECONDARY_CORROBORATED",)
    if verification == VERIFIED and authority == TIER_1_PRIMARY:
        return MATERIALITY_MEDIUM, ("AUTHORITATIVE_DISCLOSURE",)
    return MATERIALITY_UNKNOWN, ("MATERIALITY_UNDETERMINED",)


def resolve_strength(
    *,
    authority: str,
    verification: str,
    materiality: str,
    event_time: Optional[str],
) -> str:
    if verification in {REJECTED, CONFLICTING}:
        return STRENGTH_UNKNOWN if verification == CONFLICTING else STRENGTH_WEAK
    if verification == UNVERIFIED or authority in {TIER_3_SECONDARY_ANALYSIS, TIER_4_SOCIAL_DISCOVERY}:
        return STRENGTH_WEAK
    stale = False
    day = canonical_event_date(event_time)
    if day:
        try:
            age = (datetime.now(timezone.utc).date() - datetime.fromisoformat(day).date()).days
            stale = age > _FRESHNESS_STRONG_DAYS
        except ValueError:
            stale = False
    if authority == TIER_1_PRIMARY and verification == VERIFIED and materiality in MATERIAL_LEVELS and not stale:
        return STRENGTH_STRONG
    if verification in {VERIFIED, CORROBORATED} and materiality in {MATERIALITY_HIGH, MATERIALITY_MEDIUM}:
        return STRENGTH_MODERATE
    if materiality == MATERIALITY_LOW:
        return STRENGTH_WEAK
    return STRENGTH_UNKNOWN


def why_it_matters(event: SignalEvent) -> str:
    if event.verification_status == CONFLICTING:
        return "Authoritative sources disagree; the event stays unresolved."
    if event.verification_status == UNVERIFIED:
        return "Unverified context only. It is not a canonical financial fact."
    if event.materiality == MATERIALITY_CRITICAL:
        return "Authoritative evidence describes a critical issuer event."
    if event.materiality == MATERIALITY_HIGH and event.direction == DIRECTION_NEGATIVE:
        return "Authoritative evidence describes a material negative issuer event."
    if event.materiality == MATERIALITY_HIGH and event.direction == DIRECTION_POSITIVE:
        return "Authoritative evidence describes a material positive issuer event. It does not imply BUY."
    if event.event_type == EVENT_SEC_FILING:
        return "Official SEC disclosure. Routine publication is not automatically high materiality."
    if event.event_type == EVENT_SOCIAL_SIGNAL:
        return "Social discovery only. It cannot become factual truth without independent authority."
    return "Normalized event context for Security Intelligence. It does not change fundamental scores."


def _conflict_directions(items: Sequence[tuple[str, str]]) -> bool:
    dirs = {direction for authority, direction in items if direction in _OPPOSITE}
    authorities = {authority for authority, direction in items if direction in _OPPOSITE}
    if DIRECTION_POSITIVE in dirs and DIRECTION_NEGATIVE in dirs:
        return TIER_1_PRIMARY in authorities or TIER_2_HIGH_QUALITY_SECONDARY in authorities
    return False


def build_event(
    raw: RawSignalInput,
    evidence: Sequence[SignalEvidence],
    *,
    extra_directions: Sequence[tuple[str, str]] = (),
) -> SignalEvent:
    event_type = classify_event_type(raw.event_type)
    if is_social_source(raw.source_type) and event_type in {EVENT_UNKNOWN, EVENT_OTHER, EVENT_NEWS}:
        event_type = EVENT_SOCIAL_SIGNAL
    verification = resolve_event_verification(evidence)
    authority = resolve_event_authority(evidence)
    direction = resolve_direction(event_type=event_type, event_subtype=raw.event_subtype)
    directions = tuple(extra_directions) + tuple(
        (item.source_authority, resolve_direction(event_type=event_type, event_subtype=raw.event_subtype))
        for item in evidence
    )
    if _conflict_directions(directions):
        verification = CONFLICTING
        direction = DIRECTION_UNKNOWN
    materiality, material_reasons = resolve_materiality(
        event_type=event_type,
        event_subtype=raw.event_subtype,
        verification=verification,
        authority=authority,
        contract_value=raw.contract_value,
        revenue=raw.revenue,
        period_compatible=raw.period_compatible,
    )
    if verification == CONFLICTING:
        materiality = MATERIALITY_UNKNOWN
        material_reasons = ("CONFLICTING_EVIDENCE",)
    strength = resolve_strength(
        authority=authority,
        verification=verification,
        materiality=materiality,
        event_time=raw.effective_time or raw.event_time,
    )
    reasons = list(material_reasons)
    if is_social_source(raw.source_type):
        reasons.append("SOCIAL_DISCOVERY_ONLY")
    if verification == VERIFIED:
        reasons.append("AUTHORITATIVE_VERIFICATION")
    event_id = event_identity(raw)
    logical_key = normalize_logical_event_key(raw.logical_event_key) or None
    return SignalEvent(
        event_id=event_id,
        symbol=normalize_symbol(raw.symbol),
        security_id=raw.security_id,
        event_type=event_type,
        event_subtype=str(raw.event_subtype or "").strip().upper() or None,
        headline=raw.headline,
        description=raw.description,
        event_time=raw.event_time,
        effective_time=raw.effective_time,
        source_authority=authority,
        verification_status=verification,
        materiality=materiality,
        direction=direction,
        strength=strength,
        reason_codes=tuple(dict.fromkeys(reasons)),
        evidence_ids=tuple(item.evidence_id for item in evidence),
        factual_subject=normalize_factual_subject(raw.factual_subject) or None,
        raw_reference=raw.raw_reference,
        as_of=raw.as_of or canonical_event_date(raw.effective_time or raw.event_time),
        authoritative_event_id=authoritative_event_id(raw),
        logical_event_key=logical_key or None,
    )


def build_evidence(raw: RawSignalInput, event_id: str) -> SignalEvidence:
    source = resolve_source(raw.source_id, raw.source_type)
    status = evidence_verification(raw, source.authority)
    reasons = []
    if source.discovery_only or is_social_source(source.source_type):
        reasons.append("SOCIAL_NOT_AUTHORITY")
    if status == VERIFIED:
        reasons.append("PRIMARY_SOURCE")
    return SignalEvidence(
        evidence_id=evidence_identity(raw, event_id),
        event_id=event_id,
        symbol=normalize_symbol(raw.symbol),
        source_id=source.source_id,
        source_type=source.source_type,
        source_authority=source.authority,
        source_url=raw.source_url,
        external_id=str(raw.external_id or "").strip() or None,
        retrieved_at=raw.retrieved_at,
        as_of=raw.as_of,
        verification_status=status,
        raw_reference=raw.raw_reference,
        headline=raw.headline,
        reason_codes=tuple(reasons),
    )


def security_signal_from_event(event: SignalEvent) -> SecuritySignal:
    return SecuritySignal(
        event_id=event.event_id,
        symbol=event.symbol,
        event_type=event.event_type,
        event_subtype=event.event_subtype,
        headline=event.headline,
        event_time=event.effective_time or event.event_time,
        source_authority=event.source_authority,
        verification_status=event.verification_status,
        materiality=event.materiality,
        direction=event.direction,
        strength=event.strength,
        reason_codes=event.reason_codes,
        why_it_matters=why_it_matters(event),
        evidence_count=len(event.evidence_ids),
    )


def signal_risk_flags(events: Sequence[SignalEvent]) -> tuple[str, ...]:
    flags: list[str] = []
    for event in events:
        if event.verification_status == CONFLICTING:
            flags.append("SIGNAL_CONFLICT")
        if event.materiality in MATERIAL_LEVELS and event.direction == DIRECTION_NEGATIVE:
            flags.append("MATERIAL_NEGATIVE_SIGNAL")
        if event.event_type == EVENT_SOCIAL_SIGNAL or event.verification_status == UNVERIFIED:
            if event.event_type == EVENT_SOCIAL_SIGNAL:
                flags.append("UNVERIFIED_SOCIAL_CLAIM")
    return tuple(dict.fromkeys(flags))


def signal_snapshot_refs(events: Sequence[SignalEvent]) -> SignalSnapshotRefs:
    material = [
        event
        for event in events
        if event.materiality in MATERIAL_LEVELS and event.verification_status in {VERIFIED, CORROBORATED}
    ]
    latest = None
    if material:
        latest = sorted(
            material,
            key=lambda item: str(item.effective_time or item.event_time or ""),
            reverse=True,
        )[0]
    flags = signal_risk_flags(events)
    latest_id = latest.event_id if latest else None
    latest_at = (latest.effective_time or latest.event_time) if latest else None
    version = hashlib.sha256(
        f"{SIGNAL_ENGINE_VERSION}|{len(material)}|{latest_id or ''}|{latest_at or ''}|{','.join(flags)}".encode("utf-8")
    ).hexdigest()[:16]
    return SignalSnapshotRefs(
        material_signal_count=len(material),
        latest_material_event_id=latest_id,
        latest_material_event_at=latest_at,
        signal_risk_flags=flags,
        signal_state_version=f"{SIGNAL_ENGINE_VERSION}:{version}",
    )


def build_context(symbol: str, events: Sequence[SignalEvent]) -> SignalIntelligenceContext:
    normalized = normalize_symbol(symbol)
    ordered = tuple(
        sorted(events, key=lambda item: str(item.effective_time or item.event_time or ""), reverse=True)
    )
    signals = tuple(security_signal_from_event(event) for event in ordered)
    refs = signal_snapshot_refs(ordered)
    material = tuple(item for item in signals if item.materiality in MATERIAL_LEVELS)
    summary_parts = []
    if refs.material_signal_count:
        summary_parts.append(f"{refs.material_signal_count} material event(s)")
    if refs.signal_risk_flags:
        summary_parts.append(", ".join(refs.signal_risk_flags))
    if not summary_parts:
        summary_parts.append("No verified material signals")
    return SignalIntelligenceContext(
        symbol=normalized,
        contract_version=SIGNAL_CONTRACT_VERSION,
        engine_version=SIGNAL_ENGINE_VERSION,
        recent_signals=signals,
        material_signals=material,
        positive_signals=tuple(item for item in signals if item.direction == DIRECTION_POSITIVE),
        negative_signals=tuple(item for item in signals if item.direction == DIRECTION_NEGATIVE),
        unverified_signals=tuple(item for item in signals if item.verification_status == UNVERIFIED),
        signal_risk_flags=refs.signal_risk_flags,
        latest_material_event_id=refs.latest_material_event_id,
        latest_material_event_at=refs.latest_material_event_at,
        signal_summary="; ".join(summary_parts),
        snapshot_refs=refs,
    )


def compare_signal_state(
    previous: Optional[SignalSnapshotRefs],
    current: SignalSnapshotRefs,
) -> tuple[str, ...]:
    if previous is None:
        flags: list[str] = []
        if current.material_signal_count:
            flags.append(CHANGE_NEW_MATERIAL_SIGNAL)
        if "SIGNAL_CONFLICT" in current.signal_risk_flags:
            flags.append(CHANGE_SIGNAL_CONFLICT_DETECTED)
        return tuple(flags)
    flags = []
    if (
        current.latest_material_event_id
        and current.latest_material_event_id != previous.latest_material_event_id
    ) or current.material_signal_count > previous.material_signal_count:
        flags.append(CHANGE_NEW_MATERIAL_SIGNAL)
    if (
        "SIGNAL_CONFLICT" in current.signal_risk_flags
        and "SIGNAL_CONFLICT" not in previous.signal_risk_flags
    ):
        flags.append(CHANGE_SIGNAL_CONFLICT_DETECTED)
    if (
        current.latest_material_event_id
        and current.latest_material_event_id == previous.latest_material_event_id
        and previous.material_signal_count == 0
        and current.material_signal_count > 0
    ):
        flags.append(CHANGE_SIGNAL_VERIFIED)
    if current.material_signal_count > 0 and previous.material_signal_count == 0:
        if CHANGE_SIGNAL_VERIFIED not in flags:
            flags.append(CHANGE_SIGNAL_VERIFIED)
    return tuple(dict.fromkeys(flags))


def empty_refs() -> SignalSnapshotRefs:
    return SignalSnapshotRefs(signal_state_version=f"{SIGNAL_ENGINE_VERSION}:empty")
