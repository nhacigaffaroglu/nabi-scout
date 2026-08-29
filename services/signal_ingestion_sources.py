"""Read-only inputs for the Signal ingestion stage. No writes."""

from __future__ import annotations

from typing import Any

from repositories.candidate_repository import CandidateRepository
from repositories.participation_assessment_repository import (
    ParticipationAssessmentRepository,
)
from repositories.wealth_asset_repository import WealthAssetRepository
from repositories.wealth_portfolio_admin_repository import WealthPortfolioAdminRepository
from repositories.wealth_position_repository import WealthPositionRepository


def load_signal_ingestion_inputs(client) -> dict[str, Any]:
    portfolios = WealthPortfolioAdminRepository(client).list_active_portfolios_for_snapshot()
    assets: list[dict[str, Any]] = []
    positions: list[dict[str, Any]] = []
    seen_users: set[str] = set()
    for portfolio in portfolios:
        user_id = str(portfolio.get("user_id") or "").strip()
        if not user_id or user_id in seen_users:
            continue
        seen_users.add(user_id)
        assets.extend(WealthAssetRepository(client).list_for_user(user_id))
        positions.extend(WealthPositionRepository(client).list_for_user(user_id))
    qty_by_asset: dict[str, float] = {}
    for row in positions:
        asset_id = str(row.get("asset_id") or "")
        try:
            qty_by_asset[asset_id] = qty_by_asset.get(asset_id, 0.0) + float(row.get("quantity") or 0)
        except (TypeError, ValueError):
            continue
    holdings = []
    for asset in assets:
        asset_id = str(asset.get("id") or "")
        holdings.append(
            {
                "symbol": asset.get("symbol"),
                "market": asset.get("market"),
                "asset_class": asset.get("asset_class"),
                "quantity": qty_by_asset.get(asset_id, 0.0),
            }
        )
    candidates = list(CandidateRepository(client).get_all(limit=5000) or [])
    snapshots = ParticipationAssessmentRepository(client).list_latest_by_symbol()
    return {
        "holdings": holdings,
        "candidates": candidates,
        "participation_by_symbol": snapshots,
    }
