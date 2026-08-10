from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

STATUS_ACTIVE = "AKTİF"
STATUS_INACTIVE = "PASİF"
LEGACY_ACTIVE_STATUS = "İzle"
READ_ACTIVE_STATUSES = (STATUS_ACTIVE, LEGACY_ACTIVE_STATUS)


class WatchlistRepository:
    def __init__(self, client):
        self.client = client
        self.table = "watchlist"

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _get_row(self, candidate_id: str) -> Optional[Dict[str, Any]]:
        response = (
            self.client.table(self.table)
            .select("*")
            .eq("candidate_id", candidate_id)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else None

    def add_candidate(
        self,
        candidate_id: str,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        existing = self._get_row(candidate_id)
        payload: Dict[str, Any] = {
            "status": STATUS_ACTIVE,
            "updated_at": self._now_iso(),
        }
        if note is not None:
            payload["notes"] = note

        if existing:
            response = (
                self.client.table(self.table)
                .update(payload)
                .eq("id", existing["id"])
                .execute()
            )
            return response.data[0] if response.data else {**existing, **payload}

        insert_payload = {
            "candidate_id": candidate_id,
            "status": STATUS_ACTIVE,
            "notes": note,
            "updated_at": self._now_iso(),
        }
        response = (
            self.client.table(self.table)
            .insert(insert_payload)
            .execute()
        )
        return response.data[0] if response.data else insert_payload

    def deactivate(self, candidate_id: str) -> Optional[Dict[str, Any]]:
        existing = self._get_row(candidate_id)
        if not existing:
            return None
        payload = {
            "status": STATUS_INACTIVE,
            "updated_at": self._now_iso(),
        }
        response = (
            self.client.table(self.table)
            .update(payload)
            .eq("id", existing["id"])
            .execute()
        )
        return response.data[0] if response.data else {**existing, **payload}

    def update_note(
        self,
        candidate_id: str,
        note: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        existing = self._get_row(candidate_id)
        if not existing:
            return None
        payload = {
            "notes": note,
            "updated_at": self._now_iso(),
        }
        response = (
            self.client.table(self.table)
            .update(payload)
            .eq("id", existing["id"])
            .execute()
        )
        return response.data[0] if response.data else {**existing, **payload}

    def list_active(self) -> List[Dict[str, Any]]:
        response = (
            self.client.table(self.table)
            .select("*, investment_candidates(*)")
            .in_("status", list(READ_ACTIVE_STATUSES))
            .order("updated_at", desc=True)
            .execute()
        )
        rows = response.data or []
        results: List[Dict[str, Any]] = []
        for row in rows:
            candidate = row.get("investment_candidates") or {}
            if not candidate:
                continue
            results.append({
                "watchlist_id": row.get("id"),
                "candidate_id": row.get("candidate_id"),
                "status": row.get("status"),
                "notes": row.get("notes"),
                "created_at": row.get("created_at"),
                "updated_at": row.get("updated_at"),
                "candidate": candidate,
            })
        return results

    def get_active_entry(self, candidate_id: str) -> Optional[Dict[str, Any]]:
        response = (
            self.client.table(self.table)
            .select("*")
            .eq("candidate_id", candidate_id)
            .in_("status", list(READ_ACTIVE_STATUSES))
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else None

    def is_watched(self, candidate_id: str) -> bool:
        response = (
            self.client.table(self.table)
            .select("id")
            .eq("candidate_id", candidate_id)
            .in_("status", list(READ_ACTIVE_STATUSES))
            .limit(1)
            .execute()
        )
        return bool(response.data)

    def watched_candidate_ids(self) -> set[str]:
        response = (
            self.client.table(self.table)
            .select("candidate_id")
            .in_("status", list(READ_ACTIVE_STATUSES))
            .execute()
        )
        return {
            str(row["candidate_id"])
            for row in (response.data or [])
            if row.get("candidate_id")
        }
