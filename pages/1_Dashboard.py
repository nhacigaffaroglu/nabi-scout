import pandas as pd
import streamlit as st

from repositories.candidate_repository import CandidateRepository
from repositories.scan_repository import ScanRepository
from repositories.watchlist_repository import WatchlistRepository
from services.daily_brief_service import build_daily_brief
from services.ui_formatters import format_datetime_tr, format_research_status
from services.research_workflow_service import normalize_research_status
from services.supabase_client import get_supabase_client
from services.ui import configure_page, render_sidebar

configure_page("Dashboard | NABI Scout", "📊")
render_sidebar()

st.title("📊 Scout Dashboard")
client = get_supabase_client()
repo = CandidateRepository(client)
scan_repo = ScanRepository(client)
watchlist_repo = WatchlistRepository(client)

brief = build_daily_brief(
    scan_repo=scan_repo,
    candidate_repo=repo,
    watchlist_repo=watchlist_repo,
)

st.subheader("☀️ Bugünün Özeti")
scheduled = brief["scheduled_run"]
scheduled_at = scheduled.get("completed_at") or scheduled.get("started_at")
if scheduled_at:
    st.caption(
        f"Son otomatik tarama: {format_datetime_tr(scheduled_at)} · "
        f"{scheduled.get('status_label', '—')}"
    )
else:
    st.caption(f"Son otomatik tarama: {scheduled.get('status_label', '—')}")
if scheduled.get("detail"):
    st.caption(scheduled["detail"])

st.markdown(f"**{brief['headline']}**")

stats = brief["summary_stats"]
metric_cols = st.columns(4)
metric_cols[0].metric("Anlamlı değişiklik", stats["meaningful_change_count"])
metric_cols[1].metric("Yeni aday", stats["new_candidate_count"])
metric_cols[2].metric("Açık araştırma", stats["open_research_count"])
metric_cols[3].metric("Veri sorunu", stats["data_issue_count"])

if st.button("🔬 Research Monitor'u Aç", type="secondary"):
    st.switch_page("pages/3_Research_Monitor.py")

if brief["today_actions"]:
    st.markdown("**🎯 Bugün Önce Bunlara Bak**")
    for index, item in enumerate(brief["today_actions"]):
        symbol = item.get("symbol") or "—"
        company = item.get("company_name") or symbol
        st.markdown(f"**{symbol}** · {company}")
        st.caption(item.get("action_label") or "—")
        st.markdown("Neden şimdi:")
        for reason in item.get("reasons") or []:
            st.markdown(f"• {reason}")
        if item.get("next_action"):
            st.caption(f"Sıradaki: {item['next_action']}")
        st.caption(item.get("workflow_status_label") or "—")
        if item.get("data_quality_caveat"):
            st.caption(item["data_quality_caveat"])
        if st.button(
            "📄 Company Report",
            key=f"brief_today_action_{symbol}_{index}",
        ):
            candidate = item.get("company_report_target") or item.get("candidate") or {"symbol": symbol}
            st.session_state["company_report_candidate"] = candidate
            st.query_params["symbol"] = symbol
            st.switch_page("pages/4_Company_Report.py")
        st.markdown("")
else:
    st.markdown("**🎯 Bugün Önce Bunlara Bak**")
    st.info("Bugün araştırma önceliğini değiştiren yeni bir gelişme yok.")

if brief.get("new_candidates"):
    with st.expander("🆕 Yeni adaylar", expanded=False):
        for index, item in enumerate(brief["new_candidates"]):
            symbol = item.get("symbol") or "—"
            st.markdown(f"**{symbol}** — {item.get('company_name') or symbol}")
            for reason in item.get("reasons") or []:
                st.markdown(f"• {reason}")
            if st.button(
                "📄 Company Report",
                key=f"brief_new_{symbol}_{index}",
            ):
                candidate = item.get("candidate") or {"symbol": symbol}
                st.session_state["company_report_candidate"] = candidate
                st.query_params["symbol"] = symbol
                st.switch_page("pages/4_Company_Report.py")

if brief.get("data_quality_updates"):
    st.markdown("**🔄 Veri kalitesi güncellemeleri**")
    for index, item in enumerate(brief["data_quality_updates"]):
        symbol = item.get("symbol") or "—"
        company = item.get("company_name") or symbol
        st.markdown(f"**{symbol}** · {company}")
        st.caption(item.get("summary") or "—")
        if st.button(
            "📄 Company Report",
            key=f"brief_data_quality_{symbol}_{index}",
        ):
            candidate = item.get("company_report_target") or item.get("candidate") or {"symbol": symbol}
            st.session_state["company_report_candidate"] = candidate
            st.query_params["symbol"] = symbol
            st.switch_page("pages/4_Company_Report.py")

if brief["watchlist_changes"]:
    st.markdown("**⭐ İzleme listemde değişenler**")
    for index, item in enumerate(brief["watchlist_changes"]):
        symbol = item.get("symbol") or "—"
        st.markdown(f"**{symbol}** — {item.get('company_name') or symbol}")
        for reason in item.get("reasons") or []:
            st.markdown(f"• {reason}")
        if st.button(
            "📄 Company Report",
            key=f"brief_watchlist_{symbol}_{index}",
        ):
            candidate = item.get("candidate") or {"symbol": symbol}
            st.session_state["company_report_candidate"] = candidate
            st.query_params["symbol"] = symbol
            st.switch_page("pages/4_Company_Report.py")

if brief["open_research"]:
    st.markdown("**📝 Açık araştırma backlog**")
    for index, item in enumerate(brief["open_research"]):
        symbol = item.get("symbol") or "—"
        st.markdown(
            f"**{symbol}** — {item.get('workflow_status_label') or '—'}"
        )
        if item.get("data_quality_caveat"):
            st.caption(item["data_quality_caveat"])
        if item.get("research_next_action"):
            st.caption(f"Sıradaki: {item['research_next_action']}")
        if item.get("last_reviewed_at"):
            st.caption(
                "Son inceleme: "
                + format_datetime_tr(item.get("last_reviewed_at"))
            )
        if st.button(
            "📄 Company Report",
            key=f"brief_open_research_{symbol}_{index}",
        ):
            candidate = item.get("candidate") or {"symbol": symbol}
            st.session_state["company_report_candidate"] = candidate
            st.query_params["symbol"] = symbol
            st.switch_page("pages/4_Company_Report.py")

if brief["data_issues"]:
    st.markdown("**⚠️ Veri sorunları**")
    for item in brief["data_issues"]:
        st.markdown(f"• {item.get('summary') or '—'}")

st.divider()

dashboard_stats = repo.get_dashboard_stats()
cols = st.columns(5)
cols[0].metric("Toplam aday", dashboard_stats["total"])
cols[1].metric("Güçlü aday", dashboard_stats["strong"])
cols[2].metric("Scanner: İZLE", dashboard_stats["watch"])
cols[3].metric("Katılım uygun", dashboard_stats["participation_ok"])
cols[4].metric("Açık Araştırma", dashboard_stats["open_research"])

candidates = repo.get_all(order_by="nabi_score", descending=True)
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

    display_df = df.copy()
    if "research_status" in display_df.columns:
        display_df["research_status"] = display_df["research_status"].apply(
            lambda value: format_research_status(normalize_research_status(value))
        )

    st.dataframe(
        display_df[[column for column in visible if column in display_df.columns]],
        use_container_width=True,
        hide_index=True,
    )
