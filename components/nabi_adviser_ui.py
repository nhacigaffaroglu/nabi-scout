"""NABI Danışman conversational UI. No providers, no writes."""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from services.nabi_adviser_answer import answer_nabi_adviser
from services.nabi_adviser_context import build_nabi_adviser_context
from services.nabi_adviser_contract import (
    LLM_DISABLED_COPY,
    QUICK_QUESTIONS,
    USER_SOURCE_COPY,
    present_action_label,
)
from services.nabi_recommendation import ACTION_REVIEW_GOAL_PLAN, NO_APPROVED_HALAL_OPPORTUNITY
from services.wealth_adviser_config import AdviserLlmConfig
from services.wealth_adviser_conversation import (
    clear_conversation_history,
    ensure_adviser_conversation_store,
    get_adviser_followup_state,
    get_conversation_history,
    record_chat_exchange,
    set_adviser_followup_state,
)
from services.wealth_adviser_contract import AdviserResponse


def _to_response(result) -> AdviserResponse:
    return AdviserResponse(
        answer=result.answer,
        key_points=(),
        referenced_finding_ids=(),
        limitations=result.limitations,
        follow_up_questions=QUICK_QUESTIONS,
        safety_flags=() if result.grounded else ("deterministic_canonical",),
        model_name="nabi-intelligence" if not result.used_llm else "nabi-intelligence+llm",
        generated_at="",
        grounded=result.grounded,
    )


def submit_nabi_adviser_turn(
    session_state,
    chat_key: str,
    question: str,
    **answer_kwargs,
):
    """Persist one Adviser turn on the live Streamlit conversation key."""
    ensure_adviser_conversation_store(session_state, chat_key)
    prior = get_adviser_followup_state(session_state, chat_key)
    result = answer_nabi_adviser(
        question,
        conversation_state=prior,
        **answer_kwargs,
    )
    record_chat_exchange(
        session_state,
        chat_key,
        user_question=question,
        response=_to_response(result),
    )
    set_adviser_followup_state(session_state, chat_key, result.followup_state)
    return result


def render_nabi_adviser(
    *,
    candidates: Sequence[Mapping[str, Any]],
    snapshots: Optional[Mapping[str, Mapping[str, Any]]],
    portfolio_view: Any,
    decision: Any,
    presented_actions: Any,
    allocation: Any,
    goal_dashboard: Any,
    new_money_brief: Any,
    llm_config: AdviserLlmConfig,
    session_state,
    chat_key: str,
    policy: Any = None,
    assets: Sequence[Any] = (),
    positions: Sequence[Any] = (),
    fund_snapshots: Optional[Mapping[str, Any]] = None,
) -> None:
    import streamlit as st

    session_state = getattr(st, "session_state", None) or session_state
    kwargs = dict(
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
        fund_snapshots=fund_snapshots,
    )
    ensure_adviser_conversation_store(session_state, chat_key)
    get_adviser_followup_state(session_state, chat_key)
    summary = build_nabi_adviser_context("Bugün ne yapmalıyım?", **kwargs)
    rec = summary.current_recommendation

    st.subheader("NABI Danışman")
    st.warning(
        "Bu özellik yatırım tavsiyesi değildir ve otomatik işlem gerçekleştirmez."
    )
    st.caption(USER_SOURCE_COPY)
    st.markdown(f"**{rec.get('primary_action') or '—'}**")
    if rec.get("why_now"):
        st.caption(rec["why_now"])
    opportunity_line = rec.get("opportunity_line") or ""
    if (
        opportunity_line
        and rec.get("action_code") != ACTION_REVIEW_GOAL_PLAN
        and opportunity_line != NO_APPROVED_HALAL_OPPORTUNITY
    ):
        st.caption(opportunity_line)
    final_label = present_action_label(rec.get("final_action"))
    if final_label and rec.get("action_code") != ACTION_REVIEW_GOAL_PLAN:
        st.caption(final_label)

    if not llm_config.is_usable:
        st.caption(LLM_DISABLED_COPY)

    conversation_history = get_conversation_history(session_state, chat_key)
    for turn in conversation_history:
        label = "Siz" if turn.role == "user" else "NABI Danışman"
        st.markdown(f"**{label}:** {turn.content}")

    clear_col, _ = st.columns([1, 3])
    if clear_col.button("Sohbeti temizle", key=f"clear_chat_{chat_key}"):
        clear_conversation_history(session_state, chat_key)
        st.rerun()

    quick_cols = st.columns(len(QUICK_QUESTIONS))
    submitted_question = None
    for column, prompt in zip(quick_cols, QUICK_QUESTIONS):
        if column.button(prompt, key=f"nabi_adviser_quick_{prompt}"):
            submitted_question = prompt

    with st.form("adviser_chat_form", clear_on_submit=True):
        adviser_question = st.text_input(
            "Sorunuz",
            placeholder="Örn: Bugün ne yapmalıyım?",
        )
        send_message = st.form_submit_button("Gönder")
    if send_message and adviser_question.strip():
        submitted_question = adviser_question.strip()

    if submitted_question:
        submit_nabi_adviser_turn(
            session_state,
            chat_key,
            submitted_question,
            llm_config=llm_config,
            **kwargs,
        )
        st.rerun()

    with st.expander("Teknik bağlam"):
        st.json(summary.to_dict())
