from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, Optional

from services.hybrid_exposure_allocation_policy import HybridPortfolioMode
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_UYGUN,
)
from services.portfolio_security_context_builder import (
    PortfolioSecuritySourceBundle,
    build_portfolio_security_context,
)
from services.portfolio_security_decision_engine import (
    evaluate_portfolio_security_decision,
)
from services.security_intelligence_contract import (
    AUTHORITY_SEC,
    FRESHNESS_FRESH,
    PERIOD_FY,
    FactProvenance,
    SecurityFacts,
    SecurityParticipationContext,
    SecurityValuationContext,
    SecurityValuationMetricContext,
)
from services.security_intelligence_publish import (
    publish_canonical_security_intelligence,
)
from services.security_intelligence_service import SecurityIntelligenceService
from services.security_intelligence_snapshot_service import latest_snapshot
from services.security_master_contract import INSTRUMENT_EQUITY


class Repo:
    def __init__(self) -> None:
        self.rows: Dict[tuple, Dict[str, Any]] = {}
        self.upserts = 0

    @staticmethod
    def _key(payload: Dict[str, Any]) -> tuple:
        return (
            payload["symbol"],
            payload["as_of_key"],
            payload["facts_version"],
            payload["engine_version"],
        )

    def upsert(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.upserts += 1
        stored = dict(payload)
        stored.setdefault("id", f"si-{self.upserts}")
        self.rows[self._key(stored)] = stored
        return stored

    def get_by_identity(
        self,
        symbol: str,
        *,
        as_of_key: str,
        facts_version: str,
        engine_version: str,
    ) -> Optional[Dict[str, Any]]:
        return self.rows.get(
            (
                symbol,
                as_of_key,
                facts_version,
                engine_version,
            )
        )

    def get_latest(self, symbol: str) -> Optional[Dict[str, Any]]:
        rows = [
            row
            for row in self.rows.values()
            if row.get("symbol") == symbol
        ]
        if not rows:
            return None
        rows.sort(
            key=lambda row: (
                str(row.get("as_of") or ""),
                str(row.get("updated_at") or ""),
            ),
            reverse=True,
        )
        return rows[0]


def participation() -> SecurityParticipationContext:
    return SecurityParticipationContext(
        status=PARTICIPATION_STATUS_UYGUN,
        research_allowed=True,
    )


def strong_facts(
    *,
    as_of: str = "2026-09-20",
    valuation_context=None,
    provenance=(),
) -> SecurityFacts:
    return SecurityFacts(
        symbol="CRM",
        exchange="NASDAQ",
        currency="USD",
        instrument_type=INSTRUMENT_EQUITY,
        as_of=as_of,
        freshness_status=FRESHNESS_FRESH,
        authority_status=AUTHORITY_SEC,
        period_compatibility=PERIOD_FY,
        period_kind=PERIOD_FY,
        completeness_pct=95.0,
        revenue=1000.0,
        operating_income=250.0,
        net_income=200.0,
        free_cash_flow=220.0,
        total_assets=1500.0,
        total_debt=150.0,
        cash=300.0,
        equity=900.0,
        roic=25.0,
        roe=22.0,
        roa=12.0,
        revenue_cagr_3y=16.0,
        eps_cagr_3y=18.0,
        fcf_cagr_3y=17.0,
        gross_margin=75.0,
        operating_margin=25.0,
        net_margin=20.0,
        fcf_margin=22.0,
        pe=18.0,
        price_to_sales=4.0,
        price_to_book=4.0,
        debt_to_equity=0.2,
        net_debt_to_fcf=0.1,
        current_ratio=1.8,
        interest_coverage=25.0,
        price=250.0,
        market_cap=25000.0,
        valuation_context=valuation_context,
        provenance=tuple(provenance),
    )


def weak_facts(*, as_of: str = "2026-09-21") -> SecurityFacts:
    return SecurityFacts(
        symbol="CRM",
        exchange="NASDAQ",
        currency="USD",
        instrument_type=INSTRUMENT_EQUITY,
        as_of=as_of,
        freshness_status=FRESHNESS_FRESH,
        authority_status=AUTHORITY_SEC,
        period_compatibility=PERIOD_FY,
        period_kind=PERIOD_FY,
        completeness_pct=95.0,
        revenue=1000.0,
        operating_income=5.0,
        net_income=-50.0,
        free_cash_flow=-20.0,
        total_assets=1500.0,
        total_debt=1200.0,
        cash=20.0,
        equity=200.0,
        roic=-8.0,
        roe=-12.0,
        roa=-4.0,
        revenue_cagr_3y=-12.0,
        eps_cagr_3y=-18.0,
        fcf_cagr_3y=-20.0,
        gross_margin=20.0,
        operating_margin=0.5,
        net_margin=-5.0,
        fcf_margin=-2.0,
        pe=80.0,
        price_to_sales=15.0,
        price_to_book=20.0,
        debt_to_equity=6.0,
        net_debt_to_fcf=20.0,
        current_ratio=0.5,
        interest_coverage=0.5,
        price=250.0,
        market_cap=25000.0,
    )


def context_from_snapshot(snapshot):
    return build_portfolio_security_context(
        "CRM",
        PortfolioSecuritySourceBundle(
            snapshot={
                "participation_status": PARTICIPATION_STATUS_UYGUN,
                "research_allowed": True,
            },
            queue_row={"research_allowed": True},
            si_snapshot=snapshot,
            candidate={
                "symbol": "CRM",
                "research_status": "TAMAMLANDI",
            },
            instrument_type=INSTRUMENT_EQUITY,
            market="US",
            quantity=10.0,
            market_value=2500.0,
            portfolio_weight=5.0,
            economic_exposure_status=HybridPortfolioMode.STRICT.value,
        ),
    )


def test_snapshot_persists_stable_facts_and_valuation_provenance():
    metric = SecurityValuationMetricContext(
        code="pe",
        current_value=18.0,
        fundamental_period_end="2025-01-31",
        market_data_as_of="2026-09-20",
        source_provider="fmp",
        data_family="SEC_HYBRID_VALUATION",
    )
    valuation = SecurityValuationContext(
        metrics=(metric,),
        as_of="2026-09-20T12:00:00+00:00",
    )
    sec_trace = FactProvenance(
        field="revenue",
        value=1000.0,
        source="sec_company_facts_cache",
        source_as_of="2025-01-31",
        retrieved_at="2026-09-19T10:00:00+00:00",
        period_kind=PERIOD_FY,
        authority=AUTHORITY_SEC,
    )

    repo = Repo()
    facts = strong_facts(
        valuation_context=valuation,
        provenance=(sec_trace,),
    )

    first = publish_canonical_security_intelligence(
        facts,
        participation(),
        repo,
    )
    second = publish_canonical_security_intelligence(
        facts,
        participation(),
        repo,
    )

    assert first.published is True
    assert second.skipped_duplicate is True
    assert repo.upserts == 1

    row = repo.get_latest("CRM")
    provenance = row["data_quality"]["provenance"]

    assert provenance["facts_as_of"] == "2026-09-20"
    assert provenance["facts_freshness_status"] == FRESHNESS_FRESH
    assert provenance["facts_authority_status"] == AUTHORITY_SEC
    assert provenance["facts_period_compatibility"] == PERIOD_FY
    assert (
        provenance["sec_evidence_retrieved_at"]
        == "2026-09-19T10:00:00+00:00"
    )
    assert (
        provenance["valuation_fundamental_period_end"]
        == "2025-01-31"
    )
    assert provenance["valuation_market_data_as_of"] == "2026-09-20"
    assert provenance["valuation_source_providers"] == ["fmp"]
    assert provenance["valuation_data_families"] == [
        "SEC_HYBRID_VALUATION"
    ]


def test_live_si_cannot_change_8e_until_canonical_publish():
    repo = Repo()

    baseline_publish = publish_canonical_security_intelligence(
        strong_facts(),
        participation(),
        repo,
    )
    assert baseline_publish.published is True

    persisted_before = latest_snapshot(repo, "CRM")
    assert persisted_before is not None

    context_before = context_from_snapshot(persisted_before)
    decision_before = evaluate_portfolio_security_decision(context_before)

    changed = weak_facts()

    # Live research view changes, but it is not decision authority.
    live_changed = SecurityIntelligenceService().evaluate(
        changed,
        participation(),
        previous=persisted_before,
    )

    assert live_changed.overall_score != persisted_before.overall_score

    persisted_without_publish = latest_snapshot(repo, "CRM")
    context_without_publish = context_from_snapshot(
        persisted_without_publish
    )
    decision_without_publish = evaluate_portfolio_security_decision(
        context_without_publish
    )

    # 8E is unchanged because persisted SI authority is unchanged.
    assert (
        context_without_publish.si_score
        == context_before.si_score
    )
    assert (
        context_without_publish.si_state
        == context_before.si_state
    )
    assert (
        decision_without_publish.decision
        == decision_before.decision
    )

    changed_publish = publish_canonical_security_intelligence(
        changed,
        participation(),
        repo,
        previous=persisted_before,
    )
    assert changed_publish.published is True

    persisted_after = latest_snapshot(repo, "CRM")
    assert persisted_after is not None

    context_after = context_from_snapshot(persisted_after)

    # Only now does the new SI become 8E authority.
    assert context_after.si_score == changed_publish.view.overall_score
    assert context_after.si_state == changed_publish.view.investment_state
    assert context_after.si_score != context_before.si_score
