from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from services.supabase_admin_client import raise_friendly_rls_error
from services.security_master_contract import SecurityFact


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _identity_key(identifier: str, identifier_type: str, source: str) -> tuple[str, str, str]:
    return (
        str(identifier or "").strip().upper(),
        str(identifier_type or "").strip().upper(),
        str(source or "").strip(),
    )


class SecurityMasterRepository:
    TABLE = "security_master"

    def __init__(self, client=None) -> None:
        self.client = client
        self._memory: Dict[tuple[str, str, str], Dict[str, Any]] = {}

    def upsert_fact(self, fact: SecurityFact) -> Dict[str, Any]:
        key = _identity_key(fact.identifier, fact.identifier_type, fact.source)
        now = _utcnow().isoformat()
        payload = {
            "identifier": key[0],
            "identifier_type": key[1],
            "instrument_type": str(fact.instrument_type).strip().upper(),
            "source": key[2],
            "observed_at": fact.observed_at,
            "symbol": fact.symbol,
            "exchange": fact.exchange,
            "issuer_name": fact.issuer_name,
            "source_reference": fact.source_reference,
            "metadata": dict(fact.metadata or {}),
            "updated_at": now,
        }
        if self.client is None:
            existing = self._memory.get(key)
            if existing is None:
                payload["id"] = str(uuid4())
                payload["created_at"] = now
            else:
                payload["id"] = existing["id"]
                payload["created_at"] = existing.get("created_at") or now
            self._memory[key] = dict(payload)
            return dict(payload)
        payload_with_id = dict(payload)
        try:
            response = (
                self.client.table(self.TABLE)
                .upsert(payload_with_id, on_conflict="identifier,identifier_type,source")
                .execute()
            )
        except Exception as exc:
            raise_friendly_rls_error(exc)
        rows = response.data or []
        return rows[0] if rows else payload_with_id

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
