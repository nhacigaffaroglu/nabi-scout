from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from services.security_facts_service import SecurityFactsService
from services.security_intelligence_contract import (
    FACTS_VERSION,
    FRESHNESS_AGING,
    FRESHNESS_FRESH,
    FRESHNESS_UNKNOWN,
)


def test_facts_version_bumped_for_freshness_contract():
    assert FACTS_VERSION == "security_facts_8c.3"


def test_aging_candidate_is_not_promoted_to_fresh():
    facts = SecurityFactsService().build(
        "CRM",
        candidate={
            "symbol": "CRM",
            "freshness_status": "AGING",
            "financial_period_end": "2025-01-31",
            "revenue": 100.0,
        },
        allow_sec_cache_replay=False,
    )
    assert facts.freshness_status == FRESHNESS_AGING
    assert facts.stale is False


def test_unknown_candidate_is_not_promoted_to_fresh():
    facts = SecurityFactsService().build(
        "CRM",
        candidate={
            "symbol": "CRM",
            "freshness_status": "UNKNOWN",
            "financial_period_end": "2025-01-31",
            "revenue": 100.0,
        },
        allow_sec_cache_replay=False,
    )
    assert facts.freshness_status == FRESHNESS_UNKNOWN


def _cache(period):
    evidence = SimpleNamespace(cik="0001108524")
    cache = MagicMock()
    cache.get_latest.return_value = evidence
    cache.replay.return_value = {
        "financial_period_end": period,
        "financial_currency": "USD",
        "revenue": 100.0,
    }
    return cache


def test_older_sec_cache_is_not_replayed_over_newer_candidate_period():
    cache = _cache("2024-01-31")
    with patch(
        "repositories.sec_company_facts_cache.SecCompanyFactsCache",
        return_value=cache,
    ):
        result = SecurityFactsService().build_detailed(
            "CRM",
            candidate={
                "symbol": "CRM",
                "freshness_status": "FRESH",
                "financial_period_end": "2025-01-31",
                "revenue": 200.0,
            },
        )

    assert result.cache_replayed is False
    assert result.facts.revenue == 200.0
    assert result.facts.freshness_status == FRESHNESS_FRESH


def test_equal_period_sec_cache_remains_authoritative():
    cache = _cache("2025-01-31")
    with patch(
        "repositories.sec_company_facts_cache.SecCompanyFactsCache",
        return_value=cache,
    ):
        result = SecurityFactsService().build_detailed(
            "CRM",
            candidate={
                "symbol": "CRM",
                "freshness_status": "FRESH",
                "financial_period_end": "2025-01-31",
                "revenue": 200.0,
            },
        )

    assert result.cache_replayed is True
    assert result.facts.revenue == 100.0
    assert result.facts.freshness_status == FRESHNESS_FRESH
