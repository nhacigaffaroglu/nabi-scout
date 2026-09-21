from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.security_master_contract import (
    INSTRUMENT_EQUITY,
    RESOLUTION_RESOLVED,
    SOURCE_US_LISTING,
)
from services.us_security_intelligence_refresh import (
    REASON_FRESHNESS_NOT_FRESH,
    REASON_PLAN_ONLY,
    REASON_RESEARCH_NOT_ALLOWED,
    REASON_SEC_CACHE_PERIOD_OLD,
    STATUS_PLANNED,
    STATUS_WOULD_PUBLISH,
    run_us_security_intelligence_refresh,
)


class Repo:
    def __init__(self, row=None):
        self.row = row

    def get_by_symbol(self, _symbol):
        return self.row

    def get_latest(self, _symbol):
        return self.row


class Cache:
    def __init__(self, period="2025-01-31", cik="0001108524"):
        self.period = period
        self.evidence = SimpleNamespace(cik=cik)

    def get_latest(self, *, symbol=None, cik=None):
        return self.evidence

    def replay(self, _evidence):
        return {
            "financial_period_end": self.period,
            "financial_currency": "USD",
            "revenue": 100.0,
            "free_cash_flow": 20.0,
            "total_assets": 200.0,
            "total_debt": 20.0,
            "cash": 30.0,
            "equity": 100.0,
            "roic": 18.0,
        }


class Master:
    def resolve_security(self, symbol):
        return SimpleNamespace(
            symbol=symbol,
            status=RESOLUTION_RESOLVED,
            instrument_type=INSTRUMENT_EQUITY,
            source=SOURCE_US_LISTING,
            facts=(),
        )


class Ci:
    def __init__(self):
        self.calls = 0

    def build_view(self, symbol, **_kwargs):
        self.calls += 1
        return SimpleNamespace(
            symbol=symbol,
            as_of="2026-09-21T00:00:00+00:00",
            business_snapshot=None,
            financial_trends=None,
            valuation=None,
            peers=None,
        )

    def call_budget(self, symbol, **_kwargs):
        return {"profile": 1, "ratios_ttm": 1}


def candidate(*, freshness="FRESH", period="2025-01-31"):
    return {
        "symbol": "CRM",
        "company_name": "Salesforce",
        "market": "US",
        "cik": "1108524",
        "freshness_status": freshness,
        "financial_period_end": period,
        "revenue": 90.0,
        "market_cap": 250.0,
        "current_price": 250.0,
    }


def participation(*, allowed=True):
    return {
        "symbol": "CRM",
        "participation_status": PARTICIPATION_STATUS_UYGUN,
        "research_allowed": allowed,
        "assessed_at": "2026-09-20T00:00:00+00:00",
    }


def test_plan_mode_has_zero_provider_calls_and_zero_writes():
    ci = Ci()
    run = run_us_security_intelligence_refresh(
        ["CRM"],
        client=MagicMock(),
        candidate_repo=Repo(candidate()),
        participation_repo=Repo(participation()),
        queue_repo=Repo({"research_allowed": True}),
        snapshot_repo=Repo(None),
        facts_cache=Cache(),
        security_master=Master(),
        company_intelligence_service=ci,
        execute_providers=False,
        dry_run=True,
    )
    assert run.provider_calls == 0
    assert run.writes == 0
    assert run.items[0].status == STATUS_PLANNED
    assert run.items[0].reason == REASON_PLAN_ONLY
    assert ci.calls == 0


def test_research_false_blocks_before_provider():
    ci = Ci()
    run = run_us_security_intelligence_refresh(
        ["CRM"],
        client=MagicMock(),
        candidate_repo=Repo(candidate()),
        participation_repo=Repo(participation(allowed=False)),
        queue_repo=Repo({"research_allowed": False}),
        snapshot_repo=Repo(None),
        facts_cache=Cache(),
        security_master=Master(),
        company_intelligence_service=ci,
        execute_providers=True,
        dry_run=True,
    )
    assert run.provider_calls == 0
    assert run.items[0].reason == REASON_RESEARCH_NOT_ALLOWED
    assert ci.calls == 0


def test_aging_blocks_before_provider():
    ci = Ci()
    run = run_us_security_intelligence_refresh(
        ["CRM"],
        client=MagicMock(),
        candidate_repo=Repo(candidate(freshness="AGING")),
        participation_repo=Repo(participation()),
        queue_repo=Repo({"research_allowed": True}),
        snapshot_repo=Repo(None),
        facts_cache=Cache(),
        security_master=Master(),
        company_intelligence_service=ci,
        execute_providers=True,
        dry_run=True,
    )
    assert run.provider_calls == 0
    assert run.items[0].reason == REASON_FRESHNESS_NOT_FRESH
    assert ci.calls == 0


def test_old_sec_cache_blocks_before_provider():
    ci = Ci()
    run = run_us_security_intelligence_refresh(
        ["CRM"],
        client=MagicMock(),
        candidate_repo=Repo(candidate(period="2025-01-31")),
        participation_repo=Repo(participation()),
        queue_repo=Repo({"research_allowed": True}),
        snapshot_repo=Repo(None),
        facts_cache=Cache(period="2024-01-31"),
        security_master=Master(),
        company_intelligence_service=ci,
        execute_providers=True,
        dry_run=True,
    )
    assert run.provider_calls == 0
    assert run.items[0].reason == REASON_SEC_CACHE_PERIOD_OLD
    assert ci.calls == 0


def test_valid_execute_path_uses_canonical_publish_dry_run():
    ci = Ci()
    publish = SimpleNamespace(
        published=False,
        skipped_duplicate=False,
        blocked=False,
        dry_run=True,
        block_reason="",
        view=SimpleNamespace(
            overall_score=72.0,
            investment_state="ATTRACTIVE",
        ),
    )

    with patch(
        "services.us_security_intelligence_refresh.publish_canonical_security_intelligence",
        return_value=publish,
    ) as publish_mock:
        run = run_us_security_intelligence_refresh(
            ["CRM"],
            client=MagicMock(),
            candidate_repo=Repo(candidate()),
            participation_repo=Repo(participation()),
            queue_repo=Repo({"research_allowed": True}),
            snapshot_repo=Repo(None),
            facts_cache=Cache(),
            security_master=Master(),
            company_intelligence_service=ci,
            execute_providers=True,
            dry_run=True,
        )

    assert ci.calls == 1
    assert run.provider_calls == 2
    assert run.writes == 0
    assert run.items[0].status == STATUS_WOULD_PUBLISH
    publish_mock.assert_called_once()
    assert publish_mock.call_args.kwargs["dry_run"] is True


def test_persist_without_allow_live_is_rejected():
    with pytest.raises(ValueError, match="LIVE_PERSIST_UNSAFE"):
        run_us_security_intelligence_refresh(
            ["CRM"],
            client=MagicMock(),
            persist_si=True,
            allow_live=False,
        )
