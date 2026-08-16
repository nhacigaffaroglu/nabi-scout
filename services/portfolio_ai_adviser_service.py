from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from repositories.portfolio_ai_adviser_repository import PortfolioAIAdviserRepository
from services.daily_portfolio_brief_service import DailyPortfolioBriefContext
from services.portfolio_ai_adviser_contract import (
    PortfolioAIAdviserMetadata,
    PortfolioAIAdviserResponse,
)
from services.portfolio_ai_adviser_display import polish_portfolio_ai_response
from services.portfolio_ai_adviser_persistence_service import (
    save_portfolio_ai_snapshot,
    view_from_row,
)
from services.portfolio_ai_adviser_prompt import (
    build_portfolio_ai_input_payload,
    build_portfolio_ai_messages,
    compute_portfolio_ai_semantic_identity,
)
from services.portfolio_ai_adviser_validator import validate_portfolio_ai_response
from services.portfolio_research_context import PortfolioResearchContext
from services.wealth_adviser_config import AdviserLlmConfig, load_adviser_llm_config
from services.wealth_adviser_llm_client import WealthAdviserLlmClient, WealthAdviserLlmError


class PortfolioAIAdviserService:
    def __init__(self, client, user_id: str, *, config: Optional[AdviserLlmConfig] = None) -> None:
        self.client = client
        self.user_id = user_id
        self.config = config or load_adviser_llm_config()
        self.repo = PortfolioAIAdviserRepository(client)
        self.llm = WealthAdviserLlmClient(self.config) if self.config.is_usable else None

    def build_input_payload(
        self,
        *,
        portfolio_context: PortfolioResearchContext,
        brief: DailyPortfolioBriefContext,
        selected_events: Tuple[Dict[str, Any], ...] = (),
    ) -> Dict[str, Any]:
        return build_portfolio_ai_input_payload(
            portfolio_context=portfolio_context,
            brief=brief,
            selected_events=selected_events,
        )

    def compute_semantic_identity(self, payload: Dict[str, Any]) -> str:
        return compute_portfolio_ai_semantic_identity(payload)

    def fetch_persisted(
        self,
        *,
        portfolio_id: str,
        semantic_identity: str,
    ) -> Optional[PortfolioAIAdviserResponse]:
        row = self.repo.get_exact(self.user_id, portfolio_id, semantic_identity)
        if row is None or row.get("status") != "AVAILABLE":
            return None
        return view_from_row(row)

    def generate(
        self,
        *,
        portfolio_id: str,
        portfolio_context: PortfolioResearchContext,
        brief: DailyPortfolioBriefContext,
        selected_events: Tuple[Dict[str, Any], ...] = (),
        force_refresh: bool = False,
        cached_view: Optional[PortfolioAIAdviserResponse] = None,
        cached_identity: Optional[str] = None,
    ) -> PortfolioAIAdviserResponse:
        payload = self.build_input_payload(
            portfolio_context=portfolio_context,
            brief=brief,
            selected_events=selected_events,
        )
        identity = self.compute_semantic_identity(payload)

        if (
            not force_refresh
            and cached_view is not None
            and cached_identity == identity
            and cached_view.status == "AVAILABLE"
        ):
            return PortfolioAIAdviserResponse(
                portfolio_id=cached_view.portfolio_id,
                status=cached_view.status,
                evidence_level=cached_view.evidence_level,
                executive_summary=cached_view.executive_summary,
                what_changed=cached_view.what_changed,
                portfolio_implications=cached_view.portfolio_implications,
                thesis_watch=cached_view.thesis_watch,
                participation_watch=cached_view.participation_watch,
                research_gaps=cached_view.research_gaps,
                questions_to_review=cached_view.questions_to_review,
                limitations=cached_view.limitations,
                evidence_references=cached_view.evidence_references,
                generated_at=cached_view.generated_at,
                model_provider=cached_view.model_provider,
                model_name=cached_view.model_name,
                source_context_version=cached_view.source_context_version,
                user_message=cached_view.user_message,
                metadata=PortfolioAIAdviserMetadata(
                    context_semantic_identity=identity,
                    validation_outcome="cache_hit",
                    llm_call_count=0,
                    cache_hit=True,
                ),
            )

        persisted = self.fetch_persisted(portfolio_id=portfolio_id, semantic_identity=identity)
        if not force_refresh and persisted is not None:
            return PortfolioAIAdviserResponse(
                portfolio_id=persisted.portfolio_id,
                status=persisted.status,
                evidence_level=persisted.evidence_level,
                executive_summary=persisted.executive_summary,
                what_changed=persisted.what_changed,
                portfolio_implications=persisted.portfolio_implications,
                thesis_watch=persisted.thesis_watch,
                participation_watch=persisted.participation_watch,
                research_gaps=persisted.research_gaps,
                questions_to_review=persisted.questions_to_review,
                limitations=persisted.limitations,
                evidence_references=persisted.evidence_references,
                generated_at=persisted.generated_at,
                model_provider=persisted.model_provider,
                model_name=persisted.model_name,
                source_context_version=persisted.source_context_version,
                user_message=persisted.user_message,
                metadata=PortfolioAIAdviserMetadata(
                    context_semantic_identity=identity,
                    validation_outcome="persisted",
                    llm_call_count=0,
                    cache_hit=False,
                ),
            )

        if self.llm is None:
            return PortfolioAIAdviserResponse.unavailable(
                portfolio_id=portfolio_id,
                message="AI portföy değerlendirmesi şu anda etkin değil.",
            )

        started = time.perf_counter()
        try:
            raw = self.llm.complete(build_portfolio_ai_messages(payload))
        except WealthAdviserLlmError:
            return PortfolioAIAdviserResponse.unavailable(
                portfolio_id=portfolio_id,
                message="AI portföy değerlendirmesi üretilemedi.",
            )
        latency_ms = int((time.perf_counter() - started) * 1000)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return PortfolioAIAdviserResponse.validation_failed(
                portfolio_id=portfolio_id,
                message="AI yanıtı JSON olarak ayrıştırılamadı.",
            )

        validation = validate_portfolio_ai_response(
            portfolio_id=portfolio_id,
            raw_payload=parsed,
            context_payload=payload,
        )
        if not validation.ok:
            failed = validation.response
            return PortfolioAIAdviserResponse(
                portfolio_id=failed.portfolio_id,
                status=failed.status,
                evidence_level=failed.evidence_level,
                user_message=failed.user_message,
                limitations=failed.limitations,
                metadata=PortfolioAIAdviserMetadata(
                    context_semantic_identity=identity,
                    validation_outcome=f"validation_failed:{','.join(validation.issues)}",
                    llm_call_count=1,
                    latency_ms=latency_ms,
                ),
            )

        polished = polish_portfolio_ai_response(validation.response)
        generated_at = datetime.now(timezone.utc).isoformat()
        available = PortfolioAIAdviserResponse(
            portfolio_id=portfolio_id,
            status="AVAILABLE",
            evidence_level=polished.evidence_level,
            executive_summary=polished.executive_summary,
            what_changed=polished.what_changed,
            portfolio_implications=polished.portfolio_implications,
            thesis_watch=polished.thesis_watch,
            participation_watch=polished.participation_watch,
            research_gaps=polished.research_gaps,
            questions_to_review=polished.questions_to_review,
            limitations=polished.limitations,
            evidence_references=polished.evidence_references,
            generated_at=generated_at,
            model_provider=self.config.provider,
            model_name=self.config.model,
            source_context_version=polished.source_context_version,
            metadata=PortfolioAIAdviserMetadata(
                context_semantic_identity=identity,
                validation_outcome="available",
                llm_call_count=1,
                latency_ms=latency_ms,
            ),
        )
        save_portfolio_ai_snapshot(
            self.repo,
            available,
            user_id=self.user_id,
            portfolio_id=portfolio_id,
            semantic_identity=identity,
        )
        return available
