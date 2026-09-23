from pathlib import Path


WORKFLOW = Path(".github/workflows/us_si_3symbol_canary.yml")


def text():
    return WORKFLOW.read_text(encoding="utf-8")


def test_canary_supports_manual_and_scheduled_execution():
    src = text()
    assert "workflow_dispatch:" in src
    assert "schedule:" in src
    assert 'cron: "30 22 * * 1-5"' in src


def test_scope_is_approved_cohort_and_symbol_isolated():
    src = text()
    assert 'COHORT="$(python scripts/print_us_si_approved_cohort.py)"' in src
    assert "for SYMBOL in $COHORT; do" in src
    assert "for SYMBOL in CRM ADBE MU" not in src
    assert '--symbols "$SYMBOL"' in src
    assert "--max-symbols 1" in src


def test_uses_canonical_live_si_path():
    src = text()
    assert "run_us_security_intelligence_refresh.py" in src
    for flag in ("--execute", "--live", "--persist-si", "--allow-live"):
        assert flag in src


def test_no_discovery_or_candidate_mutation():
    src = text()
    assert "refresh_us_candidate_subset.py" not in src
    assert "run_daily_universe_expansion.py" not in src
    assert "--persist-candidate" not in src


def test_publish_contract_and_write_firewall_are_checked():
    src = text()
    assert 'status in {"PUBLISHED", "NO_CHANGE"}' in src
    assert 'payload.get("blocked_writes") == []' in src
    assert "security_intelligence_snapshots.upsert" in src


def test_failure_isolation_and_bounded_execution():
    src = text()
    assert "FAILED=$((FAILED + 1))" in src
    assert "CANARY_FAILURES=$FAILED" in src
    assert "timeout-minutes: 30" in src
    assert "cancel-in-progress: false" in src


def test_evidence_is_retained():
    src = text()
    assert "us_si_canary_${SYMBOL}.json" in src
    assert "us_si_canary_*.json" in src
    assert "retention-days: 14" in src
