from typing import Any, Dict, List, Optional

from services.candidate_persistence import (
    execute_with_schema_fallback,
    prepare_candidate_payload,
)


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

    def get_dashboard_stats(self):
        rows = self.client.table(self.table).select(
            "decision,research_status,participation_status"
        ).execute().data or []
        return {
            "total": len(rows),
            "strong": sum(r.get("decision") == "GÜÇLÜ ADAY" for r in rows),
            "watch": sum(r.get("decision") == "İZLE" for r in rows),
            "researching": sum(r.get("research_status") == "İnceleniyor" for r in rows),
            "participation_ok": sum(r.get("participation_status") == "Uygun" for r in rows),
        }
