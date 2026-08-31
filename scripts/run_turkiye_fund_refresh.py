#!/usr/bin/env python3
"""Turkish fund canonical snapshot refresh.

Default is dry-run with zero writes. Production writes require explicit
--live plus --persist-participation and/or --persist-fund-intelligence.
Credentials never enable writes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.bist_refresh_contract import REASON_LIVE_UNSAFE, REASON_PILOT_SCOPE
from services.fund_product_contract import PILOT_TEFAS_FUND_CODES
from services.turkiye_fund_refresh_contract import (
    JOB_NAME,
    REASON_FORBIDDEN_LAYER,
    STATE_CACHE_PATH,
    TurkiyeFundRefreshState,
)
from services.turkiye_fund_refresh_orchestrator import run_turkiye_fund_refresh


ALLOWED_WRITE_TABLES = {
    "participation_assessment_snapshots": frozenset({"insert"}),
    "security_intelligence_snapshots": frozenset({"upsert", "insert"}),
}
_WRITE_METHODS = frozenset({"insert", "update", "upsert", "delete"})


class IntelligenceWriteGuard:
    """Allow only Participation insert and FI upsert. Block portfolio writes."""

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
    parser = argparse.ArgumentParser(description="Turkish fund canonical snapshot refresh")
    parser.add_argument("--symbols", default="")
    parser.add_argument("--funds", default="")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--live", action="store_true", default=False)
    parser.add_argument("--persist-fund-intelligence", action="store_true", default=False)
    parser.add_argument("--persist-participation", action="store_true", default=False)
    parser.add_argument("--persist-economic-exposure", action="store_true", default=False)
    parser.add_argument("--persist-decisions", action="store_true", default=False)
    parser.add_argument("--allow-live", action="store_true", default=False)
    parser.add_argument("--allow-broad", action="store_true", default=False)
    parser.add_argument("--state-file", default=STATE_CACHE_PATH)
    return parser.parse_args(argv)


def resolve_fund_codes(args: argparse.Namespace) -> list[str]:
    raw = args.funds or args.symbols or ",".join(PILOT_TEFAS_FUND_CODES)
    return [item.strip().upper() for item in raw.split(",") if item.strip()]


def resolve_execution_mode(args: argparse.Namespace) -> dict[str, Any]:
    """Safe defaults unless --live and explicit persist flags are set."""
    forbidden = bool(args.persist_economic_exposure or args.persist_decisions)
    live = bool(args.live)
    persist_participation = bool(args.persist_participation) and live and not forbidden
    persist_fund_intelligence = bool(args.persist_fund_intelligence) and live and not forbidden
    return {
        "live": live,
        "cli_live": live,
        "dry_run": not (persist_participation or persist_fund_intelligence),
        "persist_participation": persist_participation,
        "persist_fund_intelligence": persist_fund_intelligence,
        "persist_economic_exposure": bool(args.persist_economic_exposure),
        "persist_decisions": bool(args.persist_decisions),
        "forbidden": forbidden,
        "allow_broad": bool(getattr(args, "allow_broad", False)),
        "allow_live": bool(args.allow_live or live),
    }


def writes_enabled(args: argparse.Namespace) -> bool:
    mode = resolve_execution_mode(args)
    return bool(mode["persist_participation"] or mode["persist_fund_intelligence"])


def live_requested(args: argparse.Namespace) -> bool:
    return bool(
        args.live
        or args.allow_live
        or args.persist_fund_intelligence
        or args.persist_participation
        or args.persist_economic_exposure
        or args.persist_decisions
        or (not args.dry_run)
    )


def load_refresh_state(path: Path) -> TurkiyeFundRefreshState:
    if not path.is_file():
        return TurkiyeFundRefreshState()
    try:
        return TurkiyeFundRefreshState.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return TurkiyeFundRefreshState()


def save_refresh_state(path: Path, state: TurkiyeFundRefreshState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.to_dict(), indent=2), encoding="utf-8")


def attach_production_repos(*, persist_fund_intelligence: bool, persist_participation: bool):
    from repositories.participation_assessment_repository import (
        ParticipationAssessmentRepository,
    )
    from repositories.security_intelligence_snapshot_repository import (
        SecurityIntelligenceSnapshotRepository,
    )
    from services.supabase_admin_client import (
        apply_local_secrets_to_env,
        create_admin_supabase_client,
    )

    apply_local_secrets_to_env()
    raw = create_admin_supabase_client()
    guarded = IntelligenceWriteGuard(raw)
    snapshot_repo = (
        SecurityIntelligenceSnapshotRepository(guarded) if persist_fund_intelligence else None
    )
    participation_repo = (
        ParticipationAssessmentRepository(guarded) if persist_participation else None
    )
    if persist_fund_intelligence and snapshot_repo is None:
        raise RuntimeError(REASON_LIVE_UNSAFE)
    if persist_participation and participation_repo is None:
        raise RuntimeError(REASON_LIVE_UNSAFE)
    return guarded, snapshot_repo, participation_repo


def main(
    argv: Optional[list[str]] = None,
    *,
    attach_repos=None,
) -> int:
    args = parse_args(argv)
    mode = resolve_execution_mode(args)
    symbols = resolve_fund_codes(args)
    if mode["forbidden"]:
        payload: dict[str, Any] = {
            "job_name": JOB_NAME,
            "status": "LIVE_BLOCKED",
            "errors": [REASON_FORBIDDEN_LAYER],
            "symbols": symbols,
            "fund_codes": symbols,
            "dry_run": True,
            "writes": 0,
            "persist_fund_intelligence": False,
            "persist_participation": False,
            "persist_economic_exposure": False,
            "persist_decisions": False,
            "cli_live": mode["live"],
        }
        print(json.dumps(payload, indent=2, default=str))
        return 1
    extra = [item for item in symbols if item not in PILOT_TEFAS_FUND_CODES]
    if extra and mode["live"] and writes_enabled(args) and not mode["allow_broad"]:
        payload = {
            "job_name": JOB_NAME,
            "status": "LIVE_BLOCKED",
            "errors": [REASON_PILOT_SCOPE],
            "symbols": symbols,
            "fund_codes": symbols,
            "dry_run": True,
            "writes": 0,
            "persist_fund_intelligence": False,
            "persist_participation": False,
        }
        print(json.dumps(payload, indent=2, default=str))
        return 1
    snapshot_repo = None
    participation_repo = None
    guard = None
    if writes_enabled(args):
        try:
            attach = attach_repos or attach_production_repos
            guard, snapshot_repo, participation_repo = attach(
                persist_fund_intelligence=mode["persist_fund_intelligence"],
                persist_participation=mode["persist_participation"],
            )
        except Exception as exc:
            payload = {
                "job_name": JOB_NAME,
                "status": "LIVE_BLOCKED",
                "errors": [REASON_LIVE_UNSAFE, type(exc).__name__],
                "symbols": symbols,
                "dry_run": True,
                "writes": 0,
                "persist_fund_intelligence": False,
                "persist_participation": False,
            }
            print(json.dumps(payload, indent=2, default=str))
            return 1
    previous = (
        load_refresh_state(Path(args.state_file))
        if writes_enabled(args)
        else TurkiyeFundRefreshState()
    )
    run = run_turkiye_fund_refresh(
        symbols=symbols,
        dry_run=mode["dry_run"],
        persist_fund_intelligence=mode["persist_fund_intelligence"],
        persist_participation=mode["persist_participation"],
        persist_economic_exposure=False,
        persist_decisions=False,
        allow_live=mode["allow_live"],
        allow_broad=mode["allow_broad"],
        cli_live=mode["cli_live"],
        previous_state=previous,
        participation_repo=participation_repo,
        snapshot_repo=snapshot_repo,
    )
    if writes_enabled(args) and run.status == "LIVE":
        save_refresh_state(Path(args.state_file), run.next_state)
    payload = run.to_dict()
    payload["state_file"] = args.state_file
    payload["state_written"] = bool(writes_enabled(args) and run.status == "LIVE")
    payload["cli_live"] = mode["live"]
    if guard is not None:
        payload["blocked_writes"] = list(guard.blocked)
    print(json.dumps(payload, indent=2, default=str))
    if run.status == "ERROR":
        return 1
    if run.status == "LIVE_BLOCKED":
        return 1
    return 0 if run.writes == 0 or run.status == "LIVE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
