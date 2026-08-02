from datetime import datetime, timezone

class ScanRepository:
    def __init__(self, client):
        self.client = client

    def create_run(self, universe_name, total_symbols):
        response = self.client.table("scan_runs").insert({
            "universe_name": universe_name,
            "status": "RUNNING",
            "total_symbols": total_symbols,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
        return response.data[0]["id"]

    def add_result(self, scan_run_id, result):
        c = result["candidate"]
        self.client.table("scan_results").insert({
            "scan_run_id": scan_run_id,
            "symbol": result["symbol"],
            "status": result["status"],
            "nabi_score": c.get("nabi_score"),
            "decision": c.get("decision"),
            "data_completeness": c.get("data_completeness"),
            "endpoint_status": result["endpoint_status"],
            "errors": result["errors"],
        }).execute()

    def complete_run(self, scan_run_id, scanned, updated, strong, errors):
        self.client.table("scan_runs").update({
            "status": "COMPLETED",
            "scanned_symbols": scanned,
            "inserted_or_updated": updated,
            "strong_candidates": strong,
            "error_count": errors,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", scan_run_id).execute()
