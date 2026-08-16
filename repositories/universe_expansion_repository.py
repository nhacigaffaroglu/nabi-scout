from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional
from uuid import uuid4

from services.supabase_admin_client import raise_friendly_rls_error
from services.universe_expansion_contract import (
    EXPANSION_STATUS_BLOCKED,
    EXPANSION_STATUS_COMPLETED,
    EXPANSION_STATUS_IN_PROGRESS,
    EXPANSION_STATUS_PENDING,
    EXPANSION_STATUS_RETRYABLE,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper()


class UniverseExpansionRepository:
    TABLE = "universe_expansion_queue"

    def __init__(self, client=None) -> None:
        self.client = client
        self._memory: Dict[str, Dict[str, Any]] = {}

    def _memory_row(self, symbol: str) -> Optional[Dict[str, Any]]:
        return self._memory.get(_normalize_symbol(symbol))

    def upsert_pending(
        self,
        symbol: str,
        *,
        source_universe: str,
        priority: int,
    ) -> Dict[str, Any]:
        normalized = _normalize_symbol(symbol)
        existing = self.get_by_symbol(normalized)
        if existing is not None:
            return existing
        payload = {
            "id": str(uuid4()),
            "symbol": normalized,
            "source_universe": source_universe,
            "priority": int(priority),
            "status": EXPANSION_STATUS_PENDING,
            "attempt_count": 0,
            "provider_calls_used": {},
            "created_at": _utcnow().isoformat(),
            "updated_at": _utcnow().isoformat(),
        }
        if self.client is None:
            self._memory[normalized] = dict(payload)
            return payload
        try:
            response = (
                self.client.table(self.TABLE)
                .upsert(payload, on_conflict="symbol")
                .execute()
            )
        except Exception as exc:
            raise_friendly_rls_error(exc)
        return response.data[0] if response.data else payload

    def get_by_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        normalized = _normalize_symbol(symbol)
        if not normalized:
            return None
        if self.client is None:
            return self._memory_row(normalized)
        response = (
            self.client.table(self.TABLE)
            .select("*")
            .eq("symbol", normalized)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else None

    def list_all(self) -> List[Dict[str, Any]]:
        if self.client is None:
            return list(self._memory.values())
        response = (
            self.client.table(self.TABLE)
            .select("*")
            .order("priority")
            .order("symbol")
            .execute()
        )
        return response.data or []

    def list_eligible(self, now: datetime, *, limit: int = 50) -> List[Dict[str, Any]]:
        rows = self.list_all()
        eligible: List[Dict[str, Any]] = []
        for row in rows:
            status = row.get("status")
            if status == EXPANSION_STATUS_PENDING:
                eligible.append(row)
                continue
            if status == EXPANSION_STATUS_RETRYABLE:
                next_retry = row.get("next_retry_at")
                if not next_retry:
                    eligible.append(row)
                    continue
                retry_at = datetime.fromisoformat(str(next_retry).replace("Z", "+00:00"))
                if retry_at <= now:
                    eligible.append(row)
        eligible.sort(key=lambda item: (item.get("priority", 100), item.get("symbol", "")))
        return eligible[: max(1, limit)]

    def claim(
        self,
        row_id: str,
        *,
        run_id: str,
        now: datetime,
    ) -> Optional[Dict[str, Any]]:
        if self.client is None:
            for symbol, row in self._memory.items():
                if row.get("id") != row_id:
                    continue
                if row.get("status") not in {
                    EXPANSION_STATUS_PENDING,
                    EXPANSION_STATUS_RETRYABLE,
                }:
                    return None
                updated = {
                    **row,
                    "status": EXPANSION_STATUS_IN_PROGRESS,
                    "claimed_at": now.isoformat(),
                    "claim_run_id": run_id,
                    "attempt_count": int(row.get("attempt_count") or 0) + 1,
                    "last_attempt_at": now.isoformat(),
                    "updated_at": now.isoformat(),
                }
                self._memory[symbol] = updated
                return updated
            return None

        current = (
            self.client.table(self.TABLE)
            .select("*")
            .eq("id", row_id)
            .limit(1)
            .execute()
        )
        rows = current.data or []
        if not rows:
            return None
        row = rows[0]
        if row.get("status") not in {
            EXPANSION_STATUS_PENDING,
            EXPANSION_STATUS_RETRYABLE,
        }:
            return None
        payload = {
            "status": EXPANSION_STATUS_IN_PROGRESS,
            "claimed_at": now.isoformat(),
            "claim_run_id": run_id,
            "attempt_count": int(row.get("attempt_count") or 0) + 1,
            "last_attempt_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
        response = (
            self.client.table(self.TABLE)
            .update(payload)
            .eq("id", row_id)
            .in_("status", [EXPANSION_STATUS_PENDING, EXPANSION_STATUS_RETRYABLE])
            .execute()
        )
        return response.data[0] if response.data else None

    def finalize(self, row_id: str, updates: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
        payload = dict(updates)
        payload["updated_at"] = _utcnow().isoformat()
        if self.client is None:
            for symbol, row in self._memory.items():
                if row.get("id") == row_id:
                    merged = {**row, **payload}
                    self._memory[symbol] = merged
                    return merged
            return None
        response = (
            self.client.table(self.TABLE)
            .update(payload)
            .eq("id", row_id)
            .execute()
        )
        return response.data[0] if response.data else None

    def recover_stale_in_progress(
        self,
        now: datetime,
        *,
        stale_minutes: int,
    ) -> int:
        threshold = now - timedelta(minutes=max(1, stale_minutes))
        recovered = 0
        for row in self.list_all():
            if row.get("status") != EXPANSION_STATUS_IN_PROGRESS:
                continue
            claimed_at_raw = row.get("claimed_at") or row.get("last_attempt_at")
            if not claimed_at_raw:
                continue
            claimed_at = datetime.fromisoformat(str(claimed_at_raw).replace("Z", "+00:00"))
            if claimed_at > threshold:
                continue
            self.finalize(
                str(row["id"]),
                {
                    "status": EXPANSION_STATUS_RETRYABLE,
                    "next_retry_at": now.isoformat(),
                    "claimed_at": None,
                    "claim_run_id": None,
                },
            )
            recovered += 1
        return recovered

    def count_by_status(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for row in self.list_all():
            status = str(row.get("status") or "")
            counts[status] = counts.get(status, 0) + 1
        return counts
