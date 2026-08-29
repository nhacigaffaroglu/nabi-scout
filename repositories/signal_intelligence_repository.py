"""Signal Intelligence repositories.

Memory store is the default test/UAT path.
Supabase methods exist but production persist is fail-closed until the
additive migration is applied explicitly.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from services.signal_intelligence_contract import SIGNAL_EVENTS_TABLE, SIGNAL_EVIDENCE_TABLE


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
