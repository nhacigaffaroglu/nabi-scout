from typing import Any, Dict, List, Optional


class CandidateRepository:
    def __init__(self, client) -> None:
        self.client = client
        self.table = "investment_candidates"

    def create(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        response = self.client.table(self.table).insert(payload).execute()
        return response.data[0] if response.data else payload

    def get_by_id(self, candidate_id: str) -> Optional[Dict[str, Any]]:
        response = (
            self.client.table(self.table)
            .select("*")
            .eq("id", candidate_id)
            .limit(1)
            .execute()
        )
        return response.data[0] if response.data else None

    def get_all(
        self,
        *,
        limit: Optional[int] = None,
        order_by: str = "created_at",
        descending: bool = True,
    ) -> List[Dict[str, Any]]:
        query = (
            self.client.table(self.table)
            .select("*")
            .order(order_by, desc=descending)
        )

        if limit:
            query = query.limit(limit)

        return query.execute().data or []

    def search(
        self,
        *,
        query: str = "",
        asset_type: Optional[str] = None,
        market: Optional[str] = None,
        decision: Optional[str] = None,
        participation_status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        request = self.client.table(self.table).select("*")

        if query.strip():
            clean = query.strip().replace(",", " ")
            request = request.or_(
                f"symbol.ilike.%{clean}%,"
                f"company_name.ilike.%{clean}%,"
                f"sector_theme.ilike.%{clean}%"
            )

        if asset_type:
            request = request.eq("asset_type", asset_type)

        if market:
            request = request.eq("market", market)

        if decision:
            request = request.eq("decision", decision)

        if participation_status:
            request = request.eq("participation_status", participation_status)

        return (
            request.order("nabi_score", desc=True)
            .execute()
            .data or []
        )

    def update(self, candidate_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        response = (
            self.client.table(self.table)
            .update(payload)
            .eq("id", candidate_id)
            .execute()
        )
        return response.data[0] if response.data else payload

    def delete(self, candidate_id: str) -> None:
        self.client.table(self.table).delete().eq("id", candidate_id).execute()

    def get_dashboard_stats(self) -> Dict[str, int]:
        rows = (
            self.client.table(self.table)
            .select("decision,research_status,participation_status")
            .execute()
            .data or []
        )

        return {
            "total": len(rows),
            "strong": sum(
                row.get("decision") == "GÜÇLÜ ADAY"
                for row in rows
            ),
            "watch": sum(
                row.get("decision") == "İZLE"
                for row in rows
            ),
            "researching": sum(
                row.get("research_status") == "İnceleniyor"
                for row in rows
            ),
            "participation_ok": sum(
                row.get("participation_status") == "Uygun"
                for row in rows
            ),
        }
