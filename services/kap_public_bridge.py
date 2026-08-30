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
from services.kap_eps_normalization import (
    BASIS_ONE_TRY,
    candidate_from_row,
    is_eps_concept,
    select_canonical_eps,
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
    eps_candidates = []
    for row in document.rows:
        if not row.values or row.values[0] is None:
            continue
        if is_eps_concept(row.concept):
            candidate = candidate_from_row(
                row,
                notification_id=document.disclosure_id,
                reporting_basis=document.consolidation,
            )
            if candidate is not None:
                eps_candidates.append(candidate)
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
    chosen = select_canonical_eps(eps_candidates)
    if chosen is not None and chosen.canonical_value is not None:
        payloads.append(
            {
                "symbol": document.symbol,
                "issuer_id": document.disclosure_id,
                "statement_type": "INCOME",
                "period_start": None,
                "period_end": chosen.period_end,
                "reporting_period": chosen.period_kind,
                "fact_nature": "FLOW",
                "consolidation": document.consolidation,
                "currency": document.presentation_currency or "TRY",
                "unit_scale": 1,
                "unit_label": "TRY",
                "account_code": chosen.taxonomy_concept,
                "account_label": chosen.reported_label or chosen.taxonomy_concept,
                "raw_value": float(chosen.canonical_value),
                "source": SOURCE_PUBLIC_KAP,
                "source_document_id": document.disclosure_id,
                "published_at": document.published_at,
                "as_of": chosen.period_end or document.published_at,
                "provenance": {
                    "source": SOURCE_PUBLIC_KAP,
                    "source_url": document.source_url,
                    "taxonomy": chosen.taxonomy_concept,
                    "typed_dimension": chosen.typed_dimension,
                    "eps_normalization": BASIS_ONE_TRY,
                    "share_nominal_basis": chosen.share_nominal_basis,
                    "share_count_basis": chosen.share_count_basis,
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
