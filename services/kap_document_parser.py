"""Parse an official KAP handoff into KapRawFinancialLine rows.

Does not normalize values, classify by headline, or call KAP.
Attachment bytes without structured lines produce no facts.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from services.kap_financial_contract import KAP_SOURCE, KapRawFinancialLine
from services.kap_rest_contract import (
    CLASSIFICATION_FINANCIAL_CANDIDATE,
    DOCUMENT_STRUCTURED_PAYLOAD,
    KapOfficialDocumentHandoff,
)


def _text(raw: Any) -> str:
    return str(raw or "").strip()


def _line_from_payload(raw: Mapping[str, Any]) -> Optional[KapRawFinancialLine]:
    symbol = _text(raw.get("symbol")).upper()
    statement_type = _text(raw.get("statement_type")).upper()
    reporting_period = _text(raw.get("reporting_period")).upper()
    fact_nature = _text(raw.get("fact_nature")).upper()
    currency = _text(raw.get("currency")).upper()
    account_label = _text(raw.get("account_label"))
    if not (symbol and statement_type and reporting_period and fact_nature and currency and account_label):
        return None
    unit_scale = raw.get("unit_scale")
    scale = int(unit_scale) if isinstance(unit_scale, int) else None
    raw_value = raw.get("raw_value")
    value = None if raw_value is None or raw_value == "" else raw_value
    return KapRawFinancialLine(
        symbol=symbol,
        issuer_id=_text(raw.get("issuer_id")) or None,
        statement_type=statement_type,
        period_start=_text(raw.get("period_start")) or None,
        period_end=_text(raw.get("period_end")) or None,
        reporting_period=reporting_period,
        fact_nature=fact_nature,
        consolidation=_text(raw.get("consolidation")).upper() or "UNKNOWN",
        currency=currency,
        unit_scale=scale,
        unit_label=_text(raw.get("unit_label")),
        account_code=_text(raw.get("account_code")).upper() or None,
        account_label=account_label,
        raw_value=value,
        source=_text(raw.get("source")) or KAP_SOURCE,
        source_document_id=_text(raw.get("source_document_id")) or None,
        published_at=_text(raw.get("published_at")) or None,
        as_of=_text(raw.get("as_of")) or None,
        provenance=dict(raw.get("provenance") or {}),
    )


def raw_lines_from_handoff(
    handoff: KapOfficialDocumentHandoff,
) -> tuple[KapRawFinancialLine, ...]:
    if handoff.classification != CLASSIFICATION_FINANCIAL_CANDIDATE:
        return ()
    if handoff.document_kind != DOCUMENT_STRUCTURED_PAYLOAD:
        return ()
    lines: list[KapRawFinancialLine] = []
    for raw in handoff.structured_raw_lines:
        if not isinstance(raw, Mapping):
            continue
        line = _line_from_payload(raw)
        if line is not None:
            lines.append(line)
    return tuple(lines)
