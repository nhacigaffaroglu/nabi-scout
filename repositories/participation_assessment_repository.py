from __future__ import annotations

from typing import Any, Dict, List, Optional


class ParticipationAssessmentRepository:
    TABLE = "participation_assessment_snapshots"

    def __init__(self, client) -> None:
        self.client = client

    def append_snapshot(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from services.participation_assessment_persistence_service import (
            hydrate_research_allowed_row,
            research_allowed_column_missing,
        )

        try:
            response = self.client.table(self.TABLE).insert(payload).execute()
        except Exception as exc:
            if not research_allowed_column_missing(exc):
                raise
            fallback = dict(payload)
            fallback.pop("research_allowed", None)
            response = self.client.table(self.TABLE).insert(fallback).execute()
        row = response.data[0] if response.data else payload
        return hydrate_research_allowed_row(row) or row

    def get_latest(self, symbol: str) -> Optional[Dict[str, Any]]:
        normalized = str(symbol or "").strip().upper()
        if not normalized:
            return None
        response = (
            self.client.table(self.TABLE)
            .select("*")
            .eq("symbol", normalized)
            .order("assessed_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        if not rows:
            return None
        from services.participation_assessment_persistence_service import (
            hydrate_research_allowed_row,
        )

        return hydrate_research_allowed_row(rows[0])

    def list_latest_by_symbol(self) -> Dict[str, Dict[str, Any]]:
        response = (
            self.client.table(self.TABLE)
            .select("*")
            .order("assessed_at", desc=True)
            .execute()
        )
        latest: Dict[str, Dict[str, Any]] = {}
        for row in response.data or []:
            symbol = str(row.get("symbol") or "").strip().upper()
            if symbol and symbol not in latest:
                from services.participation_assessment_persistence_service import (
                    hydrate_research_allowed_row,
                )

                hydrated = hydrate_research_allowed_row(row)
                if hydrated is not None:
                    latest[symbol] = hydrated
        return latest

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
            .order("assessed_at", desc=True)
            .limit(max(1, int(limit)))
            .execute()
        )
        from services.participation_assessment_persistence_service import (
            hydrate_research_allowed_row,
        )

        return [
            hydrate_research_allowed_row(row) or row for row in (response.data or [])
        ]
