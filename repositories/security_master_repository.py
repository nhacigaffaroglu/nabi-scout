from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence
from uuid import uuid4

from services.supabase_admin_client import raise_friendly_rls_error
from services.security_master_contract import SecurityFact

ACTION_INSERTED = "inserted"
ACTION_UPDATED = "updated"
ACTION_UNCHANGED = "unchanged"

_CONTENT_FIELDS = (
    "identifier",
    "identifier_type",
    "instrument_type",
    "source",
    "symbol",
    "exchange",
    "issuer_name",
    "source_reference",
)
_UPSERT_CHUNK_SIZE = 250


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _identity_key(identifier: str, identifier_type: str, source: str) -> tuple[str, str, str]:
    return (
        str(identifier or "").strip().upper(),
        str(identifier_type or "").strip().upper(),
        str(source or "").strip(),
    )


def _norm_text(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    return text or None


def _norm_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, Any] = {}
    for key, item in value.items():
        if item is None:
            continue
        normalized[str(key)] = item if isinstance(item, (dict, list, int, float, bool)) else str(item)
    return normalized


def facts_content_equal(existing: Dict[str, Any], payload: Dict[str, Any]) -> bool:
    """Compare persisted fact content, ignoring ids and timestamps."""
    for field in _CONTENT_FIELDS:
        if _norm_text(existing.get(field)) != _norm_text(payload.get(field)):
            return False
    return json.dumps(_norm_metadata(existing.get("metadata")), sort_keys=True) == json.dumps(
        _norm_metadata(payload.get("metadata")),
        sort_keys=True,
    )


@dataclass(frozen=True)
class PersistFactsResult:
    inserted: int
    updated: int
    unchanged: int
    rows: List[Dict[str, Any]]


class SecurityMasterRepository:
    TABLE = "security_master"

    def __init__(self, client=None) -> None:
        self.client = client
        self._memory: Dict[tuple[str, str, str], Dict[str, Any]] = {}

    def _payload_from_fact(self, fact: SecurityFact) -> Dict[str, Any]:
        key = _identity_key(fact.identifier, fact.identifier_type, fact.source)
        return {
            "identifier": key[0],
            "identifier_type": key[1],
            "instrument_type": str(fact.instrument_type).strip().upper(),
            "source": key[2],
            "observed_at": fact.observed_at,
            "symbol": _norm_text(fact.symbol),
            "exchange": _norm_text(fact.exchange),
            "issuer_name": _norm_text(fact.issuer_name),
            "source_reference": _norm_text(fact.source_reference),
            "metadata": _norm_metadata(fact.metadata),
        }

    def upsert_fact(self, fact: SecurityFact) -> Dict[str, Any]:
        result = self.persist_facts([fact])
        if result.rows:
            return dict(result.rows[0])
        return self._payload_from_fact(fact)

    def persist_facts(self, facts: Sequence[SecurityFact]) -> PersistFactsResult:
        """Insert or update facts; skip writes when content is unchanged."""
        existing = {
            _identity_key(row.get("identifier"), row.get("identifier_type"), row.get("source")): dict(row)
            for row in self.list_all()
        }
        to_write: List[Dict[str, Any]] = []
        returned: List[Dict[str, Any]] = []
        inserted = updated = unchanged = 0
        seen: set[tuple[str, str, str]] = set()
        now = _utcnow().isoformat()
        for fact in facts:
            payload = self._payload_from_fact(fact)
            key = _identity_key(payload["identifier"], payload["identifier_type"], payload["source"])
            if not key[0] or key in seen:
                continue
            seen.add(key)
            current = existing.get(key)
            if current is not None and facts_content_equal(current, payload):
                unchanged += 1
                returned.append(dict(current))
                continue
            write_payload = dict(payload)
            write_payload["updated_at"] = now
            if current is None:
                inserted += 1
            else:
                updated += 1
            to_write.append(write_payload)
        written = self._write_payloads(to_write)
        written_by_key = {
            _identity_key(row.get("identifier"), row.get("identifier_type"), row.get("source")): dict(row)
            for row in written
        }
        for payload in to_write:
            key = _identity_key(payload["identifier"], payload["identifier_type"], payload["source"])
            returned.append(written_by_key.get(key) or dict(payload))
        return PersistFactsResult(
            inserted=inserted,
            updated=updated,
            unchanged=unchanged,
            rows=returned,
        )

    def _write_payloads(self, payloads: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not payloads:
            return []
        if self.client is None:
            written: List[Dict[str, Any]] = []
            now = _utcnow().isoformat()
            for payload in payloads:
                key = _identity_key(
                    payload["identifier"],
                    payload["identifier_type"],
                    payload["source"],
                )
                existing = self._memory.get(key)
                stored = dict(payload)
                if existing is None:
                    stored["id"] = str(uuid4())
                    stored["created_at"] = stored.get("updated_at") or now
                else:
                    stored["id"] = existing["id"]
                    stored["created_at"] = existing.get("created_at") or now
                self._memory[key] = dict(stored)
                written.append(dict(stored))
            return written
        written = []
        try:
            table = self.client.table(self.TABLE)
            for start in range(0, len(payloads), _UPSERT_CHUNK_SIZE):
                chunk = [dict(item) for item in payloads[start : start + _UPSERT_CHUNK_SIZE]]
                response = table.upsert(chunk, on_conflict="identifier,identifier_type,source").execute()
                written.extend(response.data or chunk)
        except Exception as exc:
            raise_friendly_rls_error(exc)
        return written

    def list_facts(
        self,
        identifier: str,
        *,
        identifier_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        ident = str(identifier or "").strip().upper()
        if not ident:
            return []
        type_filter = str(identifier_type or "").strip().upper()
        if self.client is None:
            rows = [
                dict(row)
                for key, row in self._memory.items()
                if key[0] == ident and (not type_filter or key[1] == type_filter)
            ]
            rows.sort(key=lambda item: (item.get("source") or "", item.get("observed_at") or ""))
            return rows
        query = self.client.table(self.TABLE).select("*").eq("identifier", ident)
        if type_filter:
            query = query.eq("identifier_type", type_filter)
        response = query.order("source").execute()
        return response.data or []

    def list_all(self, *, page_size: int = 1000) -> List[Dict[str, Any]]:
        if self.client is None:
            return [dict(row) for row in self._memory.values()]
        rows: List[Dict[str, Any]] = []
        start = 0
        page = max(1, int(page_size))
        while True:
            end = start + page - 1
            response = (
                self.client.table(self.TABLE)
                .select("*")
                .order("identifier")
                .order("identifier_type")
                .order("source")
                .range(start, end)
                .execute()
            )
            chunk = response.data or []
            rows.extend(chunk)
            if len(chunk) < page:
                break
            start += page
        return rows

    def count(self) -> int:
        if self.client is None:
            return len(self._memory)
        response = (
            self.client.table(self.TABLE)
            .select("id", count="exact")
            .limit(1)
            .execute()
        )
        return int(getattr(response, "count", None) or 0)
