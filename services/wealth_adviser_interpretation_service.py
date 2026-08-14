from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Sequence, Tuple

from services.wealth_adviser_config import AdviserLlmConfig, load_adviser_llm_config
from services.wealth_adviser_contract import (
    AdviserBrief,
    AdviserConversationTurn,
    AdviserResponse,
    AdviserValidationContext,
)
from services.wealth_adviser_llm_client import WealthAdviserLlmClient, WealthAdviserLlmError
from services.wealth_adviser_output_validator import (
    parse_structured_response,
    sanitize_failure_reasons,
    validate_adviser_response,
)
from services.wealth_adviser_prompt import build_llm_messages, sanitize_user_question


class WealthAdviserInterpretationService:
    """Bounded multi-turn LLM interpretation over deterministic adviser briefs."""

    def __init__(
        self,
        *,
        config: Optional[AdviserLlmConfig] = None,
        client: Optional[WealthAdviserLlmClient] = None,
    ) -> None:
        self.config = config or load_adviser_llm_config()
        self._client = client

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @property
    def client(self) -> WealthAdviserLlmClient:
        if self._client is None:
            self._client = WealthAdviserLlmClient.from_config(self.config)
        return self._client

    def build_deterministic_fallback(
        self,
        brief: AdviserBrief,
        *,
        reasons: Sequence[str] = (),
    ) -> AdviserResponse:
        limitations = list(brief.data_quality_notes)
        limitations.extend(
            finding.limitations
            for finding in brief.top_findings
            if finding.limitations
        )
        if brief.preference_summary:
            limitations.extend(brief.preference_summary)
        if reasons:
            limitations.extend(
                f"AI yorumu kullanılamadı: {reason}"
                for reason in sanitize_failure_reasons(reasons)
            )

        answer_parts = [brief.headline, "", brief.portfolio_summary]
        if brief.preference_summary:
            answer_parts.append("")
            answer_parts.append("Profil/hedef ilişki gözlemleri:")
            for line in brief.preference_summary:
                answer_parts.append(f"- {line}")
        if brief.top_findings:
            answer_parts.append("")
            answer_parts.append("Öne çıkan deterministik bulgular:")
            for finding in brief.top_findings:
                answer_parts.append(f"- {finding.title}: {finding.statement}")

        return AdviserResponse(
            answer="\n".join(part for part in answer_parts if part is not None),
            key_points=tuple(finding.statement for finding in brief.top_findings),
            referenced_finding_ids=tuple(finding.finding_id for finding in brief.top_findings),
            limitations=tuple(dict.fromkeys(limitations)),
            follow_up_questions=brief.questions_for_user,
            safety_flags=tuple(["deterministic_fallback", *sanitize_failure_reasons(reasons)]),
            model_name="deterministic",
            generated_at=self._now_iso(),
            grounded=False,
        )

    def interpret(
        self,
        brief: AdviserBrief,
        *,
        user_question: Optional[str] = None,
        conversation_history: Sequence[AdviserConversationTurn] = (),
    ) -> AdviserResponse:
        if not self.config.is_usable:
            return self.build_deterministic_fallback(
                brief,
                reasons=("llm_not_configured",),
            )

        question = sanitize_user_question(user_question)
        if not question:
            return self.build_deterministic_fallback(
                brief,
                reasons=("empty_question",),
            )

        validation_context = AdviserValidationContext.from_user_context(
            brief.context.user_context
        )
        try:
            raw = self.client.complete(
                build_llm_messages(
                    brief,
                    user_question=question,
                    conversation_history=conversation_history,
                )
            )
            parsed = parse_structured_response(
                raw,
                model_name=self.config.model,
                generated_at=self._now_iso(),
            )
        except WealthAdviserLlmError as exc:
            return self.build_deterministic_fallback(
                brief,
                reasons=(exc.error_class,),
            )
        except ValueError as exc:
            return self.build_deterministic_fallback(
                brief,
                reasons=(str(exc),),
            )

        validation = validate_adviser_response(
            parsed,
            brief.context,
            validation_context=validation_context,
        )
        if not validation.valid:
            return self.build_deterministic_fallback(
                brief,
                reasons=validation.reasons,
            )

        merged_limitations = tuple(
            dict.fromkeys([*parsed.limitations, *brief.data_quality_notes])
        )
        return AdviserResponse(
            answer=parsed.answer,
            key_points=parsed.key_points,
            referenced_finding_ids=parsed.referenced_finding_ids,
            limitations=merged_limitations,
            follow_up_questions=parsed.follow_up_questions or brief.questions_for_user,
            safety_flags=validation.safety_flags,
            model_name=self.config.model,
            generated_at=parsed.generated_at,
            grounded=True,
            acknowledged_preferences=parsed.acknowledged_preferences,
            relevant_goal_ids=parsed.relevant_goal_ids,
            preference_assessment_ids=parsed.preference_assessment_ids,
            options_to_consider=parsed.options_to_consider,
        )
