import pandas as pd
import streamlit as st
from typing import Optional

from repositories.tracked_fund_repository import TrackedFundRepository
from repositories.candidate_repository import CandidateRepository
from repositories.scan_repository import ScanRepository
from repositories.watchlist_repository import WatchlistRepository
from services.candidate_pipeline_presentation import present_candidate_display_row
from services.candidate_surface_service import filter_equity_candidate_surface
from services.ui_table_headers import apply_display_headers
from services.daily_brief_service import build_daily_brief
from services.alpha_vantage_client import AlphaVantageClient
from services.fmp_client import FMPClient, FMPError
from services.fund_analysis_contract import (
    BENCHMARK_RELATIVE_DISCLAIMER,
    PARTICIPATION_SOURCE_CONFIGURED,
)
from components.fund_report_ui import (
    format_compact_number,
    format_pct,
    format_tracked_participation_label,
    render_fund_performance_risk,
    render_tracked_provider_notice,
)
from services.fund_report_service import (
    FUND_REPORT_QUERY_PARAM,
    FUND_REPORT_SESSION_LIVE,
    FUND_REPORT_SESSION_RESOLVED,
    FUND_REPORT_SESSION_SYMBOL,
    resolve_display_fund_name,
)
from services.manual_analysis_service import (
    UNRESOLVED_UNSUPPORTED_REASON,
    analyze_security,
    save_manual_candidate,
    save_tracked_fund,
    untrack_fund,
)
from services.free_universe_client import FreeUniverseClient
from services.sec_contact_config import get_sec_contact_email
from services.scanner_v8_engine import ScannerV8Engine
from services.sec_financial_client import SECFinancialClient
from services.symbol_resolver_service import SymbolNotFoundError
from services.ui_formatters import format_datetime_tr, format_research_status
from services.research_workflow_service import normalize_research_status
from components.nabi_home_dashboard import render_nabi_home_executive
from services.ui import prepare_protected_page

client = prepare_protected_page("Dashboard | NABI Scout", "📊")

st.title("NABI — Bugün")
st.caption("Karar özeti — normal render LLM/FMP/SEC/FX uzak çağrısı yapmaz.")
render_nabi_home_executive(client)
st.divider()
st.subheader("Scout Araçları")
repo = CandidateRepository(client)
scan_repo = ScanRepository(client)
watchlist_repo = WatchlistRepository(client)
tracked_fund_repo = TrackedFundRepository(client)


@st.cache_data(ttl=3600, show_spinner=False)
def load_sec_company_lookup(contact_email: str) -> dict:
    if not contact_email.strip():
        return {}
    rows = FreeUniverseClient(contact_email=contact_email.strip()).get_sec_companies()
    return {
        str(row.get("symbol") or "").strip().upper(): row
        for row in rows
        if row.get("symbol")
    }


st.markdown("**🔎 Bir sembol analiz et**")
manual_symbol = st.text_input(
    "Sembol",
    key="dashboard_manual_symbol",
    placeholder="NVDA",
    label_visibility="collapsed",
)
analyze_col, _ = st.columns([1, 3])
with analyze_col:
    analyze_clicked = st.button("Analiz et", type="primary", key="dashboard_analyze_button")


def _execute_manual_analysis(symbol: str):
    normalized = str(symbol or "").strip().upper()
    if not normalized:
        st.error("Sembol girin.")
        return None
    try:
        sec_email = get_sec_contact_email()
        sec_lookup = load_sec_company_lookup(sec_email)
        fmp_client = FMPClient.from_streamlit_secrets()
        alpha_vantage_client = AlphaVantageClient.from_streamlit_secrets()
        sec_client = SECFinancialClient(contact_email=sec_email)
        engine = ScannerV8Engine(fmp_client, sec_client)
        with st.spinner(f"{normalized} analiz ediliyor..."):
            return analyze_security(
                normalized,
                candidate_repo=repo,
                scan_repo=scan_repo,
                fmp_client=fmp_client,
                alpha_vantage_client=alpha_vantage_client,
                tracked_fund_repo=tracked_fund_repo,
                sec_client=sec_client,
                sec_lookup=sec_lookup,
                engine=engine,
            )
    except SymbolNotFoundError:
        st.error("Sembol bulunamadı.")
    except FMPError as exc:
        if exc.error_class == "rate_limit":
            st.warning("Veri sağlayıcı limiti nedeniyle analiz şu an tamamlanamadı.")
        else:
            st.error(f"Analiz sırasında veri hatası oluştu: {exc}")
    except Exception as exc:
        st.error(f"Analiz tamamlanamadı: {exc}")
    return None


def _open_fund_report(symbol: str) -> None:
    normalized = str(symbol or "").strip().upper()
    if not normalized:
        return
    st.session_state[FUND_REPORT_SESSION_SYMBOL] = normalized
    manual_result = st.session_state.get("manual_analysis_result")
    if (
        manual_result is not None
        and manual_result.analysis_kind == "fund"
        and str(manual_result.symbol or "").strip().upper() == normalized
        and manual_result.fund_result is not None
        and manual_result.resolved is not None
        and manual_result.resolved.is_etf
    ):
        st.session_state[FUND_REPORT_SESSION_LIVE] = manual_result.fund_result
        st.session_state[FUND_REPORT_SESSION_RESOLVED] = manual_result.resolved
    else:
        st.session_state.pop(FUND_REPORT_SESSION_LIVE, None)
        st.session_state.pop(FUND_REPORT_SESSION_RESOLVED, None)
    st.session_state["fund_report_had_tracked_context"] = True
    st.query_params[FUND_REPORT_QUERY_PARAM] = normalized
    st.switch_page("pages/9_Fund_Report.py")


if analyze_clicked:
    analysis = _execute_manual_analysis(manual_symbol)
    if analysis is not None:
        st.session_state["manual_analysis_result"] = analysis
    else:
        st.session_state.pop("manual_analysis_result", None)


def _render_tracked_funds_section() -> None:
    st.markdown("**⭐ Takip Edilen Fonlar**")
    tracked_rows = tracked_fund_repo.list_all(order_by="updated_at", descending=True)
    if not tracked_rows:
        st.info("Henüz takip edilen fon yok.")
        st.caption(
            "Bu bilgi bağımsız NABI Şeriat uygunluk doğrulaması değildir."
        )
        return

    st.caption(
        "Bu bilgi bağımsız NABI Şeriat uygunluk doğrulaması değildir."
    )
    for index, row in enumerate(tracked_rows):
        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        candidate_row = repo.get_by_symbol(symbol)
        fund_name = resolve_display_fund_name(
            symbol,
            tracked_row=row,
            candidate_row=candidate_row,
        )
        asset_class = row.get("asset_class") or "—"
        last_updated = row.get("last_reviewed_at") or row.get("updated_at")
        last_updated_label = (
            format_datetime_tr(last_updated) if last_updated else "—"
        )
        with st.container(border=True):
            st.markdown(f"**{symbol}** · {fund_name}")
            st.caption(format_tracked_participation_label(row))
            st.caption(f"Sınıf: {asset_class}")
            st.caption(f"Son takip güncellemesi: {last_updated_label}")
            if row.get("data_provider"):
                st.caption(f"Veri kaynağı: {row['data_provider']}")
            action_cols = st.columns(3)
            with action_cols[0]:
                if st.button(
                    "Analiz et / Güncelle",
                    key=f"dashboard_tracked_analyze_{symbol}_{index}",
                ):
                    analysis = _execute_manual_analysis(symbol)
                    if analysis is not None:
                        st.session_state["manual_analysis_result"] = analysis
                    else:
                        st.session_state.pop("manual_analysis_result", None)
            with action_cols[1]:
                if st.button(
                    "📊 Fon Raporu",
                    key=f"dashboard_tracked_fund_report_{symbol}_{index}",
                ):
                    _open_fund_report(symbol)
            with action_cols[2]:
                if st.button(
                    "Takipten çıkar",
                    key=f"dashboard_tracked_untrack_{symbol}_{index}",
                ):
                    if untrack_fund(tracked_fund_repo, symbol=symbol):
                        st.success(f"{symbol} takipten çıkarıldı.")
                    else:
                        st.caption(f"{symbol} zaten takip listesinde değil.")
                    st.session_state.pop("manual_analysis_result", None)


manual_result = st.session_state.get("manual_analysis_result")
if manual_result is not None:
    resolved = manual_result.resolved
    st.markdown(
        f"**{manual_result.symbol}** · "
        f"{resolved.company_name or manual_result.symbol}"
    )
    st.caption(
        f"Tür: {resolved.security_type} · "
        f"Kaynak: {resolved.resolution_source}"
    )

    if manual_result.analysis_kind == "equity" and manual_result.candidate:
        candidate = manual_result.candidate
        metric_cols = st.columns(4)
        metric_cols[0].metric(
            "NABI Score",
            candidate.get("nabi_score") if candidate.get("nabi_score") is not None else "—",
        )
        metric_cols[1].metric(
            "Veri tamlığı",
            f"{candidate.get('data_completeness', 0):.0f}%"
            if candidate.get("data_completeness") is not None
            else "—",
        )
        metric_cols[2].metric(
            "Karar",
            candidate.get("decision_label") or candidate.get("decision") or "—",
        )
        metric_cols[3].metric(
            "Araştırma güveni",
            candidate.get("research_confidence")
            if candidate.get("research_confidence") is not None
            else "—",
        )
        for warning in manual_result.warnings:
            st.warning(warning)
        for error in manual_result.errors:
            st.error(error)

        action_cols = st.columns(2)
        with action_cols[0]:
            if st.button(
                "📄 Company Report'u aç",
                key="dashboard_open_company_report",
            ):
                st.session_state["company_report_candidate"] = candidate
                st.query_params["symbol"] = manual_result.symbol
                st.switch_page("pages/4_Company_Report.py")
        with action_cols[1]:
            if not manual_result.is_persisted:
                if st.button(
                    "Aday havuzuna kaydet",
                    key="dashboard_save_manual_candidate",
                ):
                    try:
                        saved = save_manual_candidate(repo, candidate)
                        manual_result.is_persisted = True
                        manual_result.persisted_candidate_id = saved.get("id")
                        st.session_state["manual_analysis_result"] = manual_result
                        st.success(f"{manual_result.symbol} aday havuzuna kaydedildi.")
                    except ValueError as exc:
                        st.error(str(exc))
            else:
                st.caption("Bu sembol aday havuzunda kayıtlı.")

    elif manual_result.analysis_kind == "fund" and manual_result.fund_result is not None:
        fund = manual_result.fund_result
        st.caption("ETF / fon analizi — equity NABI skoru uygulanmaz.")
        render_tracked_provider_notice(
            fund,
            is_tracked=manual_result.is_tracked,
        )
        if fund.data_provider:
            st.caption(f"Veri kaynağı: {fund.data_provider}")
        premium_warning = next(
            (
                warning
                for warning in fund.warnings
                if "mevcut plan kapsamında" in warning.lower()
            ),
            None,
        )
        if premium_warning:
            st.info(premium_warning)

        metric_cols = st.columns(5)
        metric_cols[0].metric(
            "Gider oranı",
            f"%{fund.expense_ratio:.2f}" if fund.expense_ratio is not None else "—",
        )
        metric_cols[1].metric(
            "AUM",
            format_compact_number(fund.aum) if fund.aum is not None else "—",
        )
        metric_cols[2].metric(
            "Holdings",
            fund.holdings_count if fund.holdings_count is not None else "—",
        )
        metric_cols[3].metric(
            "Top-10 yoğunluk",
            f"%{fund.top10_concentration_pct:.1f}"
            if fund.top10_concentration_pct is not None
            else "—",
        )
        metric_cols[4].metric(
            "Güncel fiyat",
            fund.current_price if fund.current_price is not None else "—",
        )

        if fund.benchmark:
            st.caption(f"Endeks / benchmark: {fund.benchmark}")
            st.caption(BENCHMARK_RELATIVE_DISCLAIMER)
        if fund.issuer:
            st.caption(f"İhraççı: {fund.issuer}")
        if fund.asset_class or fund.domicile:
            st.caption(
                " · ".join(
                    part
                    for part in (
                        f"Sınıf: {fund.asset_class}" if fund.asset_class else None,
                        f"Domicil: {fund.domicile}" if fund.domicile else None,
                        f"Kuruluş: {fund.inception_date}" if fund.inception_date else None,
                    )
                    if part
                )
            )

        if (
            fund.participation_source == PARTICIPATION_SOURCE_CONFIGURED
            and fund.participation_status
        ):
            st.info(
                f"Katılım metadata (yapılandırılmış): {fund.participation_status} "
                f"({fund.participation_score}). "
                "Bu bilgi bağımsız NABI Şeriat uygunluk doğrulaması değildir."
            )
        elif fund.participation_status:
            st.caption(
                f"Katılım: {fund.participation_status} "
                f"({fund.participation_score})"
            )

        if fund.top_holdings:
            st.markdown("**Portföy — Top holdings**")
            holdings_df = pd.DataFrame(
                [
                    {
                        "Sembol": holding.symbol or "—",
                        "Ad": holding.name or "—",
                        "Ağırlık (%)": holding.weight_pct,
                    }
                    for holding in fund.top_holdings
                ]
            )
            st.dataframe(holdings_df, use_container_width=True, hide_index=True)

        if fund.dimension_scores:
            st.markdown("**Boyut gözlemleri**")
            for dimension in fund.dimension_scores:
                st.write(
                    f"**{dimension.dimension}** — {dimension.score:.0f}/100 · "
                    f"{dimension.observation}"
                )

        render_fund_performance_risk(fund)

        if fund.labels:
            st.markdown("**Etiketler:** " + ", ".join(f"`{label}`" for label in fund.labels))

        quality_cols = st.columns(2)
        quality_cols[0].metric(
            "Veri tamlığı",
            f"%{fund.data_completeness_pct:.0f}",
        )
        quality_cols[1].metric("Güven", fund.analysis_confidence)

        for warning in manual_result.warnings:
            st.warning(warning)
        if fund.unsupported_fields:
            st.caption(
                "Doğrulanamayan alanlar: "
                + ", ".join(fund.unsupported_fields)
            )

        if not manual_result.is_tracked:
            if st.button("Takibe al", key="dashboard_track_fund"):
                try:
                    saved = save_tracked_fund(
                        tracked_fund_repo,
                        fund_result=fund,
                        resolved=resolved,
                    )
                    manual_result.is_tracked = True
                    manual_result.tracked_fund_id = saved.get("id")
                    st.session_state["manual_analysis_result"] = manual_result
                    st.success(f"{manual_result.symbol} takibe alındı.")
                except ValueError as exc:
                    st.error(str(exc))
        else:
            st.caption("Bu fon takip listesinde.")

    elif manual_result.analysis_kind == "etf_metadata":
        st.warning("Bu sonuç eski bir ETF görünümü; lütfen sembolü yeniden analiz edin.")

    elif manual_result.analysis_kind == "unresolved":
        st.warning(manual_result.unsupported_reason or UNRESOLVED_UNSUPPORTED_REASON)
        if resolved.cik:
            st.caption(f"SEC CIK: {resolved.cik}")
        if resolved.exchange:
            st.caption(f"Borsa: {resolved.exchange}")
        for warning in manual_result.warnings:
            st.warning(warning)

    st.divider()

_render_tracked_funds_section()
st.divider()

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
rows = filter_equity_candidate_surface(candidates)
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

    st.subheader("Aday özeti")
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
        "pipeline_stage",
    ]

    display_df = pd.DataFrame([present_candidate_display_row(row) for row in rows])
    if "research_status" in display_df.columns:
        display_df["research_status"] = display_df["research_status"].apply(
            lambda value: format_research_status(normalize_research_status(value))
        )

    present = [column for column in visible if column in display_df.columns]
    st.dataframe(
        apply_display_headers(display_df, columns=present),
        use_container_width=True,
        hide_index=True,
    )
