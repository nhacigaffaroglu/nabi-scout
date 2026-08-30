#!/usr/bin/env python3
"""BIST change-driven Facts → SI → Participation refresh.

Default is dry-run with zero writes. Production writes require explicit
--live plus --persist-si and/or --persist-participation.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from repositories.participation_assessment_repository import (
    ParticipationAssessmentRepository,
)
from repositories.security_intelligence_snapshot_repository import (
    SecurityIntelligenceSnapshotRepository,
)
from services.bist_katilim_tum_source import BistKatilimTumSource
from services.bist_refresh_contract import (
    JOB_NAME,
    MAX_SYMBOLS_DEFAULT,
    PILOT_SYMBOLS,
    REASON_LIVE_UNSAFE,
    REASON_PILOT_SCOPE,
    STATE_CACHE_PATH,
    BistRefreshState,
)
from services.bist_refresh_orchestrator import _membership_key, run_bist_refresh
from services.bist_thb_history import load_history_cache
from services.kap_kafif_source import KapKafifSource
from services.wealth_contract import normalize_symbol


ALLOWED_WRITE_TABLES = {
    "participation_assessment_snapshots": frozenset({"insert"}),
    "security_intelligence_snapshots": frozenset({"upsert", "insert"}),
}
_WRITE_METHODS = frozenset({"insert", "update", "upsert", "delete"})


class IntelligenceWriteGuard:
    """Allow only Participation insert and SI upsert. Block portfolio writes."""

    def __init__(self, client: Any) -> None:
        self._client = client
        self.blocked: list[str] = []

    def table(self, name: str):
        return _GuardedTable(self, self._client.table(name), name)

    def __getattr__(self, name: str):
        return getattr(self._client, name)


class _GuardedTable:
    def __init__(self, guard: IntelligenceWriteGuard, inner: Any, name: str) -> None:
        self._guard = guard
        self._inner = inner
        self._name = name

    def __getattr__(self, name: str):
        if name in _WRITE_METHODS:
            allowed = ALLOWED_WRITE_TABLES.get(self._name, frozenset())
            if name not in allowed:
                def _blocked(*_args: Any, **_kwargs: Any) -> Any:
                    self._guard.blocked.append(f"{self._name}.{name}")
                    raise RuntimeError(f"blocked write {self._name}.{name}")

                return _blocked
        return getattr(self._inner, name)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BIST canonical intelligence refresh")
    parser.add_argument("--symbols", default=",".join(PILOT_SYMBOLS))
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--live", action="store_true", default=False)
    parser.add_argument("--persist-si", action="store_true", default=False)
    parser.add_argument("--persist-participation", action="store_true", default=False)
    parser.add_argument("--allow-live", action="store_true", default=False)
    parser.add_argument("--allow-broad", action="store_true", default=False)
    parser.add_argument("--as-of", default="")
    parser.add_argument("--state-file", default=STATE_CACHE_PATH)
    return parser.parse_args(argv)


def resolve_execution_mode(args: argparse.Namespace) -> dict[str, Any]:
    """Safe defaults unless --live and explicit persist flags are set."""
    live = bool(args.live)
    persist_si = bool(args.persist_si) and live
    persist_participation = bool(args.persist_participation) and live
    dry_run = not live
    allow_live = bool(args.allow_live or live)
    return {
        "live": live,
        "dry_run": dry_run,
        "persist_si": persist_si,
        "persist_participation": persist_participation,
        "allow_live": allow_live,
        "allow_broad": bool(args.allow_broad),
    }


def load_refresh_state(path: Path) -> BistRefreshState:
    if not path.is_file():
        return BistRefreshState()
    try:
        return BistRefreshState.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return BistRefreshState()


def save_refresh_state(path: Path, state: BistRefreshState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.to_dict(), indent=2), encoding="utf-8")


def _kafif_id_from_snapshot(row: Optional[dict[str, Any]]) -> str:
    if not row:
        return ""
    payload = row.get("assessment_payload") or {}
    assessment = payload.get("participation_assessment") or {}
    for blob in (row.get("source_evidence") or {}, payload, assessment, payload.get("source_evidence") or {}):
        if not isinstance(blob, dict):
            continue
        for key in ("source_notification_id", "disclosure_id", "kafif_id"):
            value = str(blob.get(key) or "").strip()
            if value:
                return value
    return ""


def load_official_inputs(
    symbols: list[str],
    *,
    allow_live: bool,
    participation_repo: Any = None,
) -> dict[str, Any]:
    """Official Borsa/KAP sources only. Never imports test fixtures."""
    memberships: dict[str, Any] = {}
    kafif_discoveries: dict[str, tuple] = {}
    kafif_documents: dict[str, Any] = {}
    source_failures: dict[str, str] = {}
    katilim = BistKatilimTumSource(allow_live=allow_live)
    kafif_source = KapKafifSource(allow_live=allow_live)
    try:
        snapshot = katilim.fetch_snapshot()
    except Exception:
        snapshot = None
    for symbol in symbols:
        if snapshot is None:
            from services.bist_katilim_tum_parser import membership_for_symbol

            memberships[symbol] = membership_for_symbol(None, symbol, source_unavailable=True)
        else:
            from services.bist_katilim_tum_parser import membership_for_symbol

            memberships[symbol] = membership_for_symbol(snapshot, symbol)
        disclosure_id = ""
        if participation_repo is not None:
            try:
                disclosure_id = _kafif_id_from_snapshot(participation_repo.get_latest(symbol))
            except Exception:
                disclosure_id = ""
        if not disclosure_id:
            continue
        from services.kap_kafif_contract import KapKafifDiscovery

        kafif_discoveries[symbol] = (
            KapKafifDiscovery(
                symbol=symbol,
                disclosure_id=disclosure_id,
                submitted_at="",
                financial_year="",
                period="",
                source_url=f"https://www.kap.org.tr/tr/Bildirim/{disclosure_id}",
            ),
        )
        try:
            kafif_documents[symbol] = kafif_source.fetch_form(disclosure_id, symbol=symbol)
        except Exception:
            pass
    return {
        "memberships": memberships,
        "kafif_discoveries": kafif_discoveries,
        "kafif_documents": kafif_documents,
        "source_failures": source_failures,
    }


def attach_production_repos(*, persist_si: bool, persist_participation: bool):
    from services.supabase_admin_client import (
        apply_local_secrets_to_env,
        create_admin_supabase_client,
    )

    apply_local_secrets_to_env()
    raw = create_admin_supabase_client()
    guarded = IntelligenceWriteGuard(raw)
    snapshot_repo = SecurityIntelligenceSnapshotRepository(guarded) if persist_si else None
    participation_repo = (
        ParticipationAssessmentRepository(guarded) if persist_participation else None
    )
    if persist_si and snapshot_repo is None:
        raise RuntimeError(REASON_LIVE_UNSAFE)
    if persist_participation and participation_repo is None:
        raise RuntimeError(REASON_LIVE_UNSAFE)
    return guarded, snapshot_repo, participation_repo


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    mode = resolve_execution_mode(args)
    symbols = [normalize_symbol(item) for item in args.symbols.split(",") if item.strip()]
    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
    extra = [item for item in symbols if item not in PILOT_SYMBOLS]
    if extra and mode["live"] and (mode["persist_si"] or mode["persist_participation"]) and not mode["allow_broad"]:
        payload = {
            "job_name": JOB_NAME,
            "status": "refused",
            "errors": [REASON_PILOT_SCOPE],
            "symbols": symbols,
            "dry_run": True,
            "persist_si": False,
            "persist_participation": False,
        }
        print(json.dumps(payload, indent=2, default=str))
        return 0
    snapshot_repo = None
    participation_repo = None
    guard = None
    if mode["live"] and (mode["persist_si"] or mode["persist_participation"]):
        try:
            guard, snapshot_repo, participation_repo = attach_production_repos(
                persist_si=mode["persist_si"],
                persist_participation=mode["persist_participation"],
            )
        except Exception as exc:
            payload = {
                "job_name": JOB_NAME,
                "status": "refused",
                "errors": [REASON_LIVE_UNSAFE, type(exc).__name__],
                "dry_run": True,
                "persist_si": False,
                "persist_participation": False,
            }
            print(json.dumps(payload, indent=2, default=str))
            return 1
    official = load_official_inputs(
        symbols,
        allow_live=mode["allow_live"],
        participation_repo=participation_repo,
    )
    state_path = Path(args.state_file)
    prior = load_refresh_state(state_path)
    if not prior.membership_keys and official["memberships"]:
        seeded = [
            (symbol, _membership_key(official["memberships"].get(symbol)))
            for symbol in symbols
            if _membership_key(official["memberships"].get(symbol))
        ]
        kafif_ids = [
            (symbol, rows[0].disclosure_id)
            for symbol, rows in official["kafif_discoveries"].items()
            if rows
        ]
        prior = BistRefreshState(
            known_notification_ids=prior.known_notification_ids,
            latest_kafif_ids=tuple(kafif_ids) or prior.latest_kafif_ids,
            latest_kafif_submitted=prior.latest_kafif_submitted,
            latest_thb_date=prior.latest_thb_date,
            participation_keys=prior.participation_keys,
            membership_keys=tuple(seeded),
            capital_versions=prior.capital_versions,
        )
    run = run_bist_refresh(
        symbols,
        dry_run=mode["dry_run"],
        persist_si=mode["persist_si"],
        persist_participation=mode["persist_participation"],
        allow_live=mode["allow_live"],
        allow_broad=mode["allow_broad"],
        as_of=as_of,
        state=prior,
        thb_cache=load_history_cache(),
        snapshot_repo=snapshot_repo,
        participation_repo=participation_repo,
        memberships=official["memberships"],
        kafif_discoveries=official["kafif_discoveries"],
        kafif_documents=official["kafif_documents"],
        source_failures=official["source_failures"],
        max_symbols=MAX_SYMBOLS_DEFAULT,
    )
    if not mode["dry_run"]:
        save_refresh_state(state_path, run.next_state)
    payload = run.to_dict()
    payload["job_name"] = JOB_NAME
    payload["cli_live"] = mode["live"]
    payload["cli_persist_si"] = mode["persist_si"]
    payload["cli_persist_participation"] = mode["persist_participation"]
    payload["symbols"] = symbols
    if guard is not None:
        payload["blocked_writes"] = list(guard.blocked)
    print(json.dumps(payload, indent=2, default=str))
    return 0 if run.status in {"completed", "partial", "refused"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
