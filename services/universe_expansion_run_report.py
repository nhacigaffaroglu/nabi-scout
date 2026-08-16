from __future__ import annotations

from typing import Mapping


def format_expansion_run_summary(
    report: Mapping[str, object],
    *,
    trigger: str,
    queue_counts: Mapping[str, int] | None = None,
) -> str:
    queue_counts = dict(queue_counts or report.get("queue_counts") or {})
    remaining_pending = int(queue_counts.get("PENDING") or 0)
    remaining_retryable = int(queue_counts.get("RETRYABLE") or 0)
    lines = [
        "# Daily Universe Expansion",
        "",
        f"- run_id: {report.get('run_id', '')}",
        f"- trigger: {trigger}",
        f"- dry_run: {report.get('dry_run', False)}",
        f"- stop_reason: {report.get('stop_reason') or 'none'}",
        f"- symbols_considered: {report.get('symbols_considered', 0)}",
        f"- symbols_started: {report.get('symbols_started', 0)}",
        f"- symbols_completed: {report.get('symbols_completed', 0)}",
        f"- symbols_retryable: {report.get('symbols_retryable', 0)}",
        f"- symbols_blocked: {report.get('symbols_blocked', 0)}",
        f"- symbols_skipped: {report.get('symbols_skipped', 0)}",
        f"- queue_pending: {remaining_pending}",
        f"- queue_retryable: {remaining_retryable}",
        f"- fmp_remote_calls: {report.get('fmp_calls_used', 0)}",
        f"- sec_remote_calls: {report.get('sec_calls_used', 0)}",
        f"- cache_hits: {report.get('cache_hits') or {}}",
        f"- budget_remaining: {report.get('budget_remaining') or {}}",
    ]
    return "\n".join(lines)


def write_github_step_summary(
    report: Mapping[str, object],
    *,
    trigger: str,
    queue_counts: Mapping[str, int] | None = None,
) -> None:
    import os

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    content = format_expansion_run_summary(
        report,
        trigger=trigger,
        queue_counts=queue_counts,
    )
    with open(summary_path, "a", encoding="utf-8") as handle:
        handle.write(content)
        handle.write("\n")
