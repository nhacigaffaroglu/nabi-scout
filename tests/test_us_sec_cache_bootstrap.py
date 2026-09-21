from __future__ import annotations

from pathlib import Path

from scripts.refresh_sec_participation_evidence import parse_args
from services.sec_participation_evidence_refresh import (
    plan_sec_evidence_refresh,
)
from services.universe_expansion_contract import (
    EXPANSION_STATUS_COMPLETED,
)


WORKFLOW = Path(".github/workflows/us_sec_cache_bootstrap.yml")


class EmptyCache:
    def get_latest(self, **_kwargs):
        return None


def snapshot(symbol: str, cik: str) -> dict:
    return {
        "symbol": symbol,
        "status": "Uygun",
        "source_evidence": {
            "cik": cik,
            "provider": "SEC",
        },
        "assessment_payload": {
            "source_evidence": {
                "cik": cik,
                "provider": "SEC",
            }
        },
    }


def test_explicit_symbol_scope_filters_broad_population():
    plan = plan_sec_evidence_refresh(
        queue_rows=[
            {"symbol": "CRM", "status": EXPANSION_STATUS_COMPLETED},
            {"symbol": "AAPL", "status": EXPANSION_STATUS_COMPLETED},
        ],
        snapshots_by_symbol={
            "CRM": snapshot("CRM", "1108524"),
            "AAPL": snapshot("AAPL", "320193"),
        },
        cache=EmptyCache(),
        symbols=["crm"],
    )

    assert plan.population.symbols == ("CRM",)
    assert plan.cache_misses == ("CRM",)
    assert plan.expected_sec_calls == 1
    assert plan.identity_blocked == ()


def test_requested_symbol_outside_assessed_population_fails_closed():
    plan = plan_sec_evidence_refresh(
        queue_rows=[
            {"symbol": "CRM", "status": EXPANSION_STATUS_COMPLETED},
        ],
        snapshots_by_symbol={
            "CRM": snapshot("CRM", "1108524"),
        },
        cache=EmptyCache(),
        symbols=["AAPL"],
    )

    assert plan.population.symbols == ()
    assert plan.refresh_candidates == ()
    assert plan.identity_blocked == ("AAPL",)


def test_cli_explicit_scope_defaults_to_max_three():
    args = parse_args(
        [
            "--fetch",
            "--symbols",
            "CRM,AAPL",
        ]
    )

    assert args.fetch is True
    assert args.symbols == "CRM,AAPL"
    assert args.max_symbols == 3


def test_bootstrap_workflow_is_manual_only_and_cache_only():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in text
    assert "schedule:" not in text
    assert "cron:" not in text

    assert "scripts/refresh_sec_participation_evidence.py" in text
    assert "--fetch" in text
    assert "--symbols" in text
    assert "--max-symbols 3" in text

    assert "actions/cache/restore@v4" in text
    assert "actions/cache/save@v4" in text
    assert "data/private/sec_company_facts" in text

    assert "FMP_API_KEY" not in text
    assert "run_us_security_intelligence_refresh.py" not in text
    assert "--persist-si" not in text
    assert "--allow-live" not in text
    assert "--live" not in text


def test_bootstrap_contract_requires_zero_database_writes():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert 'report["participation_snapshot_writes"] == 0' in text
    assert 'report["candidate_writes"] == 0' in text
    assert 'report["queue_writes"] == 0' in text
    assert 'fetch.get("failed") == []' in text
    assert 'report.get("identity_blocked") == []' in text
