"""NABI Danışman conversational UI. No providers, no writes."""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from services.nabi_adviser_answer import answer_nabi_adviser
from services.nabi_adviser_context import build_nabi_adviser_context
from services.nabi_adviser_contract import QUICK_QUESTIONS
from services.wealth_adviser_config import AdviserLlmConfig
from services.wealth_adviser_conversation import (
    clear_conversation_history,
    get_conversation_history,
    record_chat_exchange,
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
) -> None:
    import streamlit as st

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
    )
    summary = build_nabi_adviser_context("Bugün ne yapmalıyım?", **kwargs)
    rec = summary.current_recommendation

    st.subheader("NABI Danışman")
    st.warning(
        "Bu özellik yatırım tavsiyesi değildir ve otomatik işlem gerçekleştirmez."
    )
    st.caption(
        "Deterministik Wealth verileri kaynak gerçektir; AI bölümü yalnızca yorum katmanıdır."
    )
    st.markdown(f"**{rec.get('primary_action') or '—'}**")
    if rec.get("why_now"):
        st.caption(f"Neden: {rec['why_now']}")
    if rec.get("opportunity_line"):
        st.caption(rec["opportunity_line"])
    if rec.get("final_action"):
        st.caption(f"Kanonik yatırım aksiyonu: {rec['final_action']}")

    if not llm_config.is_usable:
        st.caption("Serbest sohbet açıklamaları için AI sohbeti etkin değil.")

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
        result = answer_nabi_adviser(
            submitted_question,
            llm_config=llm_config,
            **kwargs,
        )
        record_chat_exchange(
            session_state,
            chat_key,
            user_question=submitted_question,
            response=_to_response(result),
        )
        st.rerun()

    with st.expander("Teknik bağlam"):
        st.json(summary.to_dict())
