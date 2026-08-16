#!/usr/bin/env python3
"""Daily deterministic monitor refresh — no LLM, no FMP/SEC."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from repositories.participation_assessment_repository import ParticipationAssessmentRepository
from repositories.investment_thesis_repository import InvestmentThesisRepository
from repositories.monitor_event_repository import MonitorEventRepository
from repositories.monitor_run_repository import MonitorRunRepository
from services.monitor_dedupe import draft_to_row
from services.monitor_event_detectors import detect_participation_events, detect_thesis_events
from services.monitor_refresh_service import evaluate_scheduled_monitor_run, finish_monitor_run
from services.supabase_admin_client import apply_local_secrets_to_env, create_admin_supabase_client


def _write_github_summary(payload: dict) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    lines = [
        "## Daily Monitor Refresh",
        "",
        f"- **Run ID:** `{payload.get('run_id', '—')}`",
        f"- **Status:** {payload.get('status', '—')}",
        f"- **Events created:** {payload.get('created', 0)}",
        f"- **Events deduped/skipped:** {payload.get('skipped', 0)}",
        f"- **Symbols scanned:** {payload.get('symbols_scanned', 0)}",
        f"- **Portfolio events:** {payload.get('portfolio_events', 0)}",
        f"- **Participation events:** {payload.get('participation_events', 0)}",
        f"- **Thesis events:** {payload.get('thesis_events', 0)}",
        f"- **High/Critical:** {payload.get('high_critical', 0)}",
        f"- **FMP calls:** 0",
        f"- **SEC calls:** 0",
        f"- **LLM calls:** 0",
    ]
    Path(summary_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily monitor event refresh")
    parser.add_argument(
        "--trigger-type",
        default="scheduled",
        choices=("scheduled", "workflow_dispatch", "manual"),
    )
    parser.add_argument("--allow-second-run-today", action="store_true")
    args = parser.parse_args()

    apply_local_secrets_to_env()
    client = create_admin_supabase_client()
    run_repo = MonitorRunRepository(client)
    event_repo = MonitorEventRepository(client)
    participation_repo = ParticipationAssessmentRepository(client)
    thesis_repo = InvestmentThesisRepository(client)

    gate = evaluate_scheduled_monitor_run(
        run_repo,
        trigger_type=args.trigger_type,
        allow_second_run_today=args.allow_second_run_today,
    )
    if gate.get("skipped"):
        result = {"status": "skipped", **gate}
        print(json.dumps(result, default=str))
        _write_github_summary(result)
        return 0

    run_id = str(gate["run_id"])
    created = skipped = 0
    participation_events = thesis_events = high_critical = 0
    symbols: set[str] = set()

    for row in client.table("investment_candidates").select("symbol").limit(500).execute().data or []:
        symbol = str(row.get("symbol") or "").upper()
        if symbol:
            symbols.add(symbol)

    for symbol in sorted(symbols):
        participation_history = participation_repo.get_recent_history(symbol, limit=2)
        if len(participation_history) >= 2:
            for draft in detect_participation_events(
                symbol=symbol,
                previous_row=participation_history[1],
                current_row=participation_history[0],
            ):
                _, inserted = event_repo.upsert_draft(draft_to_row(draft, detected_at=draft.occurred_at))
                if inserted:
                    created += 1
                    participation_events += 1
                    if draft.materiality in {"high", "critical"}:
                        high_critical += 1
                else:
                    skipped += 1
        thesis_history = thesis_repo.get_recent_history(symbol, limit=2)
        if len(thesis_history) >= 2:
            for draft in detect_thesis_events(
                symbol=symbol,
                current_row=thesis_history[0],
                previous_row=thesis_history[1],
            ):
                _, inserted = event_repo.upsert_draft(draft_to_row(draft, detected_at=draft.occurred_at))
                if inserted:
                    created += 1
                    thesis_events += 1
                    if draft.materiality in {"high", "critical"}:
                        high_critical += 1
                else:
                    skipped += 1

    report = {
        "symbols_scanned": len(symbols),
        "created": created,
        "skipped": skipped,
        "participation_events": participation_events,
        "thesis_events": thesis_events,
        "portfolio_events": 0,
        "high_critical": high_critical,
    }
    finish_monitor_run(
        run_repo,
        run_id=run_id,
        events_created=created,
        events_skipped=skipped,
        report_payload=report,
    )
    result = {"status": "completed", "run_id": run_id, **report}
    print(json.dumps(result, default=str))
    _write_github_summary(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
