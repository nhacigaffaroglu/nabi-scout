import streamlit as st

from repositories.candidate_repository import CandidateRepository
from repositories.scan_repository import ScanRepository
from repositories.watchlist_repository import WatchlistRepository
from services.candidate_pipeline_presentation import display_nabi_score
from services.research_monitor_service import (
    build_priority_entries,
    summarize_change,
)
from services.ui_formatters import format_datetime_tr, format_freshness_label
from services.ui import prepare_protected_page

client = prepare_protected_page("İzleme Listesi | NABI Scout", "⭐")

st.title("⭐ İzleme Listesi")

watchlist_repo = WatchlistRepository(client)
scan_repo = ScanRepository(client)

if "watchlist_note_edit" not in st.session_state:
    st.session_state["watchlist_note_edit"] = None

entries = watchlist_repo.list_active()

if not entries:
    st.info("Henüz izleme listenizde şirket yok.")
    st.stop()

priority_entries = build_priority_entries(
    [item["candidate"] for item in entries],
    scan_repo=scan_repo,
    watched_candidate_ids=watchlist_repo.watched_candidate_ids(),
)
priority_by_id = {
    str(item["candidate"].get("id")): item
    for item in priority_entries
}

for index, item in enumerate(entries):
    candidate = item["candidate"]
    candidate_id = str(item["candidate_id"])
    symbol = candidate.get("symbol") or "—"
    company = candidate.get("company_name") or symbol
    priority = priority_by_id.get(candidate_id, {})
    recent_change = priority.get("recent_change")

    st.markdown(f"### {symbol} — {company}")

    cols = st.columns(5)
    score = display_nabi_score(candidate)
    cols[0].metric("NABI Score", f"{score:.1f}" if score is not None else "—")
    cols[1].metric(
        "Veri Güveni",
        f"%{candidate.get('research_confidence') or 0}",
    )
    cols[2].metric(
        "Araştırma Güveni",
        candidate.get("conviction_score") or 0,
    )
    cols[3].metric(
        "Fırsat Potansiyeli",
        candidate.get("opportunity_score") or 0,
    )
    cols[4].metric(
        "Öncelik",
        f"{priority.get('priority_score', 0):.0f} / "
        f"{priority.get('priority_label', '—')}",
    )

    meta_left, meta_right = st.columns(2)
    meta_left.caption(
        f"Karar: {candidate.get('decision_label') or candidate.get('decision') or '—'} · "
        f"Güncellik: {format_freshness_label(candidate.get('freshness_status'))}"
    )
    meta_right.caption(
        "Son tarama: "
        + format_datetime_tr(
            candidate.get("updated_at") or candidate.get("created_at")
        )
    )
    st.caption(f"Son değişiklik: {summarize_change(recent_change)}")

    if item.get("notes"):
        st.write(f"**Not:** {item['notes']}")

    action_left, action_middle, action_right = st.columns([1.2, 1.2, 2.6])

    with action_left:
        if st.button(
            "📄 Raporu Aç",
            key=f"watchlist_report_{candidate_id}",
            use_container_width=True,
        ):
            st.session_state["company_report_candidate"] = candidate
            st.query_params["symbol"] = symbol
            st.switch_page("pages/4_Company_Report.py")

    with action_middle:
        if st.button(
            "İzlemeden çıkar",
            key=f"watchlist_remove_{candidate_id}",
            use_container_width=True,
        ):
            watchlist_repo.deactivate(candidate_id)
            st.rerun()

    with action_right:
        if st.session_state["watchlist_note_edit"] == candidate_id:
            note_value = st.text_input(
                "Not",
                value=item.get("notes") or "",
                key=f"watchlist_note_input_{candidate_id}",
            )
            save_col, cancel_col = st.columns(2)
            if save_col.button(
                "Notu kaydet",
                key=f"watchlist_note_save_{candidate_id}",
            ):
                watchlist_repo.update_note(candidate_id, note_value or None)
                st.session_state["watchlist_note_edit"] = None
                st.rerun()
            if cancel_col.button(
                "İptal",
                key=f"watchlist_note_cancel_{candidate_id}",
            ):
                st.session_state["watchlist_note_edit"] = None
                st.rerun()
        elif st.button(
            "Not düzenle",
            key=f"watchlist_note_edit_btn_{candidate_id}",
        ):
            st.session_state["watchlist_note_edit"] = candidate_id
            st.rerun()

    st.divider()
