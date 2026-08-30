"""KAP REST client interface. Fail-closed. No invented URLs. No live HTTP."""

from __future__ import annotations

from typing import Any, Mapping, Optional, Protocol

from services.kap_rest_config import KapRestConfig, load_kap_rest_config
from services.kap_rest_contract import (
    CLASSIFICATION_FINANCIAL_CANDIDATE,
    CLASSIFICATION_NOT_CLASSIFIED,
    CLASSIFICATION_NOT_FINANCIAL,
    CLASSIFICATION_UNKNOWN,
    DOCUMENT_ATTACHMENT_BYTES,
    DOCUMENT_STRUCTURED_PAYLOAD,
    DOCUMENT_UNAVAILABLE,
    KAP_DOCUMENTED_SERVICES,
    KAP_SERVICE_DISCLOSURE_DETAIL,
    KAP_SERVICE_DISCLOSURES,
    KAP_SERVICE_DOWNLOAD_ATTACHMENT,
    KapAttachment,
    KapDisclosureDetail,
    KapDisclosureSummary,
    KapOfficialDocumentHandoff,
    LIMITATION_ATTACHMENT_MISSING,
    LIMITATION_CONFIG_MISSING,
    LIMITATION_NOT_CLASSIFIED,
    LIMITATION_SCHEMA_UNSUPPORTED,
    LIMITATION_SERVICE_UNKNOWN,
    LIMITATION_TRANSPORT_FAILED,
    LIMITATION_TRANSPORT_UNAVAILABLE,
)


class KapRestError(RuntimeError):
    pass


class KapRestUnavailable(KapRestError):
    pass


class KapTransport(Protocol):
    def request(self, service: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
        """Return a fixture/test payload. Must not invent official URLs."""


def _text(raw: Any) -> str:
    return str(raw or "").strip()


def _optional_bool(raw: Any) -> Optional[bool]:
    if raw is True or raw is False:
        return raw
    return None


def classify_financial_disclosure(detail: KapDisclosureDetail) -> str:
    """Classify only from an explicit structured flag.

    Official KAP disclosure-type schema is not documented in-repo.
    Title/headline is never used. Missing flag → NOT_CLASSIFIED.
    """
    flag = detail.explicit_financial_report_candidate
    if flag is True:
        return CLASSIFICATION_FINANCIAL_CANDIDATE
    if flag is False:
        return CLASSIFICATION_NOT_FINANCIAL
    return CLASSIFICATION_NOT_CLASSIFIED


def summary_from_payload(raw: Mapping[str, Any]) -> KapDisclosureSummary:
    payload = dict(raw or {})
    return KapDisclosureSummary(
        disclosure_id=_text(payload.get("disclosure_id") or payload.get("id")),
        symbol=_text(payload.get("symbol")) or None,
        member_code=_text(payload.get("member_code")) or None,
        published_at=_text(payload.get("published_at")) or None,
        title=_text(payload.get("title")) or None,
        raw=payload,
    )


def detail_from_payload(raw: Mapping[str, Any]) -> KapDisclosureDetail:
    payload = dict(raw or {})
    lines = payload.get("structured_raw_lines")
    structured = tuple(dict(item) for item in lines) if isinstance(lines, list) else ()
    return KapDisclosureDetail(
        disclosure_id=_text(payload.get("disclosure_id") or payload.get("id")),
        symbol=_text(payload.get("symbol")) or None,
        member_code=_text(payload.get("member_code")) or None,
        published_at=_text(payload.get("published_at")) or None,
        title=_text(payload.get("title")) or None,
        attachment_ref=_text(payload.get("attachment_ref")) or None,
        explicit_financial_report_candidate=_optional_bool(
            payload.get("explicit_financial_report_candidate")
        ),
        structured_raw_lines=structured,
        raw=payload,
    )


def attachment_from_payload(raw: Mapping[str, Any]) -> KapAttachment:
    payload = dict(raw or {})
    blob = payload.get("payload")
    data = blob if isinstance(blob, (bytes, bytearray)) else None
    available = bool(payload.get("available")) and data is not None
    return KapAttachment(
        attachment_ref=_text(payload.get("attachment_ref")),
        available=available,
        content_type=_text(payload.get("content_type")) or None,
        payload=bytes(data) if data is not None else None,
        limitation="" if available else LIMITATION_ATTACHMENT_MISSING,
    )


def build_official_document_handoff(
    *,
    symbol: str,
    detail: KapDisclosureDetail,
    attachment: Optional[KapAttachment] = None,
) -> KapOfficialDocumentHandoff:
    classification = classify_financial_disclosure(detail)
    if classification == CLASSIFICATION_UNKNOWN:
        classification = CLASSIFICATION_NOT_CLASSIFIED
    if classification != CLASSIFICATION_FINANCIAL_CANDIDATE:
        return KapOfficialDocumentHandoff(
            symbol=symbol,
            disclosure_id=detail.disclosure_id,
            service=KAP_SERVICE_DISCLOSURE_DETAIL,
            document_kind=DOCUMENT_UNAVAILABLE,
            classification=classification,
            limitation=LIMITATION_NOT_CLASSIFIED,
        )
    if detail.structured_raw_lines:
        return KapOfficialDocumentHandoff(
            symbol=symbol,
            disclosure_id=detail.disclosure_id,
            service=KAP_SERVICE_DISCLOSURE_DETAIL,
            document_kind=DOCUMENT_STRUCTURED_PAYLOAD,
            classification=classification,
            structured_raw_lines=detail.structured_raw_lines,
        )
    if attachment is not None and attachment.available:
        return KapOfficialDocumentHandoff(
            symbol=symbol,
            disclosure_id=detail.disclosure_id,
            service=KAP_SERVICE_DOWNLOAD_ATTACHMENT,
            document_kind=DOCUMENT_ATTACHMENT_BYTES,
            classification=classification,
            attachment=attachment,
            limitation=LIMITATION_SCHEMA_UNSUPPORTED
            if not detail.structured_raw_lines
            else "",
        )
    return KapOfficialDocumentHandoff(
        symbol=symbol,
        disclosure_id=detail.disclosure_id,
        service=KAP_SERVICE_DOWNLOAD_ATTACHMENT,
        document_kind=DOCUMENT_UNAVAILABLE,
        classification=classification,
        attachment=attachment,
        limitation=LIMITATION_ATTACHMENT_MISSING,
    )


class KapRestClient:
    """Official KAP access adapter. Bound transport only; no composed live URLs."""

    def __init__(
        self,
        *,
        config: Optional[KapRestConfig] = None,
        transport: Optional[KapTransport] = None,
    ) -> None:
        self.config = config if config is not None else load_kap_rest_config()
        self.transport = transport
        self.call_count = 0

    @property
    def available(self) -> bool:
        return bool(self.config.available and self.transport is not None)

    def _call(self, service: str, params: Optional[Mapping[str, Any]] = None) -> Mapping[str, Any]:
        if service not in KAP_DOCUMENTED_SERVICES:
            raise KapRestError(LIMITATION_SERVICE_UNKNOWN)
        if not self.config.available:
            raise KapRestUnavailable(LIMITATION_CONFIG_MISSING)
        if self.transport is None:
            raise KapRestUnavailable(LIMITATION_TRANSPORT_UNAVAILABLE)
        self.call_count += 1
        try:
            payload = self.transport.request(service, dict(params or {}))
        except KapRestError:
            raise
        except Exception as exc:
            raise KapRestError(LIMITATION_TRANSPORT_FAILED) from exc
        if not isinstance(payload, Mapping):
            raise KapRestError(LIMITATION_TRANSPORT_FAILED)
        return payload

    def list_disclosures(self, *, symbol: str) -> tuple[KapDisclosureSummary, ...]:
        payload = self._call(KAP_SERVICE_DISCLOSURES, {"symbol": symbol})
        rows = payload.get("disclosures")
        if not isinstance(rows, list):
            return ()
        return tuple(summary_from_payload(item) for item in rows if isinstance(item, Mapping))

    def get_disclosure_detail(self, *, disclosure_id: str) -> KapDisclosureDetail:
        payload = self._call(
            KAP_SERVICE_DISCLOSURE_DETAIL, {"disclosure_id": disclosure_id}
        )
        return detail_from_payload(payload)

    def download_attachment(self, *, attachment_ref: str) -> KapAttachment:
        if not _text(attachment_ref):
            return KapAttachment(
                attachment_ref="",
                available=False,
                limitation=LIMITATION_ATTACHMENT_MISSING,
            )
        payload = self._call(
            KAP_SERVICE_DOWNLOAD_ATTACHMENT, {"attachment_ref": attachment_ref}
        )
        return attachment_from_payload(payload)
