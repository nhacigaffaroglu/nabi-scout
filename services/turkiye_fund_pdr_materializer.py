"""KAP-only PDR text materialization.

This path is intentionally independent from TEFAS-active broad capture.
It materializes official KAP PDR text only when:
- a current applicable KAP PDR catalog row exists,
- local PDR text is absent,
- official document text can be recovered,
- the PDR parser accepts the document,
- parser output was not renormalized.

Unreconciled but otherwise valid PDRs remain fail-closed downstream.
No production snapshots or decisions are persisted here.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from services.official_kap_pdr import (
    parse_kap_pdr_text,
    report_period_label,
)
from services.official_tefas import normalize_fund_code
from services.turkiye_fund_pdr_window import pdr_row_is_applicable
from services.turkiye_fund_source_capture import (
    OfficialCaptureSession,
    cached_pdr_text_path,
    write_cached_pdr_text,
)
from services.turkiye_fund_text_recovery import (
    recover_official_document_text,
)
from services.turkiye_fund_universe_contract import (
    TEFAS_STATUS_ACTIVE,
)


def _latest_applicable_pdr_row(
    rows: Sequence[Mapping[str, Any]],
    fund_code: str,
    day: date,
) -> Optional[Mapping[str, Any]]:
    code = normalize_fund_code(fund_code)

    matches = [
        row
        for row in rows
        if normalize_fund_code(row.get("fundCode") or "") == code
        and pdr_row_is_applicable(row, day)
    ]

    if not matches:
        return None

    return max(
        matches,
        key=lambda row: (
            int(row.get("year") or 0),
            int(row.get("period") or 0),
            int(row.get("disclosureIndex") or 0),
        ),
    )


def select_kap_only_pdr_recovery_codes(
    identities: Sequence[Any],
    catalog_rows: Sequence[Mapping[str, Any]],
    *,
    as_of: date,
) -> tuple[str, ...]:
    """Missing KAP PDRs excluded from normal TEFAS-active broad capture."""

    selected: list[str] = []

    for identity in identities:
        code = normalize_fund_code(
            getattr(identity, "fund_code", "")
        )

        if not code:
            continue

        if getattr(identity, "tefas_status", None) == TEFAS_STATUS_ACTIVE:
            continue

        if cached_pdr_text_path(code) is not None:
            continue

        if _latest_applicable_pdr_row(
            catalog_rows,
            code,
            as_of,
        ) is None:
            continue

        selected.append(code)

    return tuple(sorted(set(selected)))


def materialize_kap_only_pdr_texts(
    catalog_rows: Sequence[Mapping[str, Any]],
    *,
    session: OfficialCaptureSession,
    as_of: date,
    fund_codes: Sequence[str],
    allow_ocr: bool = False,
) -> dict[str, dict[str, Any]]:
    """Recover and materialize official PDR text without TEFAS dependency."""

    results: dict[str, dict[str, Any]] = {}

    for raw_code in sorted(set(fund_codes)):
        code = normalize_fund_code(raw_code)

        if not code:
            continue

        existing = cached_pdr_text_path(code)

        if existing is not None:
            results[code] = {
                "status": "CACHED",
                "path": str(existing),
            }
            continue

        row = _latest_applicable_pdr_row(
            catalog_rows,
            code,
            as_of,
        )

        if row is None:
            results[code] = {
                "status": "NO_APPLICABLE_PDR",
            }
            continue

        disclosure_index = row.get("disclosureIndex")
        period = report_period_label(
            row.get("year"),
            row.get("period"),
        )

        recovered = recover_official_document_text(
            session,
            file_oid="",
            disclosure_index=disclosure_index,
            document_type="PDR",
            published_at=str(
                row.get("publishDate")
                or ""
            ),
            referer=(
                "https://www.kap.org.tr/tr/Bildirim/"
                f"{disclosure_index}"
            ),
            allow_ocr=allow_ocr,
        )

        text = str(recovered.get("text") or "")

        if not text.strip():
            results[code] = {
                "status": "NO_TEXT",
                "source_layer": recovered.get("source_layer"),
                "pdf_error": recovered.get("pdf_error"),
                "ocr_error": recovered.get("ocr_error"),
                "file_oid": recovered.get("file_oid"),
            }
            continue

        try:
            parsed = parse_kap_pdr_text(
                text,
                fund_code=code,
                report_period=period,
                source_notification_id=str(
                    disclosure_index
                    or ""
                ),
                source_attachment="",
                source_url=(
                    "https://www.kap.org.tr/tr/Bildirim/"
                    f"{disclosure_index}"
                ),
            )
        except Exception as exc:
            results[code] = {
                "status": "PARSE_ERROR",
                "error": str(exc)[:240],
                "source_layer": recovered.get("source_layer"),
                "file_oid": recovered.get("file_oid"),
            }
            continue

        if not parsed.holdings:
            results[code] = {
                "status": "PARSE_EMPTY",
            }
            continue

        if bool(parsed.weights.renormalized):
            results[code] = {
                "status": "RENORMALIZED_REFUSED",
            }
            continue

        path: Path = write_cached_pdr_text(
            code,
            period,
            text,
        )

        results[code] = {
            "status": "MATERIALIZED",
            "path": str(path),
            "file_oid": recovered.get("file_oid"),
            "source_layer": recovered.get("source_layer"),
            "row_count": len(parsed.holdings),
            "reported_weight": parsed.weights.reported_weight_sum,
            "reconciled": bool(
                parsed.weights.weight_reconciled
            ),
            "renormalized": False,
        }

    return results
