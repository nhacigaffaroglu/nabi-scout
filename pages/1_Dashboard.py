import pandas as pd
import streamlit as st

from repositories.candidate_repository import CandidateRepository
from repositories.scan_repository import ScanRepository
from repositories.watchlist_repository import WatchlistRepository
from services.research_monitor_service import build_priority_teaser_from_monitor
from services.ui_formatters import format_priority_reasons
from services.supabase_client import get_supabase_client
from services.ui import configure_page, render_sidebar

configure_page("Dashboard | NABI Scout", "📊")
render_sidebar()

st.title("📊 Scout Dashboard")
client = get_supabase_client()
repo = CandidateRepository(client)
scan_repo = ScanRepository(client)
watchlist_repo = WatchlistRepository(client)

stats = repo.get_dashboard_stats()
cols = st.columns(5)
cols[0].metric("Toplam aday", stats["total"])
cols[1].metric("Güçlü aday", stats["strong"])
cols[2].metric("Scanner: İZLE", stats["watch"])
cols[3].metric("Katılım uygun", stats["participation_ok"])
cols[4].metric("İnceleniyor", stats["researching"])

candidates = repo.get_all(order_by="nabi_score", descending=True)
watched_ids = watchlist_repo.watched_candidate_ids()
priority_entries = build_priority_teaser_from_monitor(
    scan_repo=scan_repo,
    candidates=candidates,
    watched_candidate_ids=watched_ids,
    limit=5,
)

st.subheader("🎯 Bugünkü araştırma öncelikleri")
if st.button("🔬 Research Monitor'u Aç", type="secondary"):
    st.switch_page("pages/3_Research_Monitor.py")
if not priority_entries:
    st.info("Öncelikli aday bulunamadı.")
else:
    for index, entry in enumerate(priority_entries):
        candidate = entry["candidate"]
        symbol = candidate.get("symbol") or "—"
        company = candidate.get("company_name") or symbol
        decision = candidate.get("decision_label") or candidate.get("decision") or "—"
        reasons = format_priority_reasons(entry.get("reasons") or [])
        events = entry.get("events") or []
        for event in events[:2]:
            message = event.get("message")
            if message and message not in reasons:
                reasons.insert(0, message)

        st.markdown(
            f"**{symbol}** — Öncelik {entry['priority_score']:.0f} / "
            f"{entry['priority_label']}"
        )
        st.caption(f"{company} · {decision}")
        for reason in reasons[:3]:
            st.markdown(f"• {reason}")

        if st.button(
            "📄 Company Report",
            key=f"dashboard_report_{symbol}_{index}",
        ):
            st.session_state["company_report_candidate"] = candidate
            st.query_params["symbol"] = symbol
            st.switch_page("pages/4_Company_Report.py")
        st.markdown("")

rows = candidates
df = pd.DataFrame(rows)

if df.empty:
    st.info("Aday havuzu boş.")
else:
    c1, c2 = st.columns(2)

    with c1:
        st.subheader("Karar dağılımı")
        st.bar_chart(
            df["decision"].fillna("VERİ EKSİK").value_counts()
        )

    with c2:
        st.subheader("Varlık türü dağılımı")
        st.bar_chart(
            df["asset_type"].fillna("Belirsiz").value_counts()
        )

    st.subheader("En yüksek NABI Score")
    visible = [
        "symbol",
        "company_name",
        "asset_type",
        "market",
        "current_price",
        "fair_value",
        "discount_to_fair_value",
        "nabi_score",
        "decision",
        "participation_status",
        "research_status",
    ]

    st.dataframe(
        df[[column for column in visible if column in df.columns]],
        use_container_width=True,
        hide_index=True,
    )
