"""Public KAP financial-report access vocabulary.

Public website pages and the on-page Excel/Word/PDF export buttons.
Not the paid Veri Yayın Servisi. Not an invented private API.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


KAP_PUBLIC_HOST = "https://kap.org.tr"
KAP_PUBLIC_BILDIRIM_PATH = "/tr/Bildirim/{disclosure_id}"
KAP_PUBLIC_FR_SEARCH_PATH = "/tr/bildirim-sorgu-sonuc?disclosureClass=FR&member={member_id}"
KAP_PUBLIC_EXCEL_EXPORT_PATH = "/tr/api/notification/export/excel/{disclosure_id}"
# Official public Detaylı Sorgulama backend used by kap.org.tr/tr/bildirim-sorgu.
# Not the paid Veri Yayın Servisi. No API key.
KAP_PUBLIC_DETAILED_SEARCH_PATH = "/tr/api/disclosure/members/byCriteria"

SOURCE_PUBLIC_KAP = "PUBLIC_KAP"

PUBLIC_PAGE_AVAILABLE = "PUBLIC_PAGE_AVAILABLE"
PUBLIC_DOWNLOAD_AVAILABLE = "PUBLIC_DOWNLOAD_AVAILABLE"
PUBLIC_STRUCTURED_DATA_AVAILABLE = "PUBLIC_STRUCTURED_DATA_AVAILABLE"
PUBLIC_PATH_BLOCKED = "PUBLIC_PATH_BLOCKED"
SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"

LIMITATION_NETWORK = "PUBLIC_KAP_NETWORK_FAILURE"
LIMITATION_HTTP = "PUBLIC_KAP_HTTP_ERROR"
LIMITATION_NOT_FOUND = "PUBLIC_KAP_REPORT_UNAVAILABLE"
LIMITATION_STRUCTURE = "PUBLIC_KAP_UNEXPECTED_STRUCTURE"
LIMITATION_TAXONOMY = "PUBLIC_KAP_MISSING_TAXONOMY"
LIMITATION_METADATA = "PUBLIC_KAP_MISSING_METADATA"
LIMITATION_SCALE = "PUBLIC_KAP_AMBIGUOUS_SCALE"
LIMITATION_US_SYMBOL = "PUBLIC_KAP_US_SYMBOL_BLOCKED"


def public_bildirim_url(disclosure_id: str) -> str:
    return f"{KAP_PUBLIC_HOST}{KAP_PUBLIC_BILDIRIM_PATH.format(disclosure_id=disclosure_id)}"


def public_fr_search_url(member_id: str) -> str:
    safe = "".join(ch for ch in str(member_id) if ch.isalnum())
    return f"{KAP_PUBLIC_HOST}{KAP_PUBLIC_FR_SEARCH_PATH.format(member_id=safe)}"


def public_detailed_search_url() -> str:
    return f"{KAP_PUBLIC_HOST}{KAP_PUBLIC_DETAILED_SEARCH_PATH}"


TITLE_FINANCIAL_REPORT = "Finansal Rapor"

PERIOD_LABEL_ANNUAL = "Yıllık"
PERIOD_LABEL_3M = "3 Aylık"
PERIOD_LABEL_6M = "6 Aylık"
PERIOD_LABEL_9M = "9 Aylık"

COLUMN_CURRENT = "CURRENT"
COLUMN_COMPARATIVE = "COMPARATIVE"

REFRESH_KEY_KNOWN_NOTIFICATION = "notification_id"
DEDUP_KEY_FIELDS = (
    "symbol",
    "fiscal_year",
    "reporting_basis",
    "notification_id",
)


@dataclass(frozen=True)
class KapFrDiscovery:
    """One public KAP financial-report notification. Not ingested facts."""

    symbol: str
    notification_id: str
    submission_date: str
    year: str
    period: str
    period_label: str
    title: str
    source_url: str
    disclosure_class: str = "FR"
    observed_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "notification_id": self.notification_id,
            "submission_date": self.submission_date,
            "year": self.year,
            "period": self.period,
            "period_label": self.period_label,
            "title": self.title,
            "source_url": self.source_url,
            "disclosure_class": self.disclosure_class,
            "observed_at": self.observed_at,
        }


@dataclass(frozen=True)
class KapPublicAccessStatus:
    page_access: str
    download_access: str
    structured_taxonomy: str
    authentication_required: bool
    paid_service_used: bool
    limitation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_access": self.page_access,
            "download_access": self.download_access,
            "structured_taxonomy": self.structured_taxonomy,
            "authentication_required": self.authentication_required,
            "paid_service_used": self.paid_service_used,
            "limitation": self.limitation,
        }


@dataclass(frozen=True)
class KapPublicTaxonomyRow:
    concept: str
    raw_label: str
    values: tuple[Optional[float], ...]
    current_period: bool
    period_kind: str
    period_start: Optional[str]
    period_end: Optional[str]
    fact_nature: str
    statement_type: str
    period_identity: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "concept": self.concept,
            "raw_label": self.raw_label,
            "values": list(self.values),
            "current_period": self.current_period,
            "period_kind": self.period_kind,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "fact_nature": self.fact_nature,
            "statement_type": self.statement_type,
            "period_identity": self.period_identity,
        }


@dataclass(frozen=True)
class KapPublicFinancialDocument:
    """Structured public report content. Not normalized. Not a verdict."""

    symbol: str
    disclosure_id: str
    source_url: str
    source: str = SOURCE_PUBLIC_KAP
    published_at: Optional[str] = None
    presentation_currency: str = ""
    presentation_unit_label: str = ""
    consolidation: str = ""
    report_year: Optional[str] = None
    report_period_label: Optional[str] = None
    rows: tuple[KapPublicTaxonomyRow, ...] = ()
    observed_concepts: tuple[str, ...] = ()
    cached: bool = False
    limitation: str = ""
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "disclosure_id": self.disclosure_id,
            "source_url": self.source_url,
            "source": self.source,
            "published_at": self.published_at,
            "presentation_currency": self.presentation_currency,
            "presentation_unit_label": self.presentation_unit_label,
            "consolidation": self.consolidation,
            "report_year": self.report_year,
            "report_period_label": self.report_period_label,
            "rows": [item.to_dict() for item in self.rows],
            "observed_concepts": list(self.observed_concepts),
            "cached": self.cached,
            "limitation": self.limitation,
            "provenance": dict(self.provenance or {}),
        }


class KapPublicSourceError(RuntimeError):
    """Public KAP retrieval or parse failed closed."""
