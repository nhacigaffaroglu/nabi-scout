#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.fmp_client import FMPClient
from services.us_security_intelligence_refresh import (
    MAX_SYMBOLS_DEFAULT,
    run_us_security_intelligence_refresh,
)


ALLOWED_WRITE_TABLES = {
    "security_intelligence_snapshots": frozenset({"upsert"}),
}
WRITE_METHODS = frozenset({"insert", "update", "upsert", "delete"})


class SiWriteGuard:
    def __init__(self, client: Any) -> None:
        self._client = client
        self.blocked: list[str] = []
        self.allowed_write_attempts: list[str] = []

    def table(self, name: str):
        return _GuardedTable(self, self._client.table(name), name)

    def __getattr__(self, name: str):
        return getattr(self._client, name)


class _GuardedTable:
    def __init__(self, guard: SiWriteGuard, inner: Any, name: str) -> None:
        self._guard = guard
        self._inner = inner
        self._name = name

    def __getattr__(self, name: str):
        if name in WRITE_METHODS:
            allowed = ALLOWED_WRITE_TABLES.get(self._name, frozenset())
            if name not in allowed:
                def blocked(*_args: Any, **_kwargs: Any):
                    self._guard.blocked.append(f"{self._name}.{name}")
                    raise RuntimeError(f"blocked write {self._name}.{name}")
                return blocked

            inner_method = getattr(self._inner, name)

            def permitted(*args: Any, **kwargs: Any):
                self._guard.allowed_write_attempts.append(
                    f"{self._name}.{name}"
                )
                return inner_method(*args, **kwargs)

            return permitted

        return getattr(self._inner, name)


def parse_args(argv: Optional[list[str]] = None):
    parser = argparse.ArgumentParser(
        description="Controlled US canonical Security Intelligence refresh"
    )
    parser.add_argument("--symbols", required=True)
    parser.add_argument("--execute", action="store_true", default=False)
    parser.add_argument("--live", action="store_true", default=False)
    parser.add_argument("--persist-si", action="store_true", default=False)
    parser.add_argument("--allow-live", action="store_true", default=False)
    parser.add_argument("--max-symbols", type=int, default=MAX_SYMBOLS_DEFAULT)
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    symbols = [
        item.strip().upper()
        for item in args.symbols.split(",")
        if item.strip()
    ]

    from services.supabase_admin_client import (
        apply_local_secrets_to_env,
        create_admin_supabase_client,
    )

    apply_local_secrets_to_env()
    raw = create_admin_supabase_client()
    guarded = SiWriteGuard(raw)

    execute = bool(args.execute or args.live)
    fmp = None
    if execute:
        try:
            fmp = FMPClient.from_env()
        except Exception:
            fmp = FMPClient.from_streamlit_secrets()

    run = run_us_security_intelligence_refresh(
        symbols,
        client=guarded,
        fmp_client=fmp,
        dry_run=not args.live,
        execute_providers=execute,
        persist_si=bool(args.persist_si),
        allow_live=bool(args.allow_live),
        max_symbols=args.max_symbols,
    )

    payload = run.to_dict()
    payload["blocked_writes"] = list(guarded.blocked)
    payload["allowed_write_attempts"] = list(
        guarded.allowed_write_attempts
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))

    if guarded.blocked:
        return 2
    if run.errors:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
