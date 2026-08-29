"""Signal Intelligence repositories.

Memory store is the default test/UAT path.
Supabase methods exist but production persist is fail-closed until the
additive migration is applied explicitly.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from services.signal_intelligence_contract import SIGNAL_EVENTS_TABLE, SIGNAL_EVIDENCE_TABLE

REQUIRED_SIGNAL_EVENT_COLUMNS = (
    "event_id",
    "symbol",
    "authoritative_event_id",
    "logical_event_key",
    "contract_version",
    "engine_version",
    "created_at",
    "updated_at",
)
REQUIRED_SIGNAL_EVIDENCE_COLUMNS = (
    "evidence_id",
    "event_id",
    "source_type",
    "external_id",
    "contract_version",
    "engine_version",
    "created_at",
    "updated_at",
)


def verify_signal_intelligence_schema(client) -> Tuple[bool, str]:
    """Read-only probe. Never applies DDL."""
    try:
        events = (
            client.table(SIGNAL_EVENTS_TABLE)
            .select(",".join(REQUIRED_SIGNAL_EVENT_COLUMNS))
            .limit(1)
            .execute()
        )
        evidence = (
            client.table(SIGNAL_EVIDENCE_TABLE)
            .select(",".join(REQUIRED_SIGNAL_EVIDENCE_COLUMNS))
            .limit(1)
            .execute()
        )
    except Exception as exc:
        return False, str(exc)[:240]
    if events is None or evidence is None:
        return False, "signal tables returned no response"
    return True, "signal_events and signal_evidence schema verified"


class InMemorySignalIntelligenceRepository:
    def __init__(self) -> None:
        self.events: Dict[str, Dict[str, Any]] = {}
        self.evidence: Dict[str, Dict[str, Any]] = {}
        self.event_writes = 0
        self.evidence_writes = 0

    def get_event(self, event_id: str) -> Optional[Dict[str, Any]]:
        row = self.events.get(event_id)
        return dict(row) if row else None

    def get_evidence(self, evidence_id: str) -> Optional[Dict[str, Any]]:
        row = self.evidence.get(evidence_id)
        return dict(row) if row else None

    def list_events(self, symbol: str) -> List[Dict[str, Any]]:
        normalized = str(symbol or "").strip().upper()
        return [dict(row) for row in self.events.values() if row.get("symbol") == normalized]

    def list_evidence(self, event_id: str) -> List[Dict[str, Any]]:
        return [dict(row) for row in self.evidence.values() if row.get("event_id") == event_id]

    def upsert_event(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.event_writes += 1
        stored = dict(payload)
        self.events[str(payload["event_id"])] = stored
        return dict(stored)

    def upsert_evidence(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.evidence_writes += 1
        stored = dict(payload)
        self.evidence[str(payload["evidence_id"])] = stored
        return dict(stored)


class SignalIntelligenceRepository:
    """Supabase-backed store. Do not call upsert unless migration is applied."""

    def __init__(self, client) -> None:
        self.client = client

    def get_event(self, event_id: str) -> Optional[Dict[str, Any]]:
        response = (
            self.client.table(SIGNAL_EVENTS_TABLE)
            .select("*")
            .eq("event_id", event_id)
            .limit(1)
            .execute()
        )
        rows = response.data if isinstance(response.data, list) else []
        return rows[0] if rows else None

    def get_evidence(self, evidence_id: str) -> Optional[Dict[str, Any]]:
        response = (
            self.client.table(SIGNAL_EVIDENCE_TABLE)
            .select("*")
            .eq("evidence_id", evidence_id)
            .limit(1)
            .execute()
        )
        rows = response.data if isinstance(response.data, list) else []
        return rows[0] if rows else None

    def list_events(self, symbol: str) -> List[Dict[str, Any]]:
        normalized = str(symbol or "").strip().upper()
        if not normalized:
            return []
        response = (
            self.client.table(SIGNAL_EVENTS_TABLE)
            .select("*")
            .eq("symbol", normalized)
            .order("event_time", desc=True)
            .limit(50)
            .execute()
        )
        return response.data if isinstance(response.data, list) else []

    def list_evidence(self, event_id: str) -> List[Dict[str, Any]]:
        response = (
            self.client.table(SIGNAL_EVIDENCE_TABLE)
            .select("*")
            .eq("event_id", event_id)
            .limit(50)
            .execute()
        )
        return response.data if isinstance(response.data, list) else []

    def upsert_event(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        response = (
            self.client.table(SIGNAL_EVENTS_TABLE)
            .upsert(payload, on_conflict="event_id")
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else payload

    def upsert_evidence(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        response = (
            self.client.table(SIGNAL_EVIDENCE_TABLE)
            .upsert(payload, on_conflict="evidence_id")
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else payload
