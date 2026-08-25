"""Immutable SEC primary-filing evidence identity and digest helpers."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from services.sec_company_facts_evidence import pad_cik
from services.sec_primary_filing_resolver import SECPrimaryFilingRef, build_filing_url

SOURCE_SEC_PRIMARY_FILING = "SEC_PRIMARY_FILING"
CACHE_FORMAT_VERSION = 1
PAYLOAD_SCHEMA_VERSION = "sec-primary-filing-bytes"


class SecFilingEvidenceCacheError(RuntimeError):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def digest_raw_bytes(content: bytes) -> str:
    return hashlib.sha256(bytes(content)).hexdigest()


@dataclass(frozen=True)
class SecFilingEvidence:
    symbol: str
    cik: str
    source: str
    endpoint: str
    retrieved_at: str
    content_digest: str
    payload_schema_version: str
    http_status: int
    accession: str
    form: str
    filing_date: str
    primary_document: str
    fiscal_year: Optional[int]
    raw_bytes: bytes
    cache_format_version: int = CACHE_FORMAT_VERSION

    def to_envelope(self) -> dict[str, Any]:
        return {
            "cache_format_version": self.cache_format_version,
            "source": self.source,
            "endpoint": self.endpoint,
            "cik": self.cik,
            "symbol": self.symbol,
            "retrieved_at": self.retrieved_at,
            "http_status": self.http_status,
            "payload_schema_version": self.payload_schema_version,
            "content_digest": self.content_digest,
            "accession": self.accession,
            "form": self.form,
            "filing_date": self.filing_date,
            "primary_document": self.primary_document,
            "fiscal_year": self.fiscal_year,
        }

    def filing_ref(self) -> SECPrimaryFilingRef:
        return SECPrimaryFilingRef(
            cik=self.cik.lstrip("0") or "0",
            form=self.form,
            fiscal_year=self.fiscal_year,
            filing_date=self.filing_date,
            accession_number=self.accession,
            primary_document=self.primary_document,
            filing_url=self.endpoint,
            retrieved_at=self.retrieved_at,
        )

    @classmethod
    def from_parts(
        cls,
        *,
        envelope: Mapping[str, Any],
        raw_bytes: bytes,
    ) -> "SecFilingEvidence":
        return cls(
            symbol=str(envelope.get("symbol") or "").strip().upper(),
            cik=pad_cik(str(envelope.get("cik") or "")),
            source=str(envelope.get("source") or SOURCE_SEC_PRIMARY_FILING),
            endpoint=str(envelope.get("endpoint") or ""),
            retrieved_at=str(envelope.get("retrieved_at") or ""),
            content_digest=str(envelope.get("content_digest") or ""),
            payload_schema_version=str(
                envelope.get("payload_schema_version") or PAYLOAD_SCHEMA_VERSION
            ),
            http_status=int(envelope.get("http_status") or 0),
            accession=str(envelope.get("accession") or ""),
            form=str(envelope.get("form") or ""),
            filing_date=str(envelope.get("filing_date") or ""),
            primary_document=str(envelope.get("primary_document") or ""),
            fiscal_year=envelope.get("fiscal_year"),
            raw_bytes=raw_bytes,
            cache_format_version=int(
                envelope.get("cache_format_version") or CACHE_FORMAT_VERSION
            ),
        )


def build_filing_evidence(
    *,
    symbol: str,
    cik: str,
    accession: str,
    form: str,
    filing_date: str,
    primary_document: str,
    raw_bytes: bytes,
    fiscal_year: Optional[int] = None,
    http_status: int = 200,
    retrieved_at: Optional[datetime] = None,
    endpoint: Optional[str] = None,
) -> SecFilingEvidence:
    padded = pad_cik(cik)
    retrieved = retrieved_at or _utcnow()
    url = endpoint or build_filing_url(
        cik=padded,
        accession=accession,
        primary_document=primary_document,
    )
    return SecFilingEvidence(
        symbol=str(symbol or "").strip().upper(),
        cik=padded,
        source=SOURCE_SEC_PRIMARY_FILING,
        endpoint=url,
        retrieved_at=retrieved.isoformat(),
        content_digest=digest_raw_bytes(raw_bytes),
        payload_schema_version=PAYLOAD_SCHEMA_VERSION,
        http_status=int(http_status),
        accession=str(accession or "").strip(),
        form=str(form or "").strip(),
        filing_date=str(filing_date or "").strip(),
        primary_document=str(primary_document or "").strip(),
        fiscal_year=int(fiscal_year) if fiscal_year not in (None, "") else None,
        raw_bytes=bytes(raw_bytes),
    )


def verify_filing_digest(evidence: SecFilingEvidence) -> str:
    actual = digest_raw_bytes(evidence.raw_bytes)
    expected = str(evidence.content_digest or "").strip()
    if actual != expected:
        raise SecFilingEvidenceCacheError(
            "SEC filing digest mismatch; cached evidence is corrupt."
        )
    return actual
