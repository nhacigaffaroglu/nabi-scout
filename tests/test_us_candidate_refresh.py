from __future__ import annotations

from pathlib import Path

import pytest

from scripts.refresh_us_candidate_subset import (
    CandidateRefreshWriteGuard,
    _degradable_provider_warnings,
    parse_args,
)


WORKFLOW = Path(
    ".github/workflows/us_candidate_refresh.yml"
)


class FakeQuery:
    def eq(self, *_args, **_kwargs):
        return self

    def execute(self):
        return "allowed"


class FakeTable:
    def update(self, *_args, **_kwargs):
        return FakeQuery()

    def upsert(self, *_args, **_kwargs):
        return FakeQuery()


class FakeClient:
    def table(self, _name):
        return FakeTable()


def source() -> str:
    return WORKFLOW.read_text(
        encoding="utf-8"
    )


def test_workflow_is_manual_only():
    text = source()

    assert "workflow_dispatch:" in text
    assert "schedule:" not in text
    assert "cron:" not in text


def test_workflow_is_bounded_to_two_symbols():
    text = source()

    assert "--max-symbols 2" in text
    assert "at most 2 symbols" in text
    assert "REFRESH_US_CANDIDATES" in text


def test_workflow_only_accepts_candidate_update_write():
    text = source()

    assert (
        '"investment_candidates.update"'
        in text
    )
    assert 'payload["blocked"]' in text
    assert 'payload["errors"]' in text


def test_workflow_requires_fresh_period_after_refresh():
    text = source()

    assert '"FRESH"' in text
    assert "financial_period_end" in text
    assert "CANDIDATE_REFRESH_GATE=PASS" in text


def test_cli_defaults_are_zero_write():
    args = parse_args(
        ["--symbols", "ADBE"]
    )

    assert args.execute is False
    assert args.persist_candidate is False
    assert args.allow_live is False


def test_cli_controlled_live_flags_are_explicit():
    args = parse_args([
        "--symbols",
        "ADBE,ADSK",
        "--max-symbols",
        "2",
        "--execute",
        "--persist-candidate",
        "--allow-live",
    ])

    assert args.execute is True
    assert args.persist_candidate is True
    assert args.allow_live is True
    assert args.max_symbols == 2


def test_guard_allows_only_candidate_update():
    guard = CandidateRefreshWriteGuard(
        FakeClient()
    )

    result = (
        guard.table(
            "investment_candidates"
        )
        .update({"freshness_status": "FRESH"})
        .eq("id", "candidate-1")
        .execute()
    )

    assert result == "allowed"
    assert guard.allowed_write_attempts == [
        "investment_candidates.update"
    ]
    assert guard.blocked == []


def test_guard_blocks_candidate_upsert():
    guard = CandidateRefreshWriteGuard(
        FakeClient()
    )

    with pytest.raises(
        RuntimeError,
        match=(
            r"blocked write "
            r"investment_candidates.upsert"
        ),
    ):
        guard.table(
            "investment_candidates"
        ).upsert({"symbol": "ADBE"})

    assert guard.blocked == [
        "investment_candidates.upsert"
    ]


def test_guard_blocks_other_table_updates():
    guard = CandidateRefreshWriteGuard(
        FakeClient()
    )

    with pytest.raises(
        RuntimeError,
        match=(
            r"blocked write "
            r"participation_assessment_snapshots.update"
        ),
    ):
        guard.table(
            "participation_assessment_snapshots"
        ).update({"status": "Uygun"})

    assert guard.blocked == [
        "participation_assessment_snapshots.update"
    ]


def test_plan_restricted_quote_and_ratios_are_degradable_with_sec():
    allowed, warnings = _degradable_provider_warnings(
        {
            "fmp_profile": "OK",
            "fmp_quote": "PLAN_RESTRICTED",
            "fmp_ratios_ttm": "PLAN_RESTRICTED",
            "sec_companyfacts": "OK",
        },
        [
            "FMP quote: FMP endpoint erişimi reddedildi: quote",
            "FMP ratios_ttm: FMP endpoint erişimi reddedildi: ratios-ttm",
        ],
    )

    assert allowed is True
    assert len(warnings) == 2


def test_plan_restricted_quote_is_degradable_when_ratios_ok():
    allowed, _ = _degradable_provider_warnings(
        {
            "fmp_profile": "OK",
            "fmp_quote": "PLAN_RESTRICTED",
            "fmp_ratios_ttm": "OK",
            "sec_companyfacts": "OK",
        },
        [
            "FMP quote: FMP endpoint erişimi reddedildi: quote",
        ],
    )

    assert allowed is True


@pytest.mark.parametrize(
    "endpoint_status,errors",
    [
        (
            {
                "fmp_profile": "AUTH_ERROR",
                "fmp_quote": "PLAN_RESTRICTED",
                "sec_companyfacts": "OK",
            },
            [
                "FMP profile: auth failure",
                "FMP quote: restricted",
            ],
        ),
        (
            {
                "fmp_profile": "OK",
                "fmp_quote": "RATE_LIMIT",
                "sec_companyfacts": "OK",
            },
            ["FMP quote: rate limited"],
        ),
        (
            {
                "fmp_profile": "OK",
                "fmp_quote": "PLAN_RESTRICTED",
                "sec_companyfacts": "SERVER_ERROR",
            },
            [
                "FMP quote: restricted",
                "SEC Company Facts: unavailable",
            ],
        ),
        (
            {
                "fmp_profile": "OK",
                "fmp_quote": "PLAN_RESTRICTED",
                "sec_companyfacts": "OK",
            },
            [
                "FMP quote: restricted",
                "unexpected provider warning",
            ],
        ),
    ],
)
def test_non_approved_provider_failures_remain_fatal(
    endpoint_status,
    errors,
):
    allowed, _ = _degradable_provider_warnings(
        endpoint_status,
        errors,
    )

    assert allowed is False
