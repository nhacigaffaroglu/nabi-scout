"""Hand public KAP taxonomy rows into the existing KAP financial pipeline.

Does not evaluate or persist Participation. Does not infer business activity.
"""

from __future__ import annotations

from typing import Any, Optional

from services.kap_document_parser import raw_lines_from_handoff
from services.kap_financial_bridge import (
    KapIdentityError,
    build_kap_normalized_bundle,
    is_us_symbol_blocked_from_kap,
    participation_inputs_from_kap,
)
from services.kap_financial_contract import (
    EXPLICIT_UNIT_SCALES,
    KapNormalizedBundle,
    KapRawFinancialLine,
)
from services.kap_public_contract import (
    LIMITATION_SCALE,
    LIMITATION_US_SYMBOL,
    SOURCE_PUBLIC_KAP,
    KapPublicFinancialDocument,
    KapPublicSourceError,
)
from services.kap_rest_contract import (
    CLASSIFICATION_FINANCIAL_CANDIDATE,
    DOCUMENT_STRUCTURED_PAYLOAD,
    KapOfficialDocumentHandoff,
)
from services.participation_financial_contract import ParticipationFinancialInputs


def _unit_scale(unit_label: str) -> Optional[int]:
    return EXPLICIT_UNIT_SCALES.get(str(unit_label or "").strip().upper())


def structured_payloads_from_public(
    document: KapPublicFinancialDocument,
) -> tuple[dict[str, Any], ...]:
    """KapRawFinancialLine-shaped dicts. No normalization."""
    scale = _unit_scale(document.presentation_unit_label)
    payloads: list[dict[str, Any]] = []
    for row in document.rows:
        if not row.values or row.values[0] is None:
            continue
        payloads.append(
            {
                "symbol": document.symbol,
                "issuer_id": document.disclosure_id,
                "statement_type": row.statement_type,
                "period_start": row.period_start,
                "period_end": row.period_end,
                "reporting_period": row.period_kind,
                "fact_nature": row.fact_nature,
                "consolidation": document.consolidation,
                "currency": document.presentation_currency,
                "unit_scale": scale,
                "unit_label": document.presentation_unit_label,
                "account_code": row.concept,
                "account_label": row.raw_label or row.concept,
                "raw_value": row.values[0],
                "source": SOURCE_PUBLIC_KAP,
                "source_document_id": document.disclosure_id,
                "published_at": document.published_at,
                "as_of": row.period_end or document.published_at,
                "provenance": {
                    "source": SOURCE_PUBLIC_KAP,
                    "source_url": document.source_url,
                    "taxonomy": row.concept,
                    "period_identity": row.period_identity,
                    "cached": document.cached,
                },
            }
        )
    return tuple(payloads)


def raw_lines_from_public(document: KapPublicFinancialDocument) -> tuple[KapRawFinancialLine, ...]:
    if _unit_scale(document.presentation_unit_label) is None:
        raise KapPublicSourceError(LIMITATION_SCALE)
    handoff = KapOfficialDocumentHandoff(
        symbol=document.symbol,
        disclosure_id=document.disclosure_id,
        service="public_bildirim",
        document_kind=DOCUMENT_STRUCTURED_PAYLOAD,
        classification=CLASSIFICATION_FINANCIAL_CANDIDATE,
        structured_raw_lines=structured_payloads_from_public(document),
    )
    return raw_lines_from_handoff(handoff)


def ingest_public_kap_financials(
    document: KapPublicFinancialDocument,
    *,
    symbol: Optional[str] = None,
) -> KapNormalizedBundle:
    ticker = (symbol or document.symbol).upper()
    if is_us_symbol_blocked_from_kap(ticker):
        raise KapIdentityError(LIMITATION_US_SYMBOL)
    return build_kap_normalized_bundle(ticker, raw_lines_from_public(document))


def participation_inputs_from_public(
    document: KapPublicFinancialDocument,
    *,
    symbol: Optional[str] = None,
) -> tuple[ParticipationFinancialInputs, tuple[str, ...]]:
    bundle = ingest_public_kap_financials(document, symbol=symbol)
    return participation_inputs_from_kap(bundle)
