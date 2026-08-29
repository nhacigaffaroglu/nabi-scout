#!/usr/bin/env python3
"""Apply additive security_intelligence_snapshots migration.

Does not write portfolio/Participation/candidate/Hybrid tables.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.supabase_admin_client import apply_local_secrets_to_env, load_local_secrets_toml

MIGRATION = ROOT / "database" / "migration_security_intelligence_snapshots.sql"


def resolve_db_url() -> str:
    apply_local_secrets_to_env()
    secrets = load_local_secrets_toml()
    supabase = secrets.get("supabase") if isinstance(secrets.get("supabase"), dict) else {}
    for item in (
        os.environ.get("SUPABASE_DB_URL"),
        os.environ.get("DATABASE_URL"),
        os.environ.get("SUPABASE_DATABASE_URL"),
        supabase.get("db_url"),
        supabase.get("database_url"),
        supabase.get("postgres_url"),
        supabase.get("connection_string"),
    ):
        text = str(item or "").strip()
        if text:
            return text
    return ""


def apply_migration() -> dict[str, Any]:
    db_url = resolve_db_url()
    if not db_url:
        return {"applied": False, "reason": "no database url"}
    sql = MIGRATION.read_text(encoding="utf-8")
    try:
        import psycopg

        with psycopg.connect(db_url, autocommit=True) as conn:
            conn.execute(sql)
        return {"applied": True, "driver": "psycopg"}
    except ImportError:
        pass
    try:
        import psycopg2

        conn = psycopg2.connect(db_url)
        try:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(sql)
        finally:
            conn.close()
        return {"applied": True, "driver": "psycopg2"}
    except ImportError:
        return {"applied": False, "reason": "psycopg/psycopg2 not installed"}
    except Exception as exc:
        return {"applied": False, "reason": str(exc)[:240]}


if __name__ == "__main__":
    print(json.dumps(apply_migration(), indent=2))
