from typing import Any, Dict, List, Optional

from services.candidate_persistence import (
    execute_with_schema_fallback,
    missing_column_name,
    prepare_candidate_payload,
)
from services.research_workflow_service import (
    ResearchWorkflowSchemaError,
    build_research_workflow_update,
    _UNSET,
)


WORKFLOW_COLUMNS = frozenset({
    "research_status",
    "research_next_action",
    "research_note",
    "last_reviewed_at",
})


class CandidateRepository:
    def __init__(self, client):
        self.client = client
        self.table = "investment_candidates"

    def upsert_by_symbol(self, payload):
        cleaned = prepare_candidate_payload(payload)

        def _write(body):
            response = self.client.table(self.table).upsert(
                body, on_conflict="symbol,market"
            ).execute()
            return response.data[0] if response.data else body

        return execute_with_schema_fallback(cleaned, _write)

    def create(self, payload):
        cleaned = prepare_candidate_payload(payload)

        def _write(body):
            response = self.client.table(self.table).insert(body).execute()
            return response.data[0] if response.data else body

        return execute_with_schema_fallback(cleaned, _write)

    def get_by_id(self, candidate_id):
        response = self.client.table(self.table).select("*").eq(
            "id", candidate_id
        ).limit(1).execute()
        return response.data[0] if response.data else None

    def get_by_symbol(self, symbol: str, market: Optional[str] = None):
        query = (
            self.client.table(self.table)
            .select("*")
            .eq("symbol", symbol.strip().upper())
        )
        if market:
            query = query.eq("market", market)
        response = query.limit(1).execute()
        return response.data[0] if response.data else None

    def list_by_symbol(self, symbol: str) -> List[Dict[str, Any]]:
        normalized = str(symbol or "").strip().upper()
        if not normalized:
            return []
        response = (
            self.client.table(self.table)
            .select("*")
            .eq("symbol", normalized)
            .execute()
        )
        return response.data or []

    def upsert_expansion_candidate(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Reuse the canonical symbol row; never insert an identity-only stub."""
        from services.candidate_identity import (
            expansion_insert_has_usable_enrichment,
            merge_preserving_enriched,
            select_canonical_candidate,
        )

        cleaned = prepare_candidate_payload(payload)
        symbol = str(cleaned.get("symbol") or "").strip().upper()
        existing = self.list_by_symbol(symbol) if symbol else []
        canonical = select_canonical_candidate(existing)
        if canonical and canonical.get("id"):
            patch = merge_preserving_enriched(canonical, cleaned)
            if not patch:
                return canonical
            return self.update(canonical["id"], patch)
        if not expansion_insert_has_usable_enrichment(cleaned):
            return None
        return self.upsert_by_symbol(cleaned)

    def get_all(self, limit=None, order_by="created_at", descending=True):
        query = self.client.table(self.table).select("*").order(
            order_by, desc=descending
        )
        if limit:
            query = query.limit(limit)
        return query.execute().data or []

    def search(self, query="", asset_type=None, market=None,
               decision=None, participation_status=None):
        request = self.client.table(self.table).select("*")
        if query.strip():
            clean = query.strip().replace(",", " ")
            request = request.or_(
                f"symbol.ilike.%{clean}%,company_name.ilike.%{clean}%,sector_theme.ilike.%{clean}%"
            )
        if asset_type:
            request = request.eq("asset_type", asset_type)
        if market:
            request = request.eq("market", market)
        if decision:
            request = request.eq("decision", decision)
        if participation_status:
            request = request.eq("participation_status", participation_status)
        return request.order("nabi_score", desc=True).execute().data or []

    def update(self, candidate_id, payload):
        cleaned = prepare_candidate_payload(payload)

        def _write(body):
            response = self.client.table(self.table).update(body).eq(
                "id", candidate_id
            ).execute()
            return response.data[0] if response.data else body

        return execute_with_schema_fallback(cleaned, _write)

    def delete(self, candidate_id):
        self.client.table(self.table).delete().eq("id", candidate_id).execute()

    def update_research_workflow(
        self,
        candidate_id: str,
        *,
        status: Optional[str] = None,
        next_action: Any = _UNSET,
        research_note: Any = _UNSET,
        last_reviewed_at: Any = _UNSET,
    ) -> Dict[str, Any]:
        payload = build_research_workflow_update(
            status=status,
            next_action=next_action,
            research_note=research_note,
            last_reviewed_at=last_reviewed_at,
        )

        def _write(body: Dict[str, Any]) -> Dict[str, Any]:
            response = (
                self.client.table(self.table)
                .update(body)
                .eq("id", candidate_id)
                .execute()
            )
            return response.data[0] if response.data else body

        try:
            return _write(payload)
        except Exception as exc:
            column = missing_column_name(exc)
            if column and column in WORKFLOW_COLUMNS:
                raise ResearchWorkflowSchemaError(
                    "Araştırma workflow kolonları bulunamadı. "
                    "database/migration_research_workflow.sql dosyasını "
                    "Supabase SQL Editor'da çalıştırın."
                ) from exc
            raise

    def mark_research_reviewed(self, candidate_id: str) -> Dict[str, Any]:
        from datetime import datetime, timezone

        return self.update_research_workflow(
            candidate_id,
            last_reviewed_at=datetime.now(timezone.utc),
        )

    def get_dashboard_stats(self):
        from services.research_workflow_service import (
            is_open_research_status,
            normalize_research_status,
        )

        rows = self.client.table(self.table).select(
            "decision,research_status,participation_status"
        ).execute().data or []
        statuses = [
            normalize_research_status(row.get("research_status"))
            for row in rows
        ]
        return {
            "total": len(rows),
            "strong": sum(r.get("decision") == "GÜÇLÜ ADAY" for r in rows),
            "watch": sum(r.get("decision") == "İZLE" for r in rows),
            "open_research": sum(
                is_open_research_status(status) for status in statuses
            ),
            "incelemde": sum(status == "INCELEMEDE" for status in statuses),
            "tekrar_bak": sum(status == "TEKRAR_BAK" for status in statuses),
            "participation_ok": sum(
                r.get("participation_status") == "Uygun" for r in rows
            ),
        }
