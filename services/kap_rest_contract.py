"""Official KAP/MKK REST vocabulary.

Service names only. No URLs. No financial-statement endpoint.
Intended financial path: disclosures → disclosureDetail → downloadAttachment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


KAP_SERVICE_DISCLOSURES = "disclosures"
KAP_SERVICE_DISCLOSURE_DETAIL = "disclosureDetail"
KAP_SERVICE_DOWNLOAD_ATTACHMENT = "downloadAttachment"
KAP_SERVICE_LAST_DISCLOSURE_INDEX = "lastDisclosureIndex"
KAP_SERVICE_MEMBERS = "members"
KAP_SERVICE_MEMBER_DETAIL = "memberDetail"
KAP_SERVICE_FUNDS = "funds"
KAP_SERVICE_FUND_DETAIL = "fundDetail"
KAP_SERVICE_MEMBER_SECURITIES = "memberSecurities"
KAP_SERVICE_BLOCKED_DISCLOSURES = "blockedDisclosures"
KAP_SERVICE_CA_EVENT_STATUS = "caEventStatus"

KAP_DOCUMENTED_SERVICES = frozenset(
    {
        KAP_SERVICE_DISCLOSURES,
        KAP_SERVICE_DISCLOSURE_DETAIL,
        KAP_SERVICE_DOWNLOAD_ATTACHMENT,
        KAP_SERVICE_LAST_DISCLOSURE_INDEX,
        KAP_SERVICE_MEMBERS,
        KAP_SERVICE_MEMBER_DETAIL,
        KAP_SERVICE_FUNDS,
        KAP_SERVICE_FUND_DETAIL,
        KAP_SERVICE_MEMBER_SECURITIES,
        KAP_SERVICE_BLOCKED_DISCLOSURES,
        KAP_SERVICE_CA_EVENT_STATUS,
    }
)

KAP_FINANCIAL_DISCLOSURE_PATH = (
    KAP_SERVICE_DISCLOSURES,
    KAP_SERVICE_DISCLOSURE_DETAIL,
    KAP_SERVICE_DOWNLOAD_ATTACHMENT,
)

CLASSIFICATION_FINANCIAL_CANDIDATE = "FINANCIAL_CANDIDATE"
CLASSIFICATION_NOT_FINANCIAL = "NOT_FINANCIAL"
CLASSIFICATION_NOT_CLASSIFIED = "NOT_CLASSIFIED"
CLASSIFICATION_UNKNOWN = "UNKNOWN"

DOCUMENT_STRUCTURED_PAYLOAD = "STRUCTURED_PAYLOAD"
DOCUMENT_ATTACHMENT_BYTES = "ATTACHMENT_BYTES"
DOCUMENT_UNAVAILABLE = "UNAVAILABLE"

LIMITATION_CONFIG_MISSING = "KAP_CONFIG_MISSING"
LIMITATION_TRANSPORT_UNAVAILABLE = "KAP_TRANSPORT_UNAVAILABLE"
LIMITATION_TRANSPORT_FAILED = "KAP_TRANSPORT_FAILED"
LIMITATION_SERVICE_UNKNOWN = "KAP_SERVICE_UNKNOWN"
LIMITATION_NOT_CLASSIFIED = "KAP_DISCLOSURE_NOT_CLASSIFIED"
LIMITATION_ATTACHMENT_MISSING = "KAP_ATTACHMENT_MISSING"
LIMITATION_SCHEMA_UNSUPPORTED = "KAP_SCHEMA_UNSUPPORTED"


@dataclass(frozen=True)
class KapDisclosureSummary:
    disclosure_id: str
    symbol: Optional[str] = None
    member_code: Optional[str] = None
    published_at: Optional[str] = None
    title: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "disclosure_id": self.disclosure_id,
            "symbol": self.symbol,
            "member_code": self.member_code,
            "published_at": self.published_at,
            "title": self.title,
            "raw": dict(self.raw or {}),
        }


@dataclass(frozen=True)
class KapDisclosureDetail:
    disclosure_id: str
    symbol: Optional[str] = None
    member_code: Optional[str] = None
    published_at: Optional[str] = None
    title: Optional[str] = None
    attachment_ref: Optional[str] = None
    explicit_financial_report_candidate: Optional[bool] = None
    structured_raw_lines: tuple[dict[str, Any], ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "disclosure_id": self.disclosure_id,
            "symbol": self.symbol,
            "member_code": self.member_code,
            "published_at": self.published_at,
            "title": self.title,
            "attachment_ref": self.attachment_ref,
            "explicit_financial_report_candidate": self.explicit_financial_report_candidate,
            "structured_raw_lines": [dict(item) for item in self.structured_raw_lines],
            "raw": dict(self.raw or {}),
        }


@dataclass(frozen=True)
class KapAttachment:
    attachment_ref: str
    available: bool
    content_type: Optional[str] = None
    payload: Optional[bytes] = None
    limitation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "attachment_ref": self.attachment_ref,
            "available": self.available,
            "content_type": self.content_type,
            "payload_bytes": len(self.payload or b""),
            "limitation": self.limitation,
        }


@dataclass(frozen=True)
class KapOfficialDocumentHandoff:
    symbol: str
    disclosure_id: str
    service: str
    document_kind: str
    classification: str
    structured_raw_lines: tuple[dict[str, Any], ...] = ()
    attachment: Optional[KapAttachment] = None
    limitation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "disclosure_id": self.disclosure_id,
            "service": self.service,
            "document_kind": self.document_kind,
            "classification": self.classification,
            "structured_raw_lines": [dict(item) for item in self.structured_raw_lines],
            "attachment": self.attachment.to_dict() if self.attachment else None,
            "limitation": self.limitation,
        }
