"""Authoritative disclosure adapters for Signal Intelligence.

SEC 8-K metadata is normalized here. Live submissions fetch lives in
SECFinancialClient. KAP / official IR remain interface only.
"""

from __future__ import annotations

from typing import Mapping, Optional

from services.sec_eight_k_discovery import SecEightKFiling, logical_items
from services.sec_eight_k_taxonomy import generic_8k_mapping, map_sec_8k_item
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
    event_type: Optional[str] = None,
) -> RawSignalInput:
    """Map a local SEC filing reference. Does not fetch EDGAR."""
    return RawSignalInput(
        symbol=symbol,
        source_id="sec",
        source_type=SOURCE_SEC,
        event_type=event_type or EVENT_SEC_FILING,
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


def raw_inputs_from_8k_filing(filing: SecEightKFiling) -> tuple[RawSignalInput, ...]:
    """One RawSignalInput per reliable 8-K item; otherwise one generic FORM_8K."""
    event_time = filing.acceptance_at or filing.filing_date
    standalone = logical_items(filing.items)
    if not standalone:
        event_type, subtype = generic_8k_mapping()
        return (
            raw_from_local_sec_filing(
                symbol=filing.symbol,
                accession=filing.accession,
                form=filing.form,
                filing_url=filing.filing_url,
                filed_at=event_time,
                headline=f"SEC {filing.form} {filing.accession}",
                event_subtype=subtype,
                security_id=filing.cik,
                event_type=event_type,
            ),
        )
    rows = []
    for item in standalone:
        event_type, subtype = map_sec_8k_item(item)
        rows.append(
            raw_from_local_sec_filing(
                symbol=filing.symbol,
                accession=filing.accession,
                form=filing.form,
                filing_url=filing.filing_url,
                filed_at=event_time,
                factual_subject=f"sec 8-k item {item}",
                headline=f"SEC {filing.form} {filing.accession} Item {item}",
                event_subtype=subtype,
                logical_event_key=item,
                security_id=filing.cik,
                event_type=event_type,
            )
        )
    return tuple(rows)


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
