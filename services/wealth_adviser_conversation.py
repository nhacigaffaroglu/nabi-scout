from __future__ import annotations

from typing import Any, List, Mapping, Optional, Sequence

from services.wealth_adviser_contract import (
    MAX_CONVERSATION_TURNS,
    AdviserConversationTurn,
    AdviserResponse,
)

CONVERSATION_TURNS_FIELD = "turns"
CONVERSATION_FOLLOWUP_FIELD = "nabi_followup"


def _sanitize_turn_content(role: str, content: str) -> str:
    if role == "user":
        from services.wealth_adviser_prompt import sanitize_user_question

        return sanitize_user_question(content)
    return content.strip()


def conversation_session_key(user_id: str, portfolio_id: str) -> str:
    return f"adviser_chat_{user_id}_{portfolio_id}"


def conversation_followup_key(chat_key: str) -> str:
    return f"{chat_key}_nabi_followup"


def _conversation_store(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict) and isinstance(raw.get(CONVERSATION_TURNS_FIELD), list):
        followup = raw.get(CONVERSATION_FOLLOWUP_FIELD)
        return {
            CONVERSATION_TURNS_FIELD: list(raw.get(CONVERSATION_TURNS_FIELD) or []),
            CONVERSATION_FOLLOWUP_FIELD: dict(followup) if isinstance(followup, dict) else {},
        }
    if isinstance(raw, list):
        return {
            CONVERSATION_TURNS_FIELD: list(raw),
            CONVERSATION_FOLLOWUP_FIELD: {},
        }
    return {CONVERSATION_TURNS_FIELD: [], CONVERSATION_FOLLOWUP_FIELD: {}}


def ensure_adviser_conversation_store(session_state, key: str) -> dict[str, Any]:
    raw = session_state.get(key) if session_state is not None else None
    store = _conversation_store(raw)
    leftover_key = conversation_followup_key(key)
    leftover = session_state.get(leftover_key) if session_state is not None else None
    if isinstance(leftover, dict) and leftover and not store.get(CONVERSATION_FOLLOWUP_FIELD):
        store[CONVERSATION_FOLLOWUP_FIELD] = dict(leftover)
    if session_state is not None:
        session_state.pop(leftover_key, None)
        session_state[key] = store
    return store


def get_adviser_followup_state(session_state, key: str) -> dict[str, Any]:
    if session_state is None:
        return {}
    store = ensure_adviser_conversation_store(session_state, key)
    return dict(store.get(CONVERSATION_FOLLOWUP_FIELD) or {})


def set_adviser_followup_state(
    session_state,
    key: str,
    followup: Optional[Mapping[str, Any]] = None,
) -> None:
    store = _conversation_store(session_state.get(key))
    store[CONVERSATION_FOLLOWUP_FIELD] = dict(followup or {})
    session_state[key] = store


def adviser_response_cache_key(user_id: str, portfolio_id: str) -> str:
    return f"adviser_response_{user_id}_{portfolio_id}"


def clear_adviser_session_state(session_state) -> None:
    """Remove adviser chat/cache keys so logout cannot leave user-scoped history behind."""
    keys_to_remove = [
        key
        for key in list(session_state.keys())
        if isinstance(key, str)
        and (key.startswith("adviser_chat_") or key.startswith("adviser_response_"))
    ]
    for key in keys_to_remove:
        session_state.pop(key, None)


def get_conversation_history(session_state, key: str) -> List[AdviserConversationTurn]:
    raw_turns = _conversation_store(session_state.get(key)).get(CONVERSATION_TURNS_FIELD) or []
    history: List[AdviserConversationTurn] = []
    for item in raw_turns[-MAX_CONVERSATION_TURNS:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        history.append(
            AdviserConversationTurn(
                role=role,
                content=content,
                grounded=bool(item.get("grounded")),
            )
        )
    return history


def append_conversation_turn(
    session_state,
    key: str,
    *,
    role: str,
    content: str,
    grounded: bool = False,
) -> None:
    history = get_conversation_history(session_state, key)
    history.append(
        AdviserConversationTurn(
            role=role,
            content=_sanitize_turn_content(role, content),
            grounded=grounded,
        )
    )
    store = _conversation_store(session_state.get(key))
    store[CONVERSATION_TURNS_FIELD] = [turn.to_dict() for turn in history[-MAX_CONVERSATION_TURNS:]]
    session_state[key] = store


def record_chat_exchange(
    session_state,
    key: str,
    *,
    user_question: str,
    response: AdviserResponse,
) -> None:
    append_conversation_turn(
        session_state,
        key,
        role="user",
        content=user_question,
    )
    append_conversation_turn(
        session_state,
        key,
        role="assistant",
        content=response.answer,
        grounded=response.grounded,
    )


def clear_conversation_history(session_state, key: str) -> None:
    session_state.pop(key, None)
    session_state.pop(conversation_followup_key(key), None)
