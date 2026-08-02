from datetime import datetime, timezone


class UniverseRepository:
    def __init__(self, client):
        self.client = client

    def create_run(self, name, filters):
        response = self.client.table("universe_runs").insert({
            "name": name,
            "status": "RUNNING",
            "filters": filters,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
        return response.data[0]["id"]

    def save_symbols(self, run_id, universe_name, rows):
        payload = []
        for rank, row in enumerate(rows, start=1):
            payload.append({
                "universe_run_id": run_id,
                "universe_name": universe_name,
                "symbol": row["symbol"],
                "company_name": row.get("company_name"),
                "exchange": row.get("exchange"),
                "country": row.get("country"),
                "sector": row.get("sector"),
                "industry": row.get("industry"),
                "market_cap": row.get("market_cap"),
                "price": row.get("price"),
                "volume": row.get("volume"),
                "beta": row.get("beta"),
                "is_etf": row.get("is_etf", False),
                "is_actively_trading": row.get(
                    "is_actively_trading", True
                ),
                "universe_source": row.get("universe_source"),
                "rank": rank,
                "is_selected": True,
                "discovered_at": row.get("discovered_at"),
            })

        if payload:
            self.client.table("universe_symbols").upsert(
                payload,
                on_conflict="universe_name,symbol",
            ).execute()

    def complete_run(self, run_id, source, total, errors):
        self.client.table("universe_runs").update({
            "status": "COMPLETED",
            "source": source,
            "total_symbols": total,
            "errors": errors,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", run_id).execute()

    def get_symbols(self, universe_name, limit=100):
        response = (
            self.client.table("universe_symbols")
            .select("*")
            .eq("universe_name", universe_name)
            .eq("is_selected", True)
            .order("rank")
            .limit(limit)
            .execute()
        )
        return response.data or []

    def get_universe_names(self):
        response = (
            self.client.table("universe_symbols")
            .select("universe_name")
            .execute()
        )
        names = {
            row["universe_name"]
            for row in (response.data or [])
            if row.get("universe_name")
        }
        return sorted(names)

    def get_recent_runs(self, limit=10):
        response = (
            self.client.table("universe_runs")
            .select("*")
            .order("started_at", desc=True)
            .limit(limit)
            .execute()
        )
        return response.data or []
