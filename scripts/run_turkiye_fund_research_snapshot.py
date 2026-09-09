#!/usr/bin/env python3
"""FUND-14A rolling official Turkish fund research snapshot.

Research/cache/artifact only. It has no production persistence or execution
authority. Live network access is explicit through --live.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

COMPATIBLE_DEPENDENCY_BLOBS = {
    "services/turkiye_fund_source_capture.py": "6d02e7e874a52fcbcf906287541b3b810647742c",
    "services/turkiye_fund_broad_capture.py": "2833ed61f276a9ee3f29881b0f2080e1e4ee5e31",
    "services/turkiye_fund_scanner.py": "9767ae44527d4ae34263f5efe1863709f2707bc4",
    "services/turkiye_fund_universe_discovery.py": "5c1f884d326433df2cc0140caa4f01b4a00c173e",
    "services/turkiye_fund_universe_contract.py": "18306f6cfdbdb0b36a673be569f528bdd26a9a9e",
    "services/turkiye_fund_tefas_history.py": "f4b8c67c6c369b79aebc25ac614c718b6dfb3a34",
}
DEFAULT_TEFAS_DISCOVERY_SHARDS = 10
DEFAULT_CAPTURE_SHARDS = 5
DEFAULT_KAP_LOOKBACK_DAYS = 45
DEFAULT_CACHE_ROOT = Path(".cache/turkiye_fund_universe")
DEFAULT_CATALOG_OVERLAY = DEFAULT_CACHE_ROOT / "research_catalog_overlay_v1.json"
DEFAULT_TEFAS_OVERLAY = DEFAULT_CACHE_ROOT / "research_tefas_activity_v1.json"
DEFAULT_OUTPUT = Path(".cache/turkiye_fund_research_snapshot/last_result.json")
DEFAULT_RUN_STATE = DEFAULT_CACHE_ROOT / "research_run_state_v1.json"

APPROVED_UYGUN_BASELINE = {
    "AIS", "BCO", "BDA", "BKY", "GKV", "IAT", "KCL",
    "VRK",
    "KTN", "RCV", "TLZ", "YCY", "YSL", "ZPE",
}


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def assert_runtime_compatibility() -> str:
    """Allow add-only commits, but fail closed if stable dependencies changed."""
    mismatches: list[str] = []
    for path, expected in COMPATIBLE_DEPENDENCY_BLOBS.items():
        actual = _git("hash-object", path)
        if actual != expected:
            mismatches.append(f"{path}:{actual}")
    if mismatches:
        raise SystemExit(
            "FUND14A incompatible stable dependency blob(s): " + ", ".join(mismatches)
        )
    return _git("rev-parse", "HEAD")


def _day(value: str) -> date:
    return date.fromisoformat(str(value).strip())


def business_day_index(day: date, *, epoch: date = date(2026, 1, 5)) -> int:
    """Mon-Fri index; Saturday/Sunday do not consume shard positions."""
    delta = (day - epoch).days
    if delta < 0:
        raise ValueError("fund14a_date_before_epoch")
    weeks, remainder = divmod(delta, 7)
    return weeks * 5 + min(remainder, 5)


def shard_index_for_day(day: date, shard_count: int) -> int:
    if shard_count <= 0:
        raise ValueError("fund14a_shard_count_must_be_positive")
    return business_day_index(day) % shard_count


def select_shard(
    codes: Iterable[str], *, shard_count: int, shard_index: int
) -> tuple[str, ...]:
    if shard_count <= 0:
        raise ValueError("fund14a_shard_count_must_be_positive")
    if shard_index < 0 or shard_index >= shard_count:
        raise ValueError("fund14a_shard_index_out_of_range")
    ordered = sorted({str(code).strip().upper() for code in codes if str(code).strip()})
    return tuple(
        code for idx, code in enumerate(ordered)
        if idx % shard_count == shard_index
    )


def kap_windows(day: date, lookback_days: int) -> tuple[tuple[str, str], ...]:
    """KAP uses ISO YYYY-MM-DD; split lookback at year boundaries."""
    if lookback_days <= 0:
        raise ValueError("fund14a_kap_lookback_days_must_be_positive")
    start = day - timedelta(days=lookback_days - 1)
    windows: list[tuple[str, str]] = []
    cursor = start
    while cursor.year < day.year:
        year_end = date(cursor.year, 12, 31)
        windows.append((cursor.isoformat(), year_end.isoformat()))
        cursor = date(cursor.year + 1, 1, 1)
    windows.append((cursor.isoformat(), day.isoformat()))
    return tuple(windows)


def _row_identity(row: Mapping[str, Any]) -> tuple:
    index = int(row.get("disclosureIndex") or 0)
    if index:
        return ("index", index)
    return (
        "fallback",
        str(row.get("fundCode") or "").strip().upper(),
        int(row.get("year") or 0),
        int(row.get("period") or 0),
        str(row.get("publishDate") or ""),
    )


def _row_sort_key(row: Mapping[str, Any]) -> tuple:
    return (
        str(row.get("fundCode") or "").strip().upper(),
        int(row.get("year") or 0),
        int(row.get("period") or 0),
        int(row.get("disclosureIndex") or 0),
        str(row.get("publishDate") or ""),
    )


def merge_catalog_rows(
    *groups: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Deterministic disclosure-index merge; later duplicate payload wins."""
    merged: dict[tuple, dict[str, Any]] = {}
    for group in groups:
        for raw in group:
            row = dict(raw)
            merged[_row_identity(row)] = row
    return sorted(merged.values(), key=_row_sort_key)


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def load_catalog_overlay(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != "fund14a_catalog_overlay_1":
        raise ValueError("fund14a_catalog_overlay_schema_invalid")
    return [dict(row) for row in data.get("rows") or []]


def save_catalog_overlay(
    path: Path,
    rows: Sequence[Mapping[str, Any]],
    *,
    observed_at: str,
) -> None:
    _atomic_json(
        path,
        {
            "schema_version": "fund14a_catalog_overlay_1",
            "observed_at": observed_at,
            "rows": [dict(row) for row in rows],
        },
    )


def load_tefas_overlay(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != "fund14a_tefas_overlay_1":
        raise ValueError("fund14a_tefas_overlay_schema_invalid")
    return {
        str(code).strip().upper(): dict(item)
        for code, item in dict(data.get("funds") or {}).items()
    }


def effective_tefas_snapshots(
    static_snapshots: Mapping[str, Mapping[str, Any]],
    overlay: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    out = {
        str(code).strip().upper(): dict(row)
        for code, row in static_snapshots.items()
        if str(code).strip()
    }
    for code, item in overlay.items():
        snapshot = dict(item.get("snapshot") or {})
        if snapshot:
            out[str(code).strip().upper()] = snapshot
    return out


def update_tefas_overlay(
    overlay: Mapping[str, Mapping[str, Any]],
    fresh: Mapping[str, Mapping[str, Any]],
    *,
    observed_at: str,
) -> dict[str, dict[str, Any]]:
    out = {
        str(code).strip().upper(): dict(item)
        for code, item in overlay.items()
    }
    for code, snapshot in fresh.items():
        key = str(code).strip().upper()
        out[key] = {
            "observed_at": observed_at,
            "snapshot": dict(snapshot),
        }
    return out


def save_tefas_overlay(
    path: Path,
    overlay: Mapping[str, Mapping[str, Any]],
) -> None:
    _atomic_json(
        path,
        {
            "schema_version": "fund14a_tefas_overlay_1",
            "funds": {
                code: dict(item)
                for code, item in sorted(overlay.items())
            },
        },
    )


def filter_current_packs(
    packs: Mapping[str, Mapping[str, Any]],
    identities: Sequence[Any],
) -> tuple[dict[str, dict[str, Any]], tuple[str, ...]]:
    """Quarantine a stale pack when current KAP disclosure identity has advanced."""
    by_code = {row.fund_code: row for row in identities}
    current: dict[str, dict[str, Any]] = {}
    quarantined: list[str] = []
    for code, raw in packs.items():
        pack = dict(raw)
        identity = by_code.get(code)
        if identity is None:
            continue
        if pack.get("pilot_frozen"):
            current[code] = pack
            continue
        expected = int(identity.kap_disclosure_index or 0)
        actual = int(pack.get("kap_disclosure_index") or 0)
        if expected and actual != expected:
            quarantined.append(code)
            continue
        current[code] = pack
    return current, tuple(sorted(quarantined))


def _fresh_tefas_snapshot(
    session: Any,
    endpoint: str,
    code: str,
) -> dict[str, Any]:
    data = session.http_json(
        endpoint,
        {"fonKodu": code},
        referer="https://www.tefas.gov.tr/",
    )
    rows = list(data.get("resultList") or [])
    if not rows:
        return {"fonKodu": code, "tefas_present": False}
    return {**dict(rows[0]), "tefas_present": True}


def _fetch_live_kap_rows(
    session: Any,
    *,
    endpoint: str,
    subject_oid: str,
    windows: Sequence[tuple[str, str]],
) -> list[dict[str, Any]]:
    session.ensure_kap_session()
    rows: list[dict[str, Any]] = []
    for from_date, to_date in windows:
        data = session.http_json(
            endpoint,
            {
                "fromDate": from_date,
                "toDate": to_date,
                "subjectList": [subject_oid],
            },
            referer="https://www.kap.org.tr/tr/bildirim-sorgu",
        )
        rows.extend(dict(row) for row in list(data or []))
    return rows



def tefas_discovery_refresh_codes(
    all_kap_codes: Iterable[str],
    new_live_codes: Iterable[str],
    *,
    shard_count: int,
    shard_index: int,
    excluded_codes: Iterable[str] = (),
) -> tuple[str, ...]:
    excluded = {
        str(code).strip().upper()
        for code in excluded_codes
        if str(code).strip()
    }
    selected = set(
        select_shard(
            all_kap_codes,
            shard_count=shard_count,
            shard_index=shard_index,
        )
    )
    selected.update(
        str(code).strip().upper()
        for code in new_live_codes
        if str(code).strip()
    )
    return tuple(sorted(code for code in selected if code not in excluded))


def update_pack_with_tefas_refresh(
    pack: Mapping[str, Any],
    *,
    snapshot: Mapping[str, Any] | None,
    history: Mapping[str, Any] | None,
    observed_at: str,
) -> dict[str, Any]:
    out = dict(pack)
    if out.get("pilot_frozen"):
        return out

    reasons = list(out.get("review_reasons") or ())
    previous_refresh = dict(out.get("tefas_refresh") or {})
    snapshot_ok = bool(snapshot)
    history_rows = list((history or {}).get("rows") or ())
    history_ok = bool((history or {}).get("available") and history_rows)

    if snapshot_ok:
        out["tefas_snapshot"] = dict(snapshot or {})
        # Clear SOURCE_STALE only when a previous FUND14A TEFAS refresh is
        # explicitly known to have introduced it. An unrelated/KAP stale
        # marker is preserved fail-closed.
        if previous_refresh.get("snapshot_ok") is False:
            reasons = [r for r in reasons if r != "SOURCE_STALE"]
        if bool((snapshot or {}).get("tefas_present")):
            reasons = [r for r in reasons if r != "TEFAS_INACTIVE"]
        else:
            reasons.append("TEFAS_INACTIVE")
    else:
        reasons.append("SOURCE_STALE")

    if history_ok:
        out["tefas_price_rows"] = history_rows
        out["tefas_prices"] = {
            "available": True,
            "error": None,
            "row_count": int((history or {}).get("row_count") or len(history_rows)),
            "periyod": (history or {}).get("periyod"),
            "latest_date": (history or {}).get("latest_date"),
            "pilot_frozen": bool((history or {}).get("pilot_frozen")),
        }
        reasons = [r for r in reasons if r != "HISTORY_INSUFFICIENT"]
    else:
        reasons.append("HISTORY_INSUFFICIENT")

    out["review_reasons"] = list(dict.fromkeys(reasons))
    out["tefas_refresh"] = {
        "observed_at": observed_at,
        "snapshot_ok": snapshot_ok,
        "history_ok": history_ok,
        "latest_date": (history or {}).get("latest_date"),
    }
    return out


def _status_counts(result: Any) -> dict[str, int]:
    return {
        "discovered": int(result.discovered_count),
        "active": int(result.active_count),
        "ready": int(result.scanner_ready_count),
        "review_required": int(result.review_required_count),
        "blocked": int(result.blocked_count),
        "participation_uygun": int(result.participation_uygun_count),
        "kontrol_et": int(result.kontrol_et_count),
        "uygun_degil": int(result.uygun_degil_count),
        "fi_ready": int(result.fi_ready_count),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--as-of", default=date.today().isoformat())
    parser.add_argument(
        "--tefas-discovery-shards",
        type=int,
        default=DEFAULT_TEFAS_DISCOVERY_SHARDS,
    )
    parser.add_argument("--tefas-discovery-shard-index", type=int)
    parser.add_argument(
        "--capture-shards",
        type=int,
        default=DEFAULT_CAPTURE_SHARDS,
    )
    parser.add_argument("--capture-shard-index", type=int)
    parser.add_argument("--kap-lookback-days", type=int, default=DEFAULT_KAP_LOOKBACK_DAYS)
    parser.add_argument("--catalog-overlay", default=str(DEFAULT_CATALOG_OVERLAY))
    parser.add_argument("--tefas-overlay", default=str(DEFAULT_TEFAS_OVERLAY))
    parser.add_argument("--run-state", default=str(DEFAULT_RUN_STATE))
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    if not args.live:
        raise SystemExit("FUND14A live research capture requires explicit --live")

    from services.fund_product_contract import PDR_SUBJECT_OID, PILOT_TEFAS_FUND_CODES
    from services.turkiye_fund_broad_capture import capture_universe
    from services.turkiye_fund_tefas_history import capture_tefas_history
    from services.turkiye_fund_scanner import run_turkiye_fund_scanner
    from services.turkiye_fund_source_capture import (
        KAP_MIN_GAP_SEC,
        KAP_PDR_URL,
        TEFAS_SNAPSHOT_URL,
        OfficialCaptureSession,
        load_cached_evidence_packs,
        load_captured_kap_pdr_catalog,
        load_captured_tefas_snapshots,
        read_evidence_pack,
        write_evidence_pack,
    )
    from services.turkiye_fund_universe_contract import TEFAS_STATUS_ACTIVE
    from services.turkiye_fund_universe_discovery import (
        discover_turkiye_participation_universe,
    )

    source_head = assert_runtime_compatibility()
    day = _day(args.as_of)
    observed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    tefas_shard_index = (
        args.tefas_discovery_shard_index
        if args.tefas_discovery_shard_index is not None
        else shard_index_for_day(day, args.tefas_discovery_shards)
    )
    capture_shard_index = (
        args.capture_shard_index
        if args.capture_shard_index is not None
        else shard_index_for_day(day, args.capture_shards)
    )
    if (
        tefas_shard_index < 0
        or tefas_shard_index >= args.tefas_discovery_shards
    ):
        raise SystemExit("FUND14A TEFAS discovery shard index out of range")
    if (
        capture_shard_index < 0
        or capture_shard_index >= args.capture_shards
    ):
        raise SystemExit("FUND14A capture shard index out of range")

    catalog_overlay_path = Path(args.catalog_overlay)
    tefas_overlay_path = Path(args.tefas_overlay)
    run_state_path = Path(args.run_state)
    output_path = Path(args.out)

    static_rows = [
        dict(row)
        for row in list(load_captured_kap_pdr_catalog().get("rows") or [])
    ]
    old_overlay_rows = load_catalog_overlay(catalog_overlay_path)

    kap_discovery_session = OfficialCaptureSession(
        live=True,
        min_gap_sec=KAP_MIN_GAP_SEC,
    )
    windows = kap_windows(day, args.kap_lookback_days)
    live_rows = _fetch_live_kap_rows(
        kap_discovery_session,
        endpoint=KAP_PDR_URL,
        subject_oid=PDR_SUBJECT_OID,
        windows=windows,
    )
    overlay_rows = merge_catalog_rows(old_overlay_rows, live_rows)
    merged_rows = merge_catalog_rows(static_rows, overlay_rows)
    save_catalog_overlay(
        catalog_overlay_path,
        overlay_rows,
        observed_at=observed_at,
    )

    static_snapshots = load_captured_tefas_snapshots()
    old_tefas_overlay = load_tefas_overlay(tefas_overlay_path)

    known_codes_before_live = {
        str(row.get("fundCode") or "").strip().upper()
        for row in merge_catalog_rows(static_rows, old_overlay_rows)
        if str(row.get("fundCode") or "").strip()
    }
    live_codes = {
        str(row.get("fundCode") or "").strip().upper()
        for row in live_rows
        if str(row.get("fundCode") or "").strip()
    }
    new_live_codes = tuple(sorted(live_codes - known_codes_before_live))
    all_kap_codes = tuple(sorted({
        str(row.get("fundCode") or "").strip().upper()
        for row in merged_rows
        if str(row.get("fundCode") or "").strip()
    }))

    tefas_discovery_codes = set(
        tefas_discovery_refresh_codes(
            all_kap_codes,
            new_live_codes,
            shard_count=args.tefas_discovery_shards,
            shard_index=tefas_shard_index,
            excluded_codes=PILOT_TEFAS_FUND_CODES,
        )
    )

    tefas_session = OfficialCaptureSession(live=True)
    fresh_tefas: dict[str, dict[str, Any]] = {}
    tefas_errors: dict[str, str] = {}

    def refresh_snapshot(code: str) -> None:
        if code in PILOT_TEFAS_FUND_CODES:
            return
        if code in fresh_tefas or code in tefas_errors:
            return
        try:
            fresh_tefas[code] = _fresh_tefas_snapshot(
                tefas_session,
                TEFAS_SNAPSHOT_URL,
                code,
            )
        except Exception as exc:
            tefas_errors[code] = str(exc)[:240]

    for code in sorted(tefas_discovery_codes):
        refresh_snapshot(code)

    new_tefas_overlay = update_tefas_overlay(
        old_tefas_overlay,
        fresh_tefas,
        observed_at=observed_at,
    )
    snapshots = effective_tefas_snapshots(
        static_snapshots,
        new_tefas_overlay,
    )

    identities = discover_turkiye_participation_universe(
        merged_rows,
        tefas_snapshots=snapshots,
    )
    active_codes = tuple(
        row.fund_code
        for row in identities
        if row.tefas_status == TEFAS_STATUS_ACTIVE
    )
    broad_shard = select_shard(
        active_codes,
        shard_count=args.capture_shards,
        shard_index=capture_shard_index,
    )

    # Every non-pilot broad-capture fund gets a same-run TEFAS snapshot refresh,
    # independent of the slower all-KAP discovery sweep.
    for code in broad_shard:
        refresh_snapshot(code)

    new_tefas_overlay = update_tefas_overlay(
        old_tefas_overlay,
        fresh_tefas,
        observed_at=observed_at,
    )
    save_tefas_overlay(tefas_overlay_path, new_tefas_overlay)
    snapshots = effective_tefas_snapshots(
        static_snapshots,
        new_tefas_overlay,
    )

    # Re-discover after the final TEFAS overlay update so a newly identified
    # Katılım category can enter the same run.
    identities = discover_turkiye_participation_universe(
        merged_rows,
        tefas_snapshots=snapshots,
    )
    active_codes = tuple(
        row.fund_code
        for row in identities
        if row.tefas_status == TEFAS_STATUS_ACTIVE
    )
    broad_shard = select_shard(
        active_codes,
        shard_count=args.capture_shards,
        shard_index=capture_shard_index,
    )

    kap_capture_session = OfficialCaptureSession(
        live=True,
        min_gap_sec=KAP_MIN_GAP_SEC,
    )
    captured, capture_stats = capture_universe(
        identities,
        catalog_rows=merged_rows,
        live=True,
        as_of=day,
        session=kap_capture_session,
        resume=True,
        only_fund_codes=broad_shard,
        fetch_prices=True,
        allow_ocr=True,
    )

    tefas_history_errors: dict[str, str] = {}
    refreshed_pack_codes: list[str] = []
    for code in broad_shard:
        if code in PILOT_TEFAS_FUND_CODES:
            continue
        pack = dict(captured.get(code) or read_evidence_pack(code) or {})
        if not pack:
            continue
        history = None
        try:
            history = capture_tefas_history(
                tefas_session,
                code,
                as_of=day,
            )
        except Exception as exc:
            tefas_history_errors[code] = str(exc)[:240]
        updated_pack = update_pack_with_tefas_refresh(
            pack,
            snapshot=fresh_tefas.get(code),
            history=history,
            observed_at=observed_at,
        )
        write_evidence_pack(code, updated_pack)
        captured[code] = updated_pack
        refreshed_pack_codes.append(code)

    packs = load_cached_evidence_packs()
    packs.update(captured)
    current_packs, quarantined = filter_current_packs(packs, identities)

    result = run_turkiye_fund_scanner(
        catalog_rows=merged_rows,
        tefas_snapshots=snapshots,
        as_of=day,
        persist=False,
        sample_only=False,
        evidence_packs=current_packs,
    )

    if result.persist or result.production_writes:
        raise SystemExit("FUND14A scanner write firewall violated")
    if any((
        result.eight_e_calls,
        result.new_money_calls,
        result.trades,
        result.portfolio_writes,
    )):
        raise SystemExit("FUND14A execution authority firewall violated")

    uygun = sorted(
        row.fund_code
        for row in result.rows
        if row.participation == "Uygun"
    )
    uygun_added = sorted(set(uygun) - APPROVED_UYGUN_BASELINE)
    uygun_removed = sorted(APPROVED_UYGUN_BASELINE - set(uygun))

    tefas_never_refreshed = sorted(
        code for code in all_kap_codes
        if code not in new_tefas_overlay
        and code not in PILOT_TEFAS_FUND_CODES
    )
    ready_codes = {
        row.fund_code
        for row in result.rows
        if row.scanner_status == "READY"
    }
    refresh_error_codes = set(tefas_errors) | set(tefas_history_errors)
    ready_refresh_error_codes = sorted(ready_codes & refresh_error_codes)
    activation_safe = not (
        uygun_added
        or uygun_removed
        or ready_refresh_error_codes
    )

    artifact = {
        "schema_version": "fund14a_research_snapshot_3",
        "source_head": source_head,
        "as_of": day.isoformat(),
        "calculated_at": observed_at,
        "research_only": True,
        "thresholds_proposed": False,
        "thresholds_locked": False,
        "discovery": {
            "kap_windows": [list(item) for item in windows],
            "static_catalog_rows": len(static_rows),
            "previous_overlay_rows": len(old_overlay_rows),
            "live_window_rows": len(live_rows),
            "overlay_rows": len(overlay_rows),
            "merged_catalog_rows": len(merged_rows),
        },
        "rolling_refresh": {
            "tefas_discovery_shards": args.tefas_discovery_shards,
            "tefas_discovery_shard_index": tefas_shard_index,
            "capture_shards": args.capture_shards,
            "capture_shard_index": capture_shard_index,
            "all_kap_codes": len(all_kap_codes),
            "new_live_kap_codes": list(new_live_codes),
            "tefas_discovery_codes_attempted": sorted(tefas_discovery_codes),
            "tefas_fresh_ok": sorted(fresh_tefas),
            "tefas_errors": tefas_errors,
            "tefas_never_refreshed_in_overlay": tefas_never_refreshed,
            "broad_capture_codes": list(broad_shard),
            "broad_capture_returned": sorted(captured),
            "tefas_pack_refreshed": sorted(refreshed_pack_codes),
            "tefas_history_errors": tefas_history_errors,
            "ready_refresh_error_codes": ready_refresh_error_codes,
            "stale_packs_quarantined": list(quarantined),
            "capture_stats": capture_stats.to_dict(),
        },
        "scanner_counts": _status_counts(result),
        "participation_uygun_set": uygun,
        "participation_baseline_delta": {
            "baseline_count": len(APPROVED_UYGUN_BASELINE),
            "current_count": len(uygun),
            "added": uygun_added,
            "removed": uygun_removed,
            "manual_review_required": bool(uygun_added or uygun_removed),
        },
        "activation_safe": activation_safe,
        "write_proof": {
            "persist": result.persist,
            "production_writes": list(result.production_writes),
            "eight_e_calls": result.eight_e_calls,
            "new_money_calls": result.new_money_calls,
            "trades": result.trades,
            "portfolio_writes": result.portfolio_writes,
        },
        "scanner": result.to_dict(),
    }
    _atomic_json(output_path, artifact)

    run_state = {
        "schema_version": "fund14a_research_run_state_1",
        "source_head": source_head,
        "as_of": day.isoformat(),
        "observed_at": observed_at,
        "activation_safe": activation_safe,
        "participation_baseline_delta": artifact["participation_baseline_delta"],
        "ready_codes": sorted(ready_codes),
        "ready_refresh_error_codes": ready_refresh_error_codes,
        "tefas_errors": tefas_errors,
        "tefas_history_errors": tefas_history_errors,
        "stale_packs_quarantined": list(quarantined),
        "write_proof": artifact["write_proof"],
    }
    _atomic_json(run_state_path, run_state)

    print("=== FUND-14A RESEARCH SNAPSHOT ===")
    print("source_head:", source_head)
    print("as_of:", day.isoformat())
    print("kap_windows:", artifact["discovery"]["kap_windows"])
    print("merged_catalog_rows:", len(merged_rows))
    print(
        "tefas_discovery_shard:",
        f"{tefas_shard_index}/{args.tefas_discovery_shards}",
    )
    print(
        "capture_shard:",
        f"{capture_shard_index}/{args.capture_shards}",
    )
    print("all_kap_codes:", len(all_kap_codes))
    print("new_live_kap_codes:", len(new_live_codes))
    print("tefas_discovery_attempted:", len(tefas_discovery_codes))
    print("tefas_errors:", len(tefas_errors))
    print("broad_capture_codes:", len(broad_shard))
    print("tefas_history_errors:", len(tefas_history_errors))
    print("ready_refresh_error_codes:", ready_refresh_error_codes)
    print("stale_packs_quarantined:", len(quarantined))
    print("scanner_counts:", artifact["scanner_counts"])
    print("uygun_delta:", artifact["participation_baseline_delta"])
    print("activation_safe:", activation_safe)
    print("write_proof:", artifact["write_proof"])
    print("run_state:", run_state_path)
    print("output:", output_path)
    print("PASS: research snapshot produced; no execution authority.")
    if uygun_added or uygun_removed:
        print(
            "NOTICE: Participation baseline changed; human review is required "
            "before downstream Candidate automation."
        )


if __name__ == "__main__":
    main()
