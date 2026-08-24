from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

SOURCE_SEC_COMPANY_FACTS = "SEC_COMPANY_FACTS"
CACHE_FORMAT_VERSION = 1
PAYLOAD_SCHEMA_VERSION = "sec-companyfacts-json"
SEC_COMPANY_FACTS_ENDPOINT = (
    "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
)


class SecCompanyFactsCacheError(RuntimeError):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def pad_cik(cik: str) -> str:
    return str(cik).strip().zfill(10)


def company_facts_endpoint(cik: str) -> str:
    return SEC_COMPANY_FACTS_ENDPOINT.format(cik=pad_cik(cik))


def canonical_json_dumps(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def digest_company_facts_payload(payload: Mapping[str, Any]) -> str:
    encoded = canonical_json_dumps(dict(payload)).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class SecCompanyFactsEvidence:
    symbol: str
    cik: str
    source: str
    endpoint: str
    retrieved_at: str
    content_digest: str
    payload_schema_version: str
    http_status: int
    raw_payload: dict[str, Any]
    cache_format_version: int = CACHE_FORMAT_VERSION

    def to_dict(self) -> dict[str, Any]:
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
            "raw_payload": self.raw_payload,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SecCompanyFactsEvidence":
        raw = payload.get("raw_payload")
        if not isinstance(raw, Mapping):
            raise SecCompanyFactsCacheError("Evidence is missing raw_payload.")
        return cls(
            symbol=str(payload.get("symbol") or "").strip().upper(),
            cik=pad_cik(str(payload.get("cik") or "")),
            source=str(payload.get("source") or SOURCE_SEC_COMPANY_FACTS),
            endpoint=str(payload.get("endpoint") or ""),
            retrieved_at=str(payload.get("retrieved_at") or ""),
            content_digest=str(payload.get("content_digest") or ""),
            payload_schema_version=str(
                payload.get("payload_schema_version") or PAYLOAD_SCHEMA_VERSION
            ),
            http_status=int(payload.get("http_status") or 0),
            raw_payload=dict(raw),
            cache_format_version=int(
                payload.get("cache_format_version") or CACHE_FORMAT_VERSION
            ),
        )


def build_company_facts_evidence(
    *,
    symbol: str,
    cik: str,
    raw_payload: Mapping[str, Any],
    http_status: int = 200,
    retrieved_at: Optional[datetime] = None,
) -> SecCompanyFactsEvidence:
    padded = pad_cik(cik)
    payload = dict(raw_payload)
    retrieved = retrieved_at or _utcnow()
    return SecCompanyFactsEvidence(
        symbol=str(symbol or "").strip().upper(),
        cik=padded,
        source=SOURCE_SEC_COMPANY_FACTS,
        endpoint=company_facts_endpoint(padded),
        retrieved_at=retrieved.isoformat(),
        content_digest=digest_company_facts_payload(payload),
        payload_schema_version=PAYLOAD_SCHEMA_VERSION,
        http_status=int(http_status),
        raw_payload=payload,
        cache_format_version=CACHE_FORMAT_VERSION,
    )


def verify_evidence_digest(evidence: SecCompanyFactsEvidence) -> str:
    actual = digest_company_facts_payload(evidence.raw_payload)
    expected = str(evidence.content_digest or "").strip()
    if actual != expected:
        raise SecCompanyFactsCacheError(
            "SEC Company Facts digest mismatch; cached evidence is corrupt."
        )
    return actual
