"""Authoritative disclosure adapters for Signal Intelligence.

SEC: normalize already-local filing evidence. No live SEC calls.
KAP / official IR: interface only — no client exists in this repository.
"""

from __future__ import annotations

from typing import Mapping, Optional

from services.signal_intelligence_contract import (
    EVENT_KAP_DISCLOSURE,
    EVENT_SEC_FILING,
    RawSignalInput,
    SOURCE_KAP,
    SOURCE_OFFICIAL_IR,
    SOURCE_SEC,
    SUBTYPE_FORM_10K,
    SUBTYPE_FORM_20F,
    SUBTYPE_FORM_8K,
    SUBTYPE_ROUTINE_FILING,
)


def subtype_from_sec_form(form: Optional[str]) -> str:
    text = str(form or "").strip().upper()
    if text == "8-K":
        return SUBTYPE_FORM_8K
    if text == "10-K":
        return SUBTYPE_FORM_10K
    if text == "20-F":
        return SUBTYPE_FORM_20F
    return SUBTYPE_ROUTINE_FILING


def raw_from_local_sec_filing(
    *,
    symbol: str,
    accession: str,
    form: Optional[str] = None,
    filing_url: Optional[str] = None,
    filed_at: Optional[str] = None,
    factual_subject: Optional[str] = None,
    headline: Optional[str] = None,
    event_subtype: Optional[str] = None,
    logical_event_key: Optional[str] = None,
    security_id: Optional[str] = None,
) -> RawSignalInput:
    """Map a local SEC filing reference. Does not fetch EDGAR."""
    return RawSignalInput(
        symbol=symbol,
        source_id="sec",
        source_type=SOURCE_SEC,
        event_type=EVENT_SEC_FILING,
        event_subtype=event_subtype or subtype_from_sec_form(form),
        headline=headline or f"SEC {form or 'filing'} {accession}",
        factual_subject=factual_subject,
        event_time=filed_at,
        effective_time=filed_at,
        source_url=filing_url,
        external_id=accession,
        authoritative_event_id=accession,
        logical_event_key=logical_event_key,
        raw_reference=f"sec:accession:{accession}",
        security_id=security_id,
        as_of=filed_at,
    )


def raw_from_local_sec_row(row: Mapping[str, object], *, symbol: str) -> RawSignalInput:
    return raw_from_local_sec_filing(
        symbol=symbol,
        accession=str(row.get("accession_number") or row.get("accession") or ""),
        form=str(row.get("form") or "") or None,
        filing_url=str(row.get("filing_url") or row.get("url") or "") or None,
        filed_at=str(row.get("filed_at") or row.get("as_of") or "") or None,
        factual_subject=str(row.get("factual_subject") or "") or None,
        headline=str(row.get("headline") or "") or None,
        logical_event_key=str(row.get("logical_event_key") or row.get("item") or "") or None,
        security_id=str(row.get("security_id") or "") or None,
    )


class KapDisclosureAdapter:
    """KAP is the intended BIST primary disclosure authority.

    No KAP client exists. This adapter records the contract only.
    """

    source_id = "kap"
    source_type = SOURCE_KAP
    event_type = EVENT_KAP_DISCLOSURE
    available = False
    limitation = "No KAP client or disclosure parser exists in the repository."

    def raw_from_disclosure(self, *_args, **_kwargs) -> RawSignalInput:
        raise NotImplementedError(self.limitation)


class OfficialIrAdapter:
    source_id = "official_ir"
    source_type = SOURCE_OFFICIAL_IR
    available = False
    limitation = "No official IR ingest client is wired."

    def raw_from_release(self, *_args, **_kwargs) -> RawSignalInput:
        raise NotImplementedError(self.limitation)
