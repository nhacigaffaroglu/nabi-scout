from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from services.scan_snapshot import (
    build_scan_snapshot,
    normalize_universe_name,
    sparse_snapshot_from_row,
)
from services.scan_universe_service import (
    MANUAL_UNIVERSE_NAME,
    SCHEDULED_UNIVERSE_PREFIX,
    is_manual_universe,
    scheduled_universe_name,
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

    def fail_run(
        self,
        scan_run_id: str,
        *,
        error_count: Optional[int] = None,
    ) -> None:
        payload: Dict[str, Any] = {
            "status": "FAILED",
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        if error_count is not None:
            payload["error_count"] = error_count
        self.client.table("scan_runs").update(payload).eq(
            "id", scan_run_id
        ).execute()

    def get_run_by_universe_name(self, universe_name: str) -> Optional[Dict[str, Any]]:
        response = (
            self.client.table("scan_runs")
            .select("*")
            .eq("universe_name", universe_name)
            .order("started_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else None

    def get_scheduled_run_for_date(
        self,
        run_date: Optional[date] = None,
    ) -> Optional[Dict[str, Any]]:
        return self.get_run_by_universe_name(scheduled_universe_name(run_date))

    def get_latest_scheduled_run(
        self,
        as_of: Optional[date] = None,
    ) -> Optional[Dict[str, Any]]:
        target = as_of or date.today()
        today_run = self.get_scheduled_run_for_date(target)
        if today_run:
            return today_run

        response = (
            self.client.table("scan_runs")
            .select("*")
            .order("started_at", desc=True)
            .limit(50)
            .execute()
        )
        for row in response.data or []:
            universe_name = str(row.get("universe_name") or "")
            if universe_name.startswith(SCHEDULED_UNIVERSE_PREFIX):
                return row
        return None

    def get_stale_running_runs(self, before: datetime) -> List[Dict[str, Any]]:
        response = (
            self.client.table("scan_runs")
            .select("*")
            .eq("status", "RUNNING")
            .lt("started_at", before.isoformat())
            .execute()
        )
        return response.data or []

    def mark_stale_running_failed(self, before: datetime) -> int:
        stale_runs = self.get_stale_running_runs(before)
        for run in stale_runs:
            run_id = run.get("id")
            if not run_id:
                continue
            self.fail_run(
                run_id,
                error_count=run.get("error_count") or 0,
            )
        return len(stale_runs)

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

            if logical_universe == MANUAL_UNIVERSE_NAME:
                return None

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

    def get_completed_runs_since(
        self,
        since: datetime,
        universe_name: Optional[str] = None,
        *,
        exclude_manual: bool = False,
    ) -> List[Dict[str, Any]]:
        query = (
            self.client.table("scan_runs")
            .select(
                "id, universe_name, status, completed_at, started_at, "
                "total_symbols, scanned_symbols"
            )
            .eq("status", "COMPLETED")
            .gte("completed_at", since.isoformat())
            .order("completed_at", desc=False)
        )
        response = query.execute()
        rows = response.data or []

        logical_universe = normalize_universe_name(universe_name)
        if not logical_universe:
            if exclude_manual:
                return [
                    row for row in rows
                    if not is_manual_universe(row.get("universe_name"))
                ]
            return rows

        filtered: List[Dict[str, Any]] = []
        for row in rows:
            row_universe = normalize_universe_name(row.get("universe_name"))
            if row_universe == logical_universe:
                filtered.append(row)
        return filtered

    def get_results_for_run(
        self,
        run_id: str,
        symbols: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        if not run_id:
            return []
        return self.get_results_for_runs([run_id], symbols=symbols)

    def get_results_for_runs(
        self,
        run_ids: List[str],
        symbols: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        if not run_ids:
            return []

        unique_run_ids = list(dict.fromkeys(run_ids))
        query = (
            self.client.table("scan_results")
            .select(f"{self._RESULT_COLUMNS_WITH_SNAPSHOT}, id")
            .in_("scan_run_id", unique_run_ids)
        )
        if symbols:
            unique_symbols = list({
                symbol.strip().upper()
                for symbol in symbols
                if symbol
            })
            if unique_symbols:
                query = query.in_("symbol", unique_symbols)

        try:
            response = query.order("created_at", desc=False).execute()
            self._snapshot_column_available = True
            rows = response.data or []
        except Exception as exc:
            if not _is_missing_column_error(exc, "candidate_snapshot"):
                raise

            self._snapshot_column_available = False
            fallback_query = (
                self.client.table("scan_results")
                .select(f"{self._RESULT_COLUMNS}, id")
                .in_("scan_run_id", unique_run_ids)
            )
            if symbols:
                unique_symbols = list({
                    symbol.strip().upper()
                    for symbol in symbols
                    if symbol
                })
                if unique_symbols:
                    fallback_query = fallback_query.in_("symbol", unique_symbols)
            response = fallback_query.order("created_at", desc=False).execute()
            rows = response.data or []

        return sorted(
            rows,
            key=lambda row: (
                row.get("created_at") or "",
                row.get("id") or "",
                row.get("scan_run_id") or "",
            ),
        )

    def get_symbols_with_results_before(
        self,
        symbols: List[str],
        before: datetime,
        run_ids: Optional[List[str]] = None,
    ) -> set[str]:
        if not symbols:
            return set()

        unique_symbols = list({
            symbol.strip().upper()
            for symbol in symbols
            if symbol
        })
        if not unique_symbols:
            return set()

        if run_ids is not None and len(run_ids) == 0:
            return set()

        query = (
            self.client.table("scan_results")
            .select("symbol, scan_run_id, created_at")
            .in_("symbol", unique_symbols)
            .lt("created_at", before.isoformat())
        )
        if run_ids is not None:
            query = query.in_("scan_run_id", list(dict.fromkeys(run_ids)))

        response = query.execute()
        return {
            str(row["symbol"]).strip().upper()
            for row in (response.data or [])
            if row.get("symbol")
        }

    def get_all_completed_run_ids_before(
        self,
        before: datetime,
        universe_name: Optional[str] = None,
        *,
        exclude_manual: bool = False,
    ) -> List[str]:
        query = (
            self.client.table("scan_runs")
            .select("id, universe_name, completed_at")
            .eq("status", "COMPLETED")
            .lt("completed_at", before.isoformat())
        )
        response = query.execute()
        rows = response.data or []
        logical_universe = normalize_universe_name(universe_name)
        if not logical_universe:
            if exclude_manual:
                return [
                    row["id"] for row in rows
                    if row.get("id")
                    and not is_manual_universe(row.get("universe_name"))
                ]
            return [row["id"] for row in rows if row.get("id")]

        run_ids: List[str] = []
        for row in rows:
            if normalize_universe_name(row.get("universe_name")) == logical_universe:
                run_ids.append(row["id"])
        return run_ids

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
