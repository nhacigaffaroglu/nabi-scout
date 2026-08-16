from datetime import datetime, timedelta, timezone

import streamlit as st

from repositories.candidate_repository import CandidateRepository
from repositories.scan_repository import ScanRepository
from repositories.watchlist_repository import WatchlistRepository
from services.candidate_surface_service import filter_equity_candidate_surface
from services.research_monitor_service import build_monitor_feed
from services.research_workflow_service import (
    WORKFLOW_FILTER_OPTIONS,
    build_research_workflow,
    filter_monitor_entries,
)
from services.scan_snapshot import normalize_universe_name
from services.ui_formatters import (
    LEGACY_HISTORY_NOTE,
    format_badges_compact,
    format_datetime_tr,
    format_freshness_label,
    format_priority_reasons,
)
from services.ui import prepare_protected_page

client = prepare_protected_page("Research Monitor | NABI Scout", "🔬")

st.title("🔬 Araştırma Monitörü")
st.caption(
    "Araştırma pipeline'ı — son taramalar arasındaki anlamlı değişiklikler ve "
    "bugünkü araştırma öncelikleri. Portföy Monitörü'nden ayrıdır."
)

candidate_repo = CandidateRepository(client)
scan_repo = ScanRepository(client)
watchlist_repo = WatchlistRepository(client)

WINDOW_OPTIONS = {
    "Son 1 gün": 1,
    "Son 7 gün": 7,
    "Son 30 gün": 30,
}

lookback_runs = scan_repo.get_completed_runs_since(
    datetime.now(timezone.utc) - timedelta(days=30),
)
universe_names = sorted({
    normalize_universe_name(run.get("universe_name"))
    for run in lookback_runs
    if normalize_universe_name(run.get("universe_name"))
})

control_left, control_middle, control_right = st.columns(3)
window_label = control_left.selectbox(
    "Zaman penceresi",
    list(WINDOW_OPTIONS.keys()),
    index=1,
)
workflow_filter = control_middle.selectbox(
    "Araştırma durumu",
    WORKFLOW_FILTER_OPTIONS,
    index=0,
)
universe_label = control_right.selectbox(
    "Evren",
    ["Tüm evrenler", *universe_names],
    index=0,
)

since = datetime.now(timezone.utc) - timedelta(days=WINDOW_OPTIONS[window_label])
universe_name = None if universe_label == "Tüm evrenler" else universe_label

candidates = filter_equity_candidate_surface(
    candidate_repo.get_all(order_by="nabi_score", descending=True)
)
watched_ids = watchlist_repo.watched_candidate_ids()

feed = build_monitor_feed(
    scan_repo=scan_repo,
    candidates=candidates,
    watched_candidate_ids=watched_ids,
    since=since,
    universe_name=universe_name,
)

SECTIONS = [
    ("ATTENTION", "🔥 Dikkat Gerektirenler"),
    ("WATCHLIST", "⭐ İzleme Listem"),
    ("NEW", "🆕 Yeni Araştırma Adayları"),
    ("DATA_ISSUES", "⚠️ Veri / Güncellik Sorunları"),
]

if not feed["entries"]:
    st.info("Seçilen pencerede gösterilecek anlamlı değişiklik bulunamadı.")
    st.stop()


def render_entry(entry: dict, index: int, section: str) -> None:
    symbol = entry.get("symbol") or "—"
    company = entry.get("company_name") or symbol
    priority = entry.get("research_priority") or {}
    candidate = entry.get("candidate") or {}
    latest_snapshot = entry.get("latest_snapshot") or {}
    decision = (
        candidate.get("decision_label")
        or candidate.get("decision")
        or latest_snapshot.get("decision_label")
        or "—"
    )
    freshness = (
        candidate.get("freshness_status")
        or latest_snapshot.get("freshness_status")
        or "—"
    )
    confidence = (
        candidate.get("research_confidence")
        or latest_snapshot.get("research_confidence")
    )
    badges = entry.get("badges") or []
    events = entry.get("events") or []
    workflow = build_research_workflow(candidate)

    st.markdown(
        f"**{symbol}** — {company} · "
        f"Öncelik {priority.get('priority_score', 0):.0f} / "
        f"{priority.get('priority_label', '—')}"
    )
    st.caption(
        f"Karar: {decision} · Güncellik: {format_freshness_label(freshness)} · "
        f"Veri güveni: {confidence if confidence is not None else '—'} · "
        f"Son tarama: {format_datetime_tr(entry.get('latest_scan_at'))}"
    )
    st.caption(f"Araştırma: {workflow['research_status_label']}")
    if workflow.get("research_next_action"):
        st.caption(f"Sıradaki: {workflow['research_next_action']}")
    if workflow.get("last_reviewed_at"):
        st.caption(
            "Son inceleme: "
            + format_datetime_tr(workflow.get("last_reviewed_at"))
        )
    badge_line = format_badges_compact(badges)
    if badge_line:
        st.caption(badge_line)
    if entry.get("has_legacy_history"):
        st.caption(LEGACY_HISTORY_NOTE)

    shown_reasons = []
    for event in events[:3]:
        message = event.get("message")
        if message:
            shown_reasons.append(message)
    for reason in format_priority_reasons(priority.get("reasons") or [])[:3]:
        if reason not in shown_reasons:
            shown_reasons.append(reason)
    for reason in shown_reasons[:3]:
        st.markdown(f"• {reason}")

    if st.button(
        "📄 Raporu Aç",
        key=f"monitor_report_{section}_{symbol}_{index}",
    ):
        if candidate:
            st.session_state["company_report_candidate"] = candidate
        else:
            st.session_state["company_report_candidate"] = {
                "symbol": symbol,
                "company_name": company,
                **latest_snapshot,
            }
        st.query_params["symbol"] = symbol
        st.switch_page("pages/4_Company_Report.py")
    st.divider()


for section_key, section_title in SECTIONS:
    section_entries = feed["categories"].get(section_key) or []
    section_entries = filter_monitor_entries(section_entries, workflow_filter)
    st.subheader(section_title)
    if not section_entries:
        st.caption("Bu bölümde gösterilecek kayıt yok.")
        continue
    for index, entry in enumerate(section_entries):
        render_entry(entry, index, section_key)
