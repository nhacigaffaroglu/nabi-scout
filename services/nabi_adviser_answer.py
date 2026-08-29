"""Answer NABI Danışman questions. LLM explains only; canonical services decide."""

from __future__ import annotations

import json
from typing import Any, Mapping, Optional, Sequence

from services.nabi_adviser_contract import (
    NabiAdviserAnswer,
    NabiAdviserContext,
    present_user_text,
)
from services.nabi_adviser_context import build_followup_state, build_nabi_adviser_context
from services.nabi_adviser_intent import parse_adviser_question
from services.nabi_decision_contract import (
    ACTION_CONSIDER_NEW_POSITION,
    ACTION_CONSIDER_TOP_UP,
)
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.wealth_adviser_config import AdviserLlmConfig, load_adviser_llm_config
from services.wealth_adviser_llm_client import WealthAdviserLlmClient, WealthAdviserLlmError
from services.wealth_adviser_output_validator import (
    BUY_SELL_PATTERNS,
    SPECIFIC_SECURITY_REC_PATTERNS,
)
from services.wealth_new_money_allocation import AllocationPlan

_SYSTEM = """You are NABI Danışman. You only explain the supplied canonical context in Turkish.

Rules:
- Do not decide Participation, NABI Score, ADAY class, timing, portfolio fit, Goal, or New Money.
- Do not invent missing evidence, catalysts, valuation, or price targets.
- Do not issue BUY/SELL/al/sat orders or quantities.
- If a field is missing, say veri yetersiz.
- Keep the canonical primary action unchanged.
- Return JSON: {"answer": "..."}.
"""


def _contains_trade_command(text: str) -> bool:
    blob = str(text or "")
    for pattern in (*BUY_SELL_PATTERNS, *SPECIFIC_SECURITY_REC_PATTERNS):
        if pattern.search(blob):
            return True
    return False


def _violates_halal_firewall(context: NabiAdviserContext, text: str) -> bool:
    status = str(context.participation_status or "").strip()
    if not status or status == PARTICIPATION_STATUS_UYGUN:
        return False
    blob = str(text or "")
    if ACTION_CONSIDER_NEW_POSITION in blob or ACTION_CONSIDER_TOP_UP in blob:
        return True
    return False


def _llm_messages(context: NabiAdviserContext) -> list[dict[str, str]]:
    payload = json.dumps(context.to_llm_payload(), ensure_ascii=False, default=str)
    return [
        {"role": "system", "content": _SYSTEM},
        {
            "role": "user",
            "content": (
                "Kullanıcı sorusu:\n"
                f"{context.question}\n\n"
                "Kanonik bağlam:\n"
                f"{payload}"
            ),
        },
    ]


def _parse_llm_answer(raw: str) -> Optional[str]:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except ValueError:
        return text
    if isinstance(payload, dict):
        answer = str(payload.get("answer") or "").strip()
        return answer or None
    return text


def answer_nabi_adviser(
    question: str,
    *,
    candidates: Sequence[Mapping[str, Any]] = (),
    snapshots: Optional[Mapping[str, Mapping[str, Any]]] = None,
    portfolio_view: Any = None,
    decision: Any = None,
    presented_actions: Any = None,
    allocation: Optional[AllocationPlan] = None,
    goal_dashboard: Any = None,
    new_money_brief: Any = None,
    policy: Any = None,
    assets: Sequence[Any] = (),
    positions: Sequence[Any] = (),
    theses: Optional[Mapping[str, Any]] = None,
    llm_config: Optional[AdviserLlmConfig] = None,
    llm_client: Optional[WealthAdviserLlmClient] = None,
    conversation_state: Optional[Mapping[str, Any]] = None,
    fund_snapshots: Optional[Mapping[str, Any]] = None,
    security_master=None,
) -> NabiAdviserAnswer:
    context = build_nabi_adviser_context(
        question,
        candidates=candidates,
        snapshots=snapshots,
        portfolio_view=portfolio_view,
        decision=decision,
        presented_actions=presented_actions,
        allocation=allocation,
        goal_dashboard=goal_dashboard,
        new_money_brief=new_money_brief,
        policy=policy,
        assets=assets,
        positions=positions,
        theses=theses,
        conversation_state=conversation_state,
        fund_snapshots=fund_snapshots,
        security_master=security_master,
    )
    parsed = parse_adviser_question(question, conversation_state)
    followup_state = build_followup_state(
        parsed,
        context.current_recommendation,
        context.canonical_answer,
        context.new_money_context,
        conversation_state,
    )
    action = str(context.current_recommendation.get("action_code") or "")
    config = llm_config or load_adviser_llm_config()
    if not config.is_usable:
        return NabiAdviserAnswer(
            answer=present_user_text(context.canonical_answer),
            intent=context.intent,
            focus_symbol=context.focus_symbol,
            canonical_action=action,
            used_llm=False,
            llm_calls=0,
            limitations=context.limitations,
            grounded=False,
            canonical_answer=context.canonical_answer,
            followup_state=followup_state,
        )

    client = llm_client or WealthAdviserLlmClient.from_config(config)
    try:
        raw = client.complete(_llm_messages(context))
        explained = _parse_llm_answer(raw)
    except WealthAdviserLlmError:
        explained = None
    llm_calls = 1
    if (
        not explained
        or _contains_trade_command(explained)
        or _violates_halal_firewall(context, explained)
    ):
        return NabiAdviserAnswer(
            answer=present_user_text(context.canonical_answer),
            intent=context.intent,
            focus_symbol=context.focus_symbol,
            canonical_action=action,
            used_llm=False,
            llm_calls=llm_calls,
            limitations=tuple(
                dict.fromkeys((*context.limitations, "llm_output_constrained"))
            ),
            grounded=False,
            canonical_answer=context.canonical_answer,
            followup_state=followup_state,
        )
    return NabiAdviserAnswer(
        answer=present_user_text(explained),
        intent=context.intent,
        focus_symbol=context.focus_symbol,
        canonical_action=action,
        used_llm=True,
        llm_calls=llm_calls,
        limitations=context.limitations,
        grounded=True,
        canonical_answer=context.canonical_answer,
        followup_state=followup_state,
    )


def present_adviser_summary(context: NabiAdviserContext) -> tuple[str, str, str]:
    rec = context.current_recommendation
    return (
        str(rec.get("primary_action") or ""),
        str(rec.get("why_now") or ""),
        present_user_text(str(rec.get("final_action") or "")),
    )
