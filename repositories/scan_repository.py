from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.scan_snapshot import (
    build_scan_snapshot,
    normalize_universe_name,
    sparse_snapshot_from_row,
)


def _is_missing_column_error(exc: Exception, column: str) -> bool:
    message = str(exc).lower()
    return column.lower() in message and (
        "column" in message
        or "schema cache" in message
        or "pgrst" in message
        or "could not find" in message
    )


class ScanRepository:
    _RESULT_COLUMNS = (
        "id, scan_run_id, symbol, status, nabi_score, decision, "
        "data_completeness, endpoint_status, errors, created_at"
    )
    _RESULT_COLUMNS_WITH_SNAPSHOT = (
        f"{_RESULT_COLUMNS}, candidate_snapshot"
    )

    def __init__(self, client):
        self.client = client
        self._snapshot_column_available: Optional[bool] = None

    def create_run(self, universe_name, total_symbols):
        response = self.client.table("scan_runs").insert({
            "universe_name": universe_name,
            "status": "RUNNING",
            "total_symbols": total_symbols,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
        return response.data[0]["id"]

    def add_result(self, scan_run_id, result):
        candidate = result["candidate"]
        payload = {
            "scan_run_id": scan_run_id,
            "symbol": result["symbol"],
            "status": result["status"],
            "nabi_score": candidate.get("nabi_score"),
            "decision": candidate.get("decision"),
            "data_completeness": candidate.get("data_completeness"),
            "endpoint_status": result["endpoint_status"],
            "errors": result["errors"],
        }
        snapshot = build_scan_snapshot(result)

        if self._snapshot_column_available is not False:
            try:
                insert_payload = {
                    **payload,
                    "candidate_snapshot": snapshot,
                }
                self.client.table("scan_results").insert(
                    insert_payload
                ).execute()
                self._snapshot_column_available = True
                return
            except Exception as exc:
                if _is_missing_column_error(exc, "candidate_snapshot"):
                    self._snapshot_column_available = False
                else:
                    raise

        self.client.table("scan_results").insert(payload).execute()

    def complete_run(self, scan_run_id, scanned, updated, strong, errors):
        self.client.table("scan_runs").update({
            "status": "COMPLETED",
            "scanned_symbols": scanned,
            "inserted_or_updated": updated,
            "strong_candidates": strong,
            "error_count": errors,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", scan_run_id).execute()

    def get_previous_snapshot(
        self,
        symbol: str,
        current_run_id: str,
        universe_name: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        rows = self._fetch_previous_rows(symbol, current_run_id)
        if not rows:
            return None

        logical_universe = normalize_universe_name(universe_name)
        if logical_universe:
            for row in rows:
                run = row.get("scan_runs") or {}
                previous_universe = normalize_universe_name(
                    run.get("universe_name"),
                )
                if previous_universe == logical_universe:
                    return self._row_to_snapshot(row)

        return self._row_to_snapshot(rows[0])

    def _fetch_previous_rows(
        self,
        symbol: str,
        current_run_id: str,
    ) -> List[Dict[str, Any]]:
        base_query = (
            self.client.table("scan_results")
            .select(
                f"{self._RESULT_COLUMNS_WITH_SNAPSHOT}, "
                "scan_runs!inner(status, universe_name, completed_at)"
            )
            .eq("symbol", symbol)
            .neq("scan_run_id", current_run_id)
            .eq("scan_runs.status", "COMPLETED")
            .order("created_at", desc=True)
            .limit(20)
        )

        try:
            response = base_query.execute()
            self._snapshot_column_available = True
            return response.data or []
        except Exception as exc:
            if not _is_missing_column_error(exc, "candidate_snapshot"):
                raise

            self._snapshot_column_available = False
            fallback_query = (
                self.client.table("scan_results")
                .select(
                    f"{self._RESULT_COLUMNS}, "
                    "scan_runs!inner(status, universe_name, completed_at)"
                )
                .eq("symbol", symbol)
                .neq("scan_run_id", current_run_id)
                .eq("scan_runs.status", "COMPLETED")
                .order("created_at", desc=True)
                .limit(20)
            )
            response = fallback_query.execute()
            return response.data or []

    def get_latest_scan_row(self, symbol: str) -> Optional[Dict[str, Any]]:
        rows = self.get_latest_scan_rows_for_symbols([symbol])
        return rows.get(symbol.strip().upper())

    def get_latest_scan_rows_for_symbols(
        self,
        symbols: List[str],
    ) -> Dict[str, Dict[str, Any]]:
        if not symbols:
            return {}

        unique_symbols = list({
            symbol.strip().upper()
            for symbol in symbols
            if symbol
        })
        if not unique_symbols:
            return {}

        limit = max(len(unique_symbols) * 3, 20)
        rows = self._fetch_latest_result_rows(unique_symbols, limit)
        latest: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            symbol = row.get("symbol")
            if symbol and symbol not in latest:
                latest[symbol] = row
        return latest

    def _fetch_latest_result_rows(
        self,
        symbols: List[str],
        limit: int,
    ) -> List[Dict[str, Any]]:
        base_query = (
            self.client.table("scan_results")
            .select(f"{self._RESULT_COLUMNS_WITH_SNAPSHOT}, symbol")
            .in_("symbol", symbols)
            .order("created_at", desc=True)
            .limit(limit)
        )
        try:
            response = base_query.execute()
            self._snapshot_column_available = True
            return response.data or []
        except Exception as exc:
            if not _is_missing_column_error(exc, "candidate_snapshot"):
                raise

            self._snapshot_column_available = False
            fallback_query = (
                self.client.table("scan_results")
                .select(f"{self._RESULT_COLUMNS}, symbol")
                .in_("symbol", symbols)
                .order("created_at", desc=True)
                .limit(limit)
            )
            response = fallback_query.execute()
            return response.data or []

    def row_to_snapshot(self, row: Dict[str, Any]) -> Dict[str, Any]:
        return self._row_to_snapshot(row)

    @staticmethod
    def _row_to_snapshot(row: Dict[str, Any]) -> Dict[str, Any]:
        snapshot = row.get("candidate_snapshot")
        if isinstance(snapshot, dict) and snapshot:
            normalized = dict(snapshot)
            normalized.setdefault("_comparison_source", "snapshot")
            return normalized
        return sparse_snapshot_from_row(row)
