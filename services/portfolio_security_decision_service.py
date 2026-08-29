"""Read-only 8E surface entry. Assembles persisted context and evaluates.

Does not rebuild SI, call the facade, size New Money, or write anything.
"""

from __future__ import annotations

from typing import Any, Optional

from repositories.candidate_repository import CandidateRepository
from repositories.participation_assessment_repository import (
    ParticipationAssessmentRepository,
)
from repositories.security_intelligence_snapshot_repository import (
    SecurityIntelligenceSnapshotRepository,
)
from repositories.signal_intelligence_repository import SignalIntelligenceRepository
from repositories.universe_expansion_repository import UniverseExpansionRepository
from repositories.wealth_portfolio_repository import WealthPortfolioRepository
from services.candidate_identity import select_canonical_candidate
from services.candidate_price_service import CandidatePriceService
from services.fund_holdings_service import FundHoldingsService
from services.portfolio_intelligence_helpers import iter_all_position_rows
from services.portfolio_intelligence_service import PortfolioIntelligenceService
from services.portfolio_security_context_builder import (
    PortfolioSecuritySourceBundle,
    aggregate_holding,
    build_portfolio_security_context,
    identity_from_security_master,
    load_persisted_si_snapshot,
    load_signal_context,
    resolve_economic_exposure_status,
)
from services.portfolio_security_decision_contract import PortfolioSecurityDecision
from services.portfolio_security_decision_engine import evaluate_portfolio_security_decision
from services.security_master_service import production_security_master
from services.signal_intelligence_service import SignalIntelligenceService
from services.wealth_core_service import WealthCoreService
from services.wealth_contract import normalize_symbol

LOOKTHROUGH_FUNDS = ("SPUS", "SPSK", "SPRE", "SPWO")


def fail_closed_portfolio_security_decision(symbol: str) -> PortfolioSecurityDecision:
    return evaluate_portfolio_security_decision(
        build_portfolio_security_context(symbol, PortfolioSecuritySourceBundle())
    )


def evaluate_portfolio_security_for_symbol(
    client: Any,
    symbol: str,
    *,
    user_id: Optional[str] = None,
) -> PortfolioSecurityDecision:
    """Canonical 8E path: persisted builder inputs → decision engine."""
    normalized = normalize_symbol(symbol)
    if not normalized or client is None:
        return fail_closed_portfolio_security_decision(normalized or str(symbol or ""))
    try:
        return _evaluate_loaded(client, normalized, user_id=user_id)
    except Exception:
        return fail_closed_portfolio_security_decision(normalized)


def _evaluate_loaded(
    client: Any,
    symbol: str,
    *,
    user_id: Optional[str],
) -> PortfolioSecurityDecision:
    resolution = None
    try:
        resolution = production_security_master(client).resolve_security(symbol)
    except Exception:
        resolution = None
    instrument_type, sm_market = identity_from_security_master(resolution)
    candidate = None
    try:
        candidate = select_canonical_candidate(
            CandidateRepository(client).list_by_symbol(symbol)
        )
    except Exception:
        candidate = None
    snapshot = None
    queue_row = None
    try:
        loaded = ParticipationAssessmentRepository(client).get_latest(symbol)
        snapshot = loaded if isinstance(loaded, dict) else None
    except Exception:
        snapshot = None
    try:
        loaded = UniverseExpansionRepository(client).get_by_symbol(symbol)
        queue_row = loaded if isinstance(loaded, dict) else None
    except Exception:
        queue_row = None
    si_snapshot = None
    try:
        si_snapshot = load_persisted_si_snapshot(
            SecurityIntelligenceSnapshotRepository(client), symbol
        )
    except Exception:
        si_snapshot = None
    signal_context = load_signal_context(
        SignalIntelligenceService(SignalIntelligenceRepository(client)),
        symbol,
    )
    qty = value = weight = holding_market = None
    view = _portfolio_view(client, user_id or _default_user_id(client))
    if view is not None:
        qty, value, weight, holding_market = aggregate_holding(
            iter_all_position_rows(view), symbol
        )
    is_holding = qty is not None and qty > 0
    bundle = PortfolioSecuritySourceBundle(
        snapshot=snapshot,
        queue_row=queue_row,
        si_snapshot=si_snapshot,
        signal_context=signal_context,
        candidate=candidate,
        instrument_type=instrument_type,
        market=holding_market or sm_market,
        quantity=qty,
        market_value=value,
        portfolio_weight=weight,
        economic_exposure_status=resolve_economic_exposure_status(),
        lookthrough_only=symbol in _lookthrough_symbols(client)
        and not is_holding
        and candidate is None,
        as_of=None if si_snapshot is None else si_snapshot.as_of,
    )
    return evaluate_portfolio_security_decision(
        build_portfolio_security_context(symbol, bundle)
    )


def _default_user_id(client: Any) -> Optional[str]:
    try:
        rows = (
            client.table("wealth_portfolios")
            .select("user_id")
            .eq("is_default", True)
            .limit(1)
            .execute()
            .data
            or []
        )
        if rows and isinstance(rows[0], dict) and rows[0].get("user_id"):
            return str(rows[0]["user_id"])
    except Exception:
        return None
    return None


def _portfolio_view(client: Any, user_id: Optional[str]):
    if not user_id:
        return None
    try:
        portfolio = WealthPortfolioRepository(client).get_default_for_user(user_id)
        if not portfolio:
            return None
        return PortfolioIntelligenceService(
            WealthCoreService(client, user_id),
            CandidatePriceService(client),
        ).build_view(portfolio, enrich_nabi=False)
    except Exception:
        return None


def _lookthrough_symbols(client: Any) -> set[str]:
    found: set[str] = set()
    try:
        service = FundHoldingsService(client)
    except Exception:
        return found
    for fund in LOOKTHROUGH_FUNDS:
        try:
            snapshot = service.get_snapshot(fund)
        except Exception:
            continue
        holdings = getattr(snapshot, "holdings", None) if snapshot is not None else None
        rows = holdings if holdings is not None else []
        for row in rows:
            symbol = str(
                getattr(row, "underlying_symbol", None)
                or (row.get("underlying_symbol") if isinstance(row, dict) else "")
                or ""
            ).strip().upper()
            if symbol:
                found.add(symbol)
    return found
