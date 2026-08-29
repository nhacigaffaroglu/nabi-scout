"""Authoritative fixture inputs for Signal Intelligence UAT.

These are synthetic local facts for contract proof. They are not
production filings and do not call providers.
"""

from __future__ import annotations

from services.signal_disclosure_adapters import raw_from_local_sec_filing
from services.signal_intelligence_contract import (
    EVENT_DIVIDEND,
    EVENT_GUIDANCE,
    EVENT_MERGER_ACQUISITION,
    RawSignalInput,
    SOURCE_NEWSWIRE,
    SOURCE_SEC,
    SUBTYPE_BANKRUPTCY,
    SUBTYPE_DIVIDEND_CUT,
    SUBTYPE_DIVIDEND_INCREASE,
    SUBTYPE_FORM_8K,
    SUBTYPE_GUIDANCE_CUT,
)
from services.signal_social_adapter import SocialSignalAdapter


def fixture_sec_8k_verified() -> RawSignalInput:
    return raw_from_local_sec_filing(
        symbol="CRM",
        accession="0001108524-26-000088",
        form="8-K",
        filing_url="https://www.sec.gov/Archives/edgar/data/1108524/000110852426000088/crm-8k.htm",
        filed_at="2026-03-15",
        factual_subject="current report item 2.02 results of operations",
        headline="Salesforce files Form 8-K",
        event_subtype=SUBTYPE_FORM_8K,
    )


def fixture_social_only_claim() -> RawSignalInput:
    return SocialSignalAdapter().raw_from_post(
        symbol="CRM",
        source_id="x:bugra_kurtoglu",
        post_id="fixture-social-001",
        text="CRM will acquire a large private software firm this week.",
        posted_at="2026-03-16T09:00:00+00:00",
        url="https://x.com/bugra_kurtoglu/status/fixture-social-001",
        factual_subject="rumored private software acquisition",
    )


def fixture_merger_sec() -> RawSignalInput:
    return RawSignalInput(
        symbol="CRM",
        source_id="sec",
        source_type=SOURCE_SEC,
        event_type=EVENT_MERGER_ACQUISITION,
        headline="Salesforce files 8-K announcing definitive merger agreement",
        factual_subject="definitive merger agreement exampleco",
        event_time="2026-04-01",
        effective_time="2026-04-01",
        source_url="https://www.sec.gov/Archives/edgar/data/1108524/000110852426000099/crm-8k.htm",
        external_id="0001108524-26-000099",
        authoritative_event_id="0001108524-26-000099",
        raw_reference="sec:accession:0001108524-26-000099",
    )


def fixture_merger_newswire() -> RawSignalInput:
    return RawSignalInput(
        symbol="CRM",
        source_id="newswire",
        source_type=SOURCE_NEWSWIRE,
        event_type=EVENT_MERGER_ACQUISITION,
        headline="Newswire: Salesforce announces definitive merger agreement",
        factual_subject="definitive merger agreement exampleco",
        event_time="2026-04-01",
        effective_time="2026-04-01",
        source_url="https://example.test/newswire/crm-merger",
        external_id="wire-crm-merger-2026-04-01",
        authoritative_event_id="0001108524-26-000099",
        raw_reference="newswire:wire-crm-merger-2026-04-01",
    )


def fixture_conflict_positive() -> RawSignalInput:
    return RawSignalInput(
        symbol="CRM",
        source_id="sec",
        source_type=SOURCE_SEC,
        event_type=EVENT_DIVIDEND,
        event_subtype=SUBTYPE_DIVIDEND_INCREASE,
        headline="Issuer 8-K: dividend increased",
        factual_subject="quarterly dividend declaration 2026-05",
        event_time="2026-05-10",
        effective_time="2026-05-10",
        external_id="0001108524-26-000111",
        authoritative_event_id="0001108524-26-000111",
        raw_reference="sec:accession:0001108524-26-000111",
    )


def fixture_conflict_negative() -> RawSignalInput:
    return RawSignalInput(
        symbol="CRM",
        source_id="official_ir",
        source_type="OFFICIAL_IR",
        event_type=EVENT_DIVIDEND,
        event_subtype=SUBTYPE_DIVIDEND_CUT,
        headline="Issuer IR: dividend reduced",
        factual_subject="quarterly dividend declaration 2026-05",
        event_time="2026-05-10",
        effective_time="2026-05-10",
        external_id="ir-crm-div-2026-05",
        authoritative_event_id="0001108524-26-000111",
        raw_reference="official_ir:ir-crm-div-2026-05",
    )


def fixture_material_negative() -> RawSignalInput:
    return raw_from_local_sec_filing(
        symbol="CRM",
        accession="0001108524-26-000120",
        form="8-K",
        filed_at="2026-06-01",
        factual_subject="chapter 11 bankruptcy filing",
        headline="Issuer files 8-K Item 1.03 bankruptcy",
        event_subtype=SUBTYPE_BANKRUPTCY,
    )


def fixture_material_positive() -> RawSignalInput:
    return RawSignalInput(
        symbol="AAPL",
        source_id="sec",
        source_type=SOURCE_SEC,
        event_type=EVENT_DIVIDEND,
        event_subtype=SUBTYPE_DIVIDEND_INCREASE,
        headline="Apple 8-K: quarterly dividend increased",
        factual_subject="quarterly dividend increase 2026-02",
        event_time="2026-02-06",
        effective_time="2026-02-06",
        external_id="0000320193-26-000020",
        raw_reference="sec:accession:0000320193-26-000020",
    )


def fixture_guidance_cut() -> RawSignalInput:
    return RawSignalInput(
        symbol="CRM",
        source_id="sec",
        source_type=SOURCE_SEC,
        event_type=EVENT_GUIDANCE,
        event_subtype=SUBTYPE_GUIDANCE_CUT,
        headline="Issuer 8-K: full-year guidance reduced",
        factual_subject="fy2026 guidance reduction",
        event_time="2026-03-20",
        effective_time="2026-03-20",
        external_id="0001108524-26-000090",
        raw_reference="sec:accession:0001108524-26-000090",
    )
