from __future__ import annotations

from typing import Any, Dict, Optional

from repositories.portfolio_reference_limits_repository import PortfolioReferenceLimitsRepository
from services.portfolio_scenario_engine import DEFAULT_REFERENCE_LIMITS


class PortfolioReferenceLimitsService:
    def __init__(self, client, user_id: str) -> None:
        self.client = client
        self.user_id = user_id
        self.repo = PortfolioReferenceLimitsRepository(client)

    def get_limits(self, portfolio_id: str) -> Dict[str, Any]:
        row = self.repo.get_for_portfolio(self.user_id, portfolio_id)
        if row is None:
            return {"portfolio_id": portfolio_id, **DEFAULT_REFERENCE_LIMITS}
        return row

    def save_limits(self, portfolio_id: str, **fields: Optional[float]) -> Dict[str, Any]:
        payload = {
            key: fields.get(key, DEFAULT_REFERENCE_LIMITS.get(key))
            for key in DEFAULT_REFERENCE_LIMITS
        }
        return self.repo.upsert(self.user_id, portfolio_id, payload)
