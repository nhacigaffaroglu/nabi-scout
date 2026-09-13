from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


UNDATED_AS_OF_KEY = "UNDATED"


def _authority_instant(row: Dict[str, Any]) -> Optional[datetime]:
    raw = str(row.get("as_of") or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _authority_row_sort_key(row: Dict[str, Any]) -> tuple:
    """Deterministic persisted-authority ordering.

    Freshest evidence instant wins first. Same-instant rows are resolved by
    persistence timestamp, then stable version/id tie-breakers. Comparing UTC
    instants avoids lexicographic mistakes across timezone offsets.
    """
    instant = _authority_instant(row)
    updated = str(row.get("updated_at") or row.get("created_at") or "").strip()
    return (
        1 if instant is not None else 0,
        instant or datetime.min.replace(tzinfo=timezone.utc),
        updated,
        str(row.get("engine_version") or ""),
        str(row.get("facts_version") or ""),
        str(row.get("id") or ""),
    )


class SecurityIntelligenceSnapshotRepository:
    TABLE = "security_intelligence_snapshots"

    def __init__(self, client) -> None:
        self.client = client

    def upsert(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        response = (
            self.client.table(self.TABLE)
            .upsert(
                payload,
                on_conflict="symbol,as_of_key,facts_version,engine_version",
            )
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else payload

    def get_latest(self, symbol: str) -> Optional[Dict[str, Any]]:
        normalized = str(symbol or "").strip().upper()
        if not normalized:
            return None
        rows = self.get_recent_history(normalized, limit=25)
        if not rows:
            return None
        return max(rows, key=_authority_row_sort_key)

    def get_by_identity(
        self,
        symbol: str,
        *,
        as_of_key: str,
        facts_version: str,
        engine_version: str,
    ) -> Optional[Dict[str, Any]]:
        normalized = str(symbol or "").strip().upper()
        response = (
            self.client.table(self.TABLE)
            .select("*")
            .eq("symbol", normalized)
            .eq("as_of_key", as_of_key)
            .eq("facts_version", facts_version)
            .eq("engine_version", engine_version)
            .limit(1)
            .execute()
        )
        rows = response.data if isinstance(response.data, list) else []
        return rows[0] if rows else None

    def get_previous(
        self,
        symbol: str,
        *,
        before_as_of: Optional[str] = None,
        exclude_id: Optional[str] = None,
        facts_version: Optional[str] = None,
        engine_version: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Latest persisted snapshot strictly older than the current evaluation."""
        rows = self.get_recent_history(symbol, limit=25)
        before = str(before_as_of or "").strip()
        for row in rows:
            if exclude_id and str(row.get("id") or "") == str(exclude_id):
                continue
            if facts_version and str(row.get("facts_version") or "") != facts_version:
                continue
            if engine_version and str(row.get("engine_version") or "") != engine_version:
                continue
            as_of = str(row.get("as_of") or "")
            if before and as_of and as_of >= before:
                continue
            if before and not as_of:
                continue
            return row
        return None

    def get_recent_history(
        self,
        symbol: str,
        *,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        normalized = str(symbol or "").strip().upper()
        if not normalized:
            return []
        response = (
            self.client.table(self.TABLE)
            .select("*")
            .eq("symbol", normalized)
            .order("as_of", desc=True, nullsfirst=False)
            .limit(max(1, min(int(limit), 25)))
            .execute()
        )
        return response.data if isinstance(response.data, list) else []
