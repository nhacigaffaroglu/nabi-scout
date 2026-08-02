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
        # Aynı isimli evren yeniden oluşturulduğunda eski ve eksik
        # sembolleri kaldır. Böylece CIK=None olan eski satırlar kalmaz.
        self.client.table("universe_symbols").delete().eq(
            "universe_name",
            universe_name,
        ).execute()

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
                    "is_actively_trading",
                    True,
                ),
                "cik": row.get("cik"),
                "universe_source": row.get("universe_source"),
                "rank": rank,
                "is_selected": True,
                "discovered_at": row.get("discovered_at"),
                "updated_at": datetime.now(
                    timezone.utc
                ).isoformat(),
            })

        if payload:
            # Supabase/PostgREST için büyük payloadları küçük partilerle yaz.
            chunk_size = 250
            for index in range(0, len(payload), chunk_size):
                chunk = payload[index:index + chunk_size]
                self.client.table("universe_symbols").insert(
                    chunk
                ).execute()

    def complete_run(self, run_id, source, total, errors):
        self.client.table("universe_runs").update({
            "status": "COMPLETED",
            "source": source,
            "total_symbols": total,
            "errors": errors,
            "completed_at": datetime.now(
                timezone.utc
            ).isoformat(),
        }).eq("id", run_id).execute()

    def fail_run(self, run_id, errors):
        self.client.table("universe_runs").update({
            "status": "FAILED",
            "errors": errors,
            "completed_at": datetime.now(
                timezone.utc
            ).isoformat(),
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

    def get_universe_health(self, universe_name):
        rows = (
            self.client.table("universe_symbols")
            .select("symbol,cik,is_etf")
            .eq("universe_name", universe_name)
            .eq("is_selected", True)
            .execute()
            .data or []
        )

        stocks = [
            row for row in rows
            if not row.get("is_etf", False)
        ]
        with_cik = [
            row for row in stocks
            if row.get("cik") is not None
        ]

        return {
            "total": len(rows),
            "stocks": len(stocks),
            "with_cik": len(with_cik),
            "without_cik": len(stocks) - len(with_cik),
            "cik_coverage": (
                round(len(with_cik) / len(stocks) * 100, 1)
                if stocks else 0.0
            ),
        }
