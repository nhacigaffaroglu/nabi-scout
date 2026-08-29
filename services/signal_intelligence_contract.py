"""Canonical Signal Intelligence contract.

Architecture:
  RAW EVENT → SOURCE EVIDENCE → NORMALIZED EVENT → SIGNAL FACT
  → MATERIALITY → SECURITY IMPACT → SECURITY INTELLIGENCE CONTEXT
  → CHANGE / EXPLANATION

Signals are NOT canonical financial facts. They must never override
SEC/KAP facts, Participation, Security Master identity, or portfolio facts.

LLM may later explain already-normalized signals. It must not invent
events, materiality, scores, Participation, facts, or recommendations.

Sentiment, engagement, and author popularity are not truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

SIGNAL_CONTRACT_VERSION = "signal_contract_8d.1"
SIGNAL_ENGINE_VERSION = "signal_engine_8d.1"

# --- taxonomy ----------------------------------------------------------------

EVENT_EARNINGS = "EARNINGS"
EVENT_GUIDANCE = "GUIDANCE"
EVENT_FINANCIAL_STATEMENT = "FINANCIAL_STATEMENT"
EVENT_SEC_FILING = "SEC_FILING"
EVENT_KAP_DISCLOSURE = "KAP_DISCLOSURE"
EVENT_DIVIDEND = "DIVIDEND"
EVENT_BUYBACK = "BUYBACK"
EVENT_CAPITAL_INCREASE = "CAPITAL_INCREASE"
EVENT_BONUS_ISSUE = "BONUS_ISSUE"
EVENT_SPLIT = "SPLIT"
EVENT_MERGER_ACQUISITION = "MERGER_ACQUISITION"
EVENT_ASSET_SALE = "ASSET_SALE"
EVENT_DEBT_FINANCING = "DEBT_FINANCING"
EVENT_CREDIT_RATING = "CREDIT_RATING"
EVENT_MANAGEMENT_CHANGE = "MANAGEMENT_CHANGE"
EVENT_LEGAL_REGULATORY = "LEGAL_REGULATORY"
EVENT_PRODUCT_LAUNCH = "PRODUCT_LAUNCH"
EVENT_MAJOR_CONTRACT = "MAJOR_CONTRACT"
EVENT_CUSTOMER_CHANGE = "CUSTOMER_CHANGE"
EVENT_SUPPLIER_CHANGE = "SUPPLIER_CHANGE"
EVENT_CYBER_SECURITY = "CYBER_SECURITY"
EVENT_OPERATIONAL_INCIDENT = "OPERATIONAL_INCIDENT"
EVENT_MACRO_EXPOSURE = "MACRO_EXPOSURE"
EVENT_ANALYST_ACTION = "ANALYST_ACTION"
EVENT_NEWS = "NEWS"
EVENT_SOCIAL_SIGNAL = "SOCIAL_SIGNAL"
EVENT_OTHER = "OTHER"
EVENT_UNKNOWN = "UNKNOWN"

EVENT_TYPES = (
    EVENT_EARNINGS,
    EVENT_GUIDANCE,
    EVENT_FINANCIAL_STATEMENT,
    EVENT_SEC_FILING,
    EVENT_KAP_DISCLOSURE,
    EVENT_DIVIDEND,
    EVENT_BUYBACK,
    EVENT_CAPITAL_INCREASE,
    EVENT_BONUS_ISSUE,
    EVENT_SPLIT,
    EVENT_MERGER_ACQUISITION,
    EVENT_ASSET_SALE,
    EVENT_DEBT_FINANCING,
    EVENT_CREDIT_RATING,
    EVENT_MANAGEMENT_CHANGE,
    EVENT_LEGAL_REGULATORY,
    EVENT_PRODUCT_LAUNCH,
    EVENT_MAJOR_CONTRACT,
    EVENT_CUSTOMER_CHANGE,
    EVENT_SUPPLIER_CHANGE,
    EVENT_CYBER_SECURITY,
    EVENT_OPERATIONAL_INCIDENT,
    EVENT_MACRO_EXPOSURE,
    EVENT_ANALYST_ACTION,
    EVENT_NEWS,
    EVENT_SOCIAL_SIGNAL,
    EVENT_OTHER,
    EVENT_UNKNOWN,
)

# --- source types / authority ------------------------------------------------

SOURCE_SEC = "SEC"
SOURCE_KAP = "KAP"
SOURCE_ISSUER_FILING = "ISSUER_FILING"
SOURCE_EXCHANGE_DISCLOSURE = "EXCHANGE_DISCLOSURE"
SOURCE_OFFICIAL_IR = "OFFICIAL_IR"
SOURCE_REGULATOR = "REGULATOR"
SOURCE_NEWSWIRE = "NEWSWIRE"
SOURCE_FINANCIAL_PUBLICATION = "FINANCIAL_PUBLICATION"
SOURCE_RESEARCH = "RESEARCH"
SOURCE_ANALYST = "ANALYST"
SOURCE_SOCIAL_X = "SOCIAL_X"
SOURCE_SOCIAL_REDDIT = "SOCIAL_REDDIT"
SOURCE_SOCIAL_FORUM = "SOCIAL_FORUM"
SOURCE_SOCIAL_OTHER = "SOCIAL_OTHER"
SOURCE_OTHER = "OTHER"

SOURCE_TYPES = (
    SOURCE_SEC,
    SOURCE_KAP,
    SOURCE_ISSUER_FILING,
    SOURCE_EXCHANGE_DISCLOSURE,
    SOURCE_OFFICIAL_IR,
    SOURCE_REGULATOR,
    SOURCE_NEWSWIRE,
    SOURCE_FINANCIAL_PUBLICATION,
    SOURCE_RESEARCH,
    SOURCE_ANALYST,
    SOURCE_SOCIAL_X,
    SOURCE_SOCIAL_REDDIT,
    SOURCE_SOCIAL_FORUM,
    SOURCE_SOCIAL_OTHER,
    SOURCE_OTHER,
)

TIER_1_PRIMARY = "TIER_1_PRIMARY"
TIER_2_HIGH_QUALITY_SECONDARY = "TIER_2_HIGH_QUALITY_SECONDARY"
TIER_3_SECONDARY_ANALYSIS = "TIER_3_SECONDARY_ANALYSIS"
TIER_4_SOCIAL_DISCOVERY = "TIER_4_SOCIAL_DISCOVERY"

AUTHORITY_TIERS = (
    TIER_1_PRIMARY,
    TIER_2_HIGH_QUALITY_SECONDARY,
    TIER_3_SECONDARY_ANALYSIS,
    TIER_4_SOCIAL_DISCOVERY,
)

TIER_1_SOURCE_TYPES = frozenset(
    {
        SOURCE_SEC,
        SOURCE_KAP,
        SOURCE_ISSUER_FILING,
        SOURCE_EXCHANGE_DISCLOSURE,
        SOURCE_OFFICIAL_IR,
        SOURCE_REGULATOR,
    }
)
TIER_2_SOURCE_TYPES = frozenset({SOURCE_NEWSWIRE, SOURCE_FINANCIAL_PUBLICATION})
TIER_3_SOURCE_TYPES = frozenset({SOURCE_RESEARCH, SOURCE_ANALYST})
TIER_4_SOURCE_TYPES = frozenset(
    {SOURCE_SOCIAL_X, SOURCE_SOCIAL_REDDIT, SOURCE_SOCIAL_FORUM, SOURCE_SOCIAL_OTHER}
)

# --- verification / materiality / direction / strength -----------------------

VERIFIED = "VERIFIED"
CORROBORATED = "CORROBORATED"
UNVERIFIED = "UNVERIFIED"
CONFLICTING = "CONFLICTING"
REJECTED = "REJECTED"

VERIFICATION_STATES = (VERIFIED, CORROBORATED, UNVERIFIED, CONFLICTING, REJECTED)

MATERIALITY_CRITICAL = "CRITICAL"
MATERIALITY_HIGH = "HIGH"
MATERIALITY_MEDIUM = "MEDIUM"
MATERIALITY_LOW = "LOW"
MATERIALITY_UNKNOWN = "UNKNOWN"

MATERIALITY_LEVELS = (
    MATERIALITY_CRITICAL,
    MATERIALITY_HIGH,
    MATERIALITY_MEDIUM,
    MATERIALITY_LOW,
    MATERIALITY_UNKNOWN,
)
MATERIAL_LEVELS = frozenset({MATERIALITY_CRITICAL, MATERIALITY_HIGH})

DIRECTION_POSITIVE = "POSITIVE"
DIRECTION_NEGATIVE = "NEGATIVE"
DIRECTION_MIXED = "MIXED"
DIRECTION_NEUTRAL = "NEUTRAL"
DIRECTION_UNKNOWN = "UNKNOWN"

DIRECTIONS = (
    DIRECTION_POSITIVE,
    DIRECTION_NEGATIVE,
    DIRECTION_MIXED,
    DIRECTION_NEUTRAL,
    DIRECTION_UNKNOWN,
)

STRENGTH_STRONG = "STRONG"
STRENGTH_MODERATE = "MODERATE"
STRENGTH_WEAK = "WEAK"
STRENGTH_UNKNOWN = "UNKNOWN"

STRENGTH_LEVELS = (STRENGTH_STRONG, STRENGTH_MODERATE, STRENGTH_WEAK, STRENGTH_UNKNOWN)

CHANGE_NEW_MATERIAL_SIGNAL = "NEW_MATERIAL_SIGNAL"
CHANGE_SIGNAL_CONFLICT_DETECTED = "SIGNAL_CONFLICT_DETECTED"
CHANGE_SIGNAL_VERIFIED = "SIGNAL_VERIFIED"

SIGNAL_CHANGE_FLAGS = (
    CHANGE_NEW_MATERIAL_SIGNAL,
    CHANGE_SIGNAL_CONFLICT_DETECTED,
    CHANGE_SIGNAL_VERIFIED,
)

SIGNAL_EVENTS_TABLE = "signal_events"
SIGNAL_EVIDENCE_TABLE = "signal_evidence"

# Controlled subtypes used for deterministic materiality/direction.
# Unknown subtypes stay UNKNOWN; they are never inferred from headlines.
SUBTYPE_BANKRUPTCY = "BANKRUPTCY"
SUBTYPE_SANCTION = "SANCTION"
SUBTYPE_GUIDANCE_RAISE = "GUIDANCE_RAISE"
SUBTYPE_GUIDANCE_CUT = "GUIDANCE_CUT"
SUBTYPE_GUIDANCE_WITHDRAW = "GUIDANCE_WITHDRAW"
SUBTYPE_DIVIDEND_INCREASE = "DIVIDEND_INCREASE"
SUBTYPE_DIVIDEND_CUT = "DIVIDEND_CUT"
SUBTYPE_DIVIDEND_SUSPEND = "DIVIDEND_SUSPEND"
SUBTYPE_RATING_UPGRADE = "RATING_UPGRADE"
SUBTYPE_RATING_DOWNGRADE = "RATING_DOWNGRADE"
SUBTYPE_FORM_10K = "FORM_10K"
SUBTYPE_FORM_20F = "FORM_20F"
SUBTYPE_FORM_8K = "FORM_8K"
SUBTYPE_ROUTINE_FILING = "ROUTINE_FILING"

# Materiality rules (deterministic, evidence-based, not sentiment):
# - UNKNOWN when event_type is OTHER/UNKNOWN or evidence is missing.
# - CRITICAL: TIER 1 VERIFIED bankruptcy / major sanction.
# - HIGH: TIER 1 VERIFIED M&A, guidance withdraw/cut, material legal sanction,
#   cyber/operational incident; numeric contract/revenue ratio only when both
#   values are present and period_compatible.
# - MEDIUM: TIER 1 dividend/buyback/split/bonus/8-K without critical subtype;
#   TIER 2 corroborated M&A/guidance.
# - LOW: routine financial-statement publication, analyst action, generic news.
# - Social-only claims are UNKNOWN materiality (discovery, not fact).
#
# Direction rules (factual subtype / event type only):
# - POSITIVE: dividend increase, guidance raise, buyback, rating upgrade.
# - NEGATIVE: dividend cut/suspend, guidance cut/withdraw, bankruptcy,
#   sanction, capital increase, rating downgrade, cyber, operational incident.
# - MIXED: M&A / asset sale without acquirer/target role.
# - UNKNOWN: management change, social-only, OTHER, missing subtype.
# Direction never implies BUY / investable.
#
# Event identity priority (never headline-only):
# 1. Authoritative external event id — SEC accession, KAP disclosure id,
#    issuer / exchange / regulator event id.
# 2. Authoritative deterministic composite — same primary id plus an
#    explicit logical_event_key when one source document exposes multiple
#    logical events (for example one 8-K accession with Item 2.02 and 5.02).
# 3. Canonical fingerprint fallback — symbol, event_type, effective/event
#    date, normalized factual subject.
# Secondary sources join an existing event only by citing the same
# authoritative_event_id. A newswire article id is evidence identity, not
# event identity.


@dataclass(frozen=True)
class RawSignalInput:
    """Normalized ingest input. Do not persist the original provider payload."""

    symbol: str
    source_id: str
    source_type: str
    event_type: Optional[str] = None
    event_subtype: Optional[str] = None
    headline: Optional[str] = None
    description: Optional[str] = None
    factual_subject: Optional[str] = None
    event_time: Optional[str] = None
    effective_time: Optional[str] = None
    source_url: Optional[str] = None
    external_id: Optional[str] = None
    authoritative_event_id: Optional[str] = None
    logical_event_key: Optional[str] = None
    evidence_id: Optional[str] = None
    retrieved_at: Optional[str] = None
    as_of: Optional[str] = None
    security_id: Optional[str] = None
    contract_value: Optional[float] = None
    revenue: Optional[float] = None
    period_compatible: bool = False
    raw_reference: Optional[str] = None
    rejected: bool = False


@dataclass(frozen=True)
class SignalEvidence:
    evidence_id: str
    event_id: str
    symbol: str
    source_id: str
    source_type: str
    source_authority: str
    source_url: Optional[str]
    external_id: Optional[str]
    retrieved_at: Optional[str]
    as_of: Optional[str]
    verification_status: str
    raw_reference: Optional[str]
    headline: Optional[str]
    reason_codes: tuple[str, ...] = ()
    contract_version: str = SIGNAL_CONTRACT_VERSION
    engine_version: str = SIGNAL_ENGINE_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "event_id": self.event_id,
            "symbol": self.symbol,
            "source_id": self.source_id,
            "source_type": self.source_type,
            "source_authority": self.source_authority,
            "source_url": self.source_url,
            "external_id": self.external_id,
            "retrieved_at": self.retrieved_at,
            "as_of": self.as_of,
            "verification_status": self.verification_status,
            "raw_reference": self.raw_reference,
            "headline": self.headline,
            "reason_codes": list(self.reason_codes),
            "contract_version": self.contract_version,
            "engine_version": self.engine_version,
        }


@dataclass(frozen=True)
class SignalEvent:
    event_id: str
    symbol: str
    security_id: Optional[str]
    event_type: str
    event_subtype: Optional[str]
    headline: Optional[str]
    description: Optional[str]
    event_time: Optional[str]
    effective_time: Optional[str]
    source_authority: str
    verification_status: str
    materiality: str
    direction: str
    strength: str
    reason_codes: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    factual_subject: Optional[str]
    raw_reference: Optional[str]
    as_of: Optional[str]
    authoritative_event_id: Optional[str] = None
    logical_event_key: Optional[str] = None
    contract_version: str = SIGNAL_CONTRACT_VERSION
    engine_version: str = SIGNAL_ENGINE_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "symbol": self.symbol,
            "security_id": self.security_id,
            "event_type": self.event_type,
            "event_subtype": self.event_subtype,
            "headline": self.headline,
            "description": self.description,
            "event_time": self.event_time,
            "effective_time": self.effective_time,
            "source_authority": self.source_authority,
            "verification_status": self.verification_status,
            "materiality": self.materiality,
            "direction": self.direction,
            "strength": self.strength,
            "reason_codes": list(self.reason_codes),
            "evidence_ids": list(self.evidence_ids),
            "factual_subject": self.factual_subject,
            "raw_reference": self.raw_reference,
            "as_of": self.as_of,
            "authoritative_event_id": self.authoritative_event_id,
            "logical_event_key": self.logical_event_key,
            "contract_version": self.contract_version,
            "engine_version": self.engine_version,
        }


@dataclass(frozen=True)
class SecuritySignal:
    event_id: str
    symbol: str
    event_type: str
    event_subtype: Optional[str]
    headline: Optional[str]
    event_time: Optional[str]
    source_authority: str
    verification_status: str
    materiality: str
    direction: str
    strength: str
    reason_codes: tuple[str, ...]
    why_it_matters: str
    evidence_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "symbol": self.symbol,
            "event_type": self.event_type,
            "event_subtype": self.event_subtype,
            "headline": self.headline,
            "event_time": self.event_time,
            "source_authority": self.source_authority,
            "verification_status": self.verification_status,
            "materiality": self.materiality,
            "direction": self.direction,
            "strength": self.strength,
            "reason_codes": list(self.reason_codes),
            "why_it_matters": self.why_it_matters,
            "evidence_count": self.evidence_count,
        }


@dataclass(frozen=True)
class SignalSnapshotRefs:
    """Compact SI-history references. Never embed news payloads."""

    material_signal_count: int = 0
    latest_material_event_id: Optional[str] = None
    latest_material_event_at: Optional[str] = None
    signal_risk_flags: tuple[str, ...] = ()
    signal_state_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "material_signal_count": self.material_signal_count,
            "latest_material_event_id": self.latest_material_event_id,
            "latest_material_event_at": self.latest_material_event_at,
            "signal_risk_flags": list(self.signal_risk_flags),
            "signal_state_version": self.signal_state_version,
        }


@dataclass(frozen=True)
class SignalIntelligenceContext:
    symbol: str
    contract_version: str = SIGNAL_CONTRACT_VERSION
    engine_version: str = SIGNAL_ENGINE_VERSION
    recent_signals: tuple[SecuritySignal, ...] = ()
    material_signals: tuple[SecuritySignal, ...] = ()
    positive_signals: tuple[SecuritySignal, ...] = ()
    negative_signals: tuple[SecuritySignal, ...] = ()
    unverified_signals: tuple[SecuritySignal, ...] = ()
    signal_risk_flags: tuple[str, ...] = ()
    latest_material_event_id: Optional[str] = None
    latest_material_event_at: Optional[str] = None
    signal_summary: str = ""
    snapshot_refs: SignalSnapshotRefs = field(default_factory=SignalSnapshotRefs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "contract_version": self.contract_version,
            "engine_version": self.engine_version,
            "recent_signals": [item.to_dict() for item in self.recent_signals],
            "material_signals": [item.to_dict() for item in self.material_signals],
            "positive_signals": [item.to_dict() for item in self.positive_signals],
            "negative_signals": [item.to_dict() for item in self.negative_signals],
            "unverified_signals": [item.to_dict() for item in self.unverified_signals],
            "signal_risk_flags": list(self.signal_risk_flags),
            "latest_material_event_id": self.latest_material_event_id,
            "latest_material_event_at": self.latest_material_event_at,
            "signal_summary": self.signal_summary,
            "snapshot_refs": self.snapshot_refs.to_dict(),
        }


def empty_signal_context(symbol: str) -> SignalIntelligenceContext:
    return SignalIntelligenceContext(symbol=str(symbol or "").strip().upper())
