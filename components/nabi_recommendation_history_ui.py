"""Smallest inspect surface for recommendation history and outcomes."""

from __future__ import annotations

from typing import Optional

from services.nabi_recommendation_history_presentation import (
    HISTORY_EMPTY,
    present_history_rows,
    present_tracking_status,
)
from services.nabi_recommendation_history_store import InMemoryRecommendationHistoryStore


HISTORY_SECTION = "Öneri geçmişi"


def render_recommendation_history(
    store: Optional[InMemoryRecommendationHistoryStore] = None,
    *,
    outcomes=(),
) -> None:
    import streamlit as st

    st.caption(present_tracking_status(store))
    records = store.list_records() if store is not None else ()
    if not records:
        st.caption(HISTORY_EMPTY)
        return
    related = outcomes or (store.list_outcomes() if store is not None else ())
    for line in present_history_rows(records, related):
        st.caption(line)
