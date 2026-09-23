from __future__ import annotations

from pathlib import Path

import pytest

from services.us_si_approved_cohort import (
    APPROVED_US_SI_REFRESH_COHORT,
    MAX_APPROVED_US_SI_REFRESH_COHORT,
    approved_us_si_refresh_symbols,
    validate_approved_us_si_refresh_cohort,
)


ROOT = Path(__file__).resolve().parents[1]


def test_approved_cohort_contains_verified_expansion_symbols():
    assert APPROVED_US_SI_REFRESH_COHORT == (
        "CRM",
        "ADBE",
        "MU",
        "BIIB",
    )
    assert approved_us_si_refresh_symbols() == (
        "CRM",
        "ADBE",
        "MU",
        "BIIB",
    )


def test_cohort_is_bounded_for_next_rollout_stage():
    assert MAX_APPROVED_US_SI_REFRESH_COHORT == 10
    assert len(validate_approved_us_si_refresh_cohort()) == 4


def test_validation_normalizes_symbols():
    assert validate_approved_us_si_refresh_cohort(
        [" crm ", "ADBE", "mu"]
    ) == ("CRM", "ADBE", "MU")


def test_validation_rejects_duplicates():
    with pytest.raises(ValueError, match="duplicates"):
        validate_approved_us_si_refresh_cohort(
            ["CRM", "CRM"]
        )


def test_validation_rejects_empty_cohort():
    with pytest.raises(ValueError, match="empty"):
        validate_approved_us_si_refresh_cohort([])


def test_validation_rejects_over_limit():
    symbols = [f"S{i}" for i in range(11)]
    with pytest.raises(ValueError, match="exceeds"):
        validate_approved_us_si_refresh_cohort(symbols)


def test_workflow_loads_central_cohort_instead_of_hardcoding_symbols():
    text = (
        ROOT / ".github/workflows/us_si_3symbol_canary.yml"
    ).read_text(encoding="utf-8")

    assert (
        'COHORT="$(python scripts/print_us_si_approved_cohort.py)"'
        in text
    )
    assert "for SYMBOL in $COHORT; do" in text
    assert "for SYMBOL in CRM ADBE MU; do" not in text


def test_workflow_keeps_symbol_isolation_and_live_write_contract():
    text = (
        ROOT / ".github/workflows/us_si_3symbol_canary.yml"
    ).read_text(encoding="utf-8")

    assert '--symbols "$SYMBOL"' in text
    assert "--max-symbols 1" in text
    assert "--execute" in text
    assert "--live" in text
    assert "--persist-si" in text
    assert "--allow-live" in text
    assert 'status in {"PUBLISHED", "NO_CHANGE"}' in text
    assert 'payload.get("blocked_writes") == []' in text


def test_workflow_schedule_remains_active():
    text = (
        ROOT / ".github/workflows/us_si_3symbol_canary.yml"
    ).read_text(encoding="utf-8")

    assert "schedule:" in text
    assert 'cron: "30 22 * * 1-5"' in text
