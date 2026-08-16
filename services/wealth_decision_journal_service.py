from __future__ import annotations

from typing import Any, Dict, List, Optional

from repositories.wealth_decision_journal_repository import (
    JOURNAL_ACTION_CONTEXTS,
    WealthDecisionJournalRepository,
)
from services.wealth_contract import WealthValidationError


class WealthDecisionJournalService:
    def __init__(self, client, user_id: str) -> None:
        self.client = client
        self.user_id = user_id
        self.repo = WealthDecisionJournalRepository(client)

    def list_entries(
        self,
        *,
        symbol: Optional[str] = None,
        portfolio_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        return self.repo.list_for_user(
            self.user_id,
            symbol=symbol,
            portfolio_id=portfolio_id,
            limit=limit,
        )

    def create_entry(
        self,
        *,
        symbol: str,
        action_context: str,
        portfolio_id: Optional[str] = None,
        account_id: Optional[str] = None,
        asset_id: Optional[str] = None,
        thesis: Optional[str] = None,
        key_evidence: Optional[str] = None,
        key_risks: Optional[str] = None,
        invalidation_conditions: Optional[str] = None,
        expected_horizon: Optional[str] = None,
        tags: Optional[List[str]] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        sym = str(symbol or "").strip().upper()
        if not sym:
            raise WealthValidationError("Sembol gerekli.")
        context = str(action_context or "").strip().lower()
        if context not in JOURNAL_ACTION_CONTEXTS:
            raise WealthValidationError(f"Geçersiz işlem bağlamı: {action_context}")

        return self.repo.create(
            {
                "user_id": self.user_id,
                "portfolio_id": portfolio_id,
                "account_id": account_id,
                "asset_id": asset_id,
                "symbol": sym,
                "action_context": context,
                "thesis": thesis.strip() if thesis else None,
                "key_evidence": key_evidence.strip() if key_evidence else None,
                "key_risks": key_risks.strip() if key_risks else None,
                "invalidation_conditions": (
                    invalidation_conditions.strip() if invalidation_conditions else None
                ),
                "expected_horizon": expected_horizon.strip() if expected_horizon else None,
                "tags": tags or [],
                "notes": notes.strip() if notes else None,
            }
        )

    def update_entry(
        self,
        entry_id: str,
        *,
        thesis: Optional[str] = None,
        key_evidence: Optional[str] = None,
        key_risks: Optional[str] = None,
        invalidation_conditions: Optional[str] = None,
        expected_horizon: Optional[str] = None,
        tags: Optional[List[str]] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        existing = self.repo.get_by_id(self.user_id, entry_id)
        if existing is None:
            raise WealthValidationError("Karar günlüğü kaydı bulunamadı.")
        updates: Dict[str, Any] = {}
        if thesis is not None:
            updates["thesis"] = thesis.strip() or None
        if key_evidence is not None:
            updates["key_evidence"] = key_evidence.strip() or None
        if key_risks is not None:
            updates["key_risks"] = key_risks.strip() or None
        if invalidation_conditions is not None:
            updates["invalidation_conditions"] = invalidation_conditions.strip() or None
        if expected_horizon is not None:
            updates["expected_horizon"] = expected_horizon.strip() or None
        if tags is not None:
            updates["tags"] = tags
        if notes is not None:
            updates["notes"] = notes.strip() or None
        if not updates:
            return existing
        return self.repo.update(self.user_id, entry_id, updates)
