import pandas as pd
import os
import streamlit as st

from repositories.candidate_repository import CandidateRepository
from repositories.scan_repository import ScanRepository
from repositories.tracked_fund_repository import TrackedFundRepository
from repositories.watchlist_repository import WatchlistRepository
from services.auth_service import get_current_user_id
from services.candidate_surface_service import (
    enrich_candidate_classification_from_db,
    is_equity_candidate_surface_eligible,
)
from services.participation_filter_service import (
    COMPANY_REPORT_PARTICIPATION_FILTERS,
    filter_candidates_by_participation,
)
from services.monitor_intelligence_service import MonitorIntelligenceService
from services.portfolio_context_service import build_symbol_portfolio_context
from services.company_intelligence_service import build_company_intelligence
from repositories.participation_assessment_repository import (
    ParticipationAssessmentRepository,
)
from services.company_report_participation_service import build_company_report_participation
from services.fund_report_service import FUND_REPORT_QUERY_PARAM, FUND_REPORT_SESSION_SYMBOL
from services.participation_assessment_persistence_service import (
    fetch_participation_assessment_history,
    save_participation_assessment_snapshot,
)
from services.sec_contact_config import get_sec_contact_email
from services.sec_financial_client import SECFinancialClient
from services.free_universe_client import FreeUniverseClient
from components.company_intelligence_ui import render_company_intelligence_sections
from components.company_report_ui import render_company_report_participation_section
from components.investment_thesis_ui import (
    render_investment_thesis_section,
    render_investment_thesis_technical_details,
)
from components.ai_research_summary_ui import (
    clear_ai_summary_cache,
    load_cached_ai_summary,
    render_ai_research_summary_section,
    store_ai_summary,
)
from services.ai_research_summary_display import polish_ai_research_summary_view
from services.ai_research_summary_trace import get_last_ai_summary_generation_trace
from services.ai_research_summary_service import (
    AIResearchSummaryService,
    compute_context_semantic_identity,
)
from services.ai_research_summary_persistence_service import (
    fetch_exact_ai_research_summary,
    save_ai_research_summary_snapshot,
    symbol_has_stale_persisted_summary,
)
from services.wealth_adviser_config import load_adviser_llm_config
from repositories.investment_thesis_repository import InvestmentThesisRepository
from repositories.ai_research_summary_repository import AIResearchSummaryRepository
from services.investment_thesis_persistence_service import (
    fetch_investment_thesis_history,
    save_investment_thesis_snapshot,
)
from services.investment_thesis_service import InvestmentThesisService
from services.company_intelligence_core_service import CompanyIntelligenceCoreService
from services.fmp_client import FMPClient, FMPError
from services.research_eligibility_service import (
    evaluate_research_eligibility_from_participation_view,
)
from components.research_eligibility_ui import render_research_eligibility_block
from services.research_workflow_service import (
    ResearchWorkflowSchemaError,
    build_research_workflow,
    workflow_select_index,
    workflow_select_options,
)
from services.ui_formatters import (
    format_badges_compact,
    format_change_window_summary,
    format_data_quality_notes,
    format_datetime_tr,
    format_priority_reasons,
)
from services.academy_ui import (
    render_metric_card,
    render_metric_explanation,
)
from services.ui import prepare_protected_page


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


client = prepare_protected_page("Company Report | NABI Scout", "📄")

st.title("📄 NABI Company Report")

repo = CandidateRepository(client)
tracked_fund_repo = TrackedFundRepository(client)
watchlist_repo = WatchlistRepository(client)
scan_repo = ScanRepository(client)
candidate = st.session_state.get("company_report_candidate")

if candidate is None:
    rows = repo.get_all(
        order_by="nabi_score",
        descending=True,
    )
    rows = [
        row
        for row in rows
        if is_equity_candidate_surface_eligible(row)
    ]

    participation_filter = st.selectbox(
        "Katılım filtresi",
        list(COMPANY_REPORT_PARTICIPATION_FILTERS),
        index=0,
        key="company_report_participation_filter",
        help="Yalnızca listede görünen adayları filtreler; katılım kararını değiştirmez.",
    )
    rows = filter_candidates_by_participation(rows, participation_filter)

    query_symbol = st.query_params.get("symbol")
    if query_symbol:
        direct = repo.get_by_symbol(query_symbol)
        if direct and not is_equity_candidate_surface_eligible(direct):
            candidate = direct

    if candidate is None:
        if not rows:
            st.info(
                "Seçilen katılım filtresine uyan veya raporlanacak şirket bulunmuyor. "
                "Filtreyi değiştirin veya Scout Scanner ekranında tarama yapın."
            )
            st.stop()

        default_index = 0
        labels = []
        row_lookup = {}

        for index, row in enumerate(rows):
            label = (
                f"{row['symbol']} — "
                f"{row.get('company_name') or row['symbol']}"
            )
            labels.append(label)
            row_lookup[label] = row["id"]

            if query_symbol and row["symbol"] == query_symbol:
                default_index = index

        selected = st.selectbox(
            "Şirket seç",
            labels,
            index=default_index,
        )
        candidate = repo.get_by_id(row_lookup[selected])

if candidate is not None:
    candidate = enrich_candidate_classification_from_db(
        candidate,
        repo.get_by_symbol,
    )

if not is_equity_candidate_surface_eligible(candidate):
    symbol = str(candidate.get("symbol") or "").strip().upper()
    tracked_row = tracked_fund_repo.get_by_symbol(symbol) if symbol else None
    st.warning(
        "Bu sembol equity Company Report kapsamında değil. "
        "ETF/fonlar için Dashboard'daki Takip Edilen Fonlar ve Fon Raporu kullanılır."
    )
    if tracked_row is not None and symbol:
        if st.button("📊 Fon Raporu", type="primary", key="company_report_fund_redirect"):
            st.session_state[FUND_REPORT_SESSION_SYMBOL] = symbol
            st.query_params[FUND_REPORT_QUERY_PARAM] = symbol
            st.session_state.pop("company_report_candidate", None)
            if "symbol" in st.query_params:
                del st.query_params["symbol"]
            st.switch_page("pages/9_Fund_Report.py")
    if st.button("← Dashboard", key="company_report_non_equity_dashboard"):
        st.session_state.pop("company_report_candidate", None)
        if "symbol" in st.query_params:
            del st.query_params["symbol"]
        st.switch_page("pages/1_Dashboard.py")
    st.stop()

candidate_id = candidate.get("id")
if not candidate_id and candidate.get("symbol"):
    db_candidate = repo.get_by_symbol(candidate["symbol"])
    if db_candidate:
        candidate_id = db_candidate.get("id")
        candidate = {**db_candidate, **candidate, "id": candidate_id}

symbol = candidate.get("symbol") or "—"
company = candidate.get("company_name") or symbol

participation_repo = ParticipationAssessmentRepository(client)
participation_symbol = str(candidate.get("symbol") or "").strip().upper()

top_left, top_right = st.columns([4, 1])

with top_left:
    st.markdown(f"## {symbol} — {company}")
    st.caption(
        f"{candidate.get('thesis_type') or 'Tez türü yok'} · "
        f"{candidate.get('investment_profile') or 'Profil yok'}"
    )

with top_right:
    watchlist_entry = (
        watchlist_repo.get_active_entry(str(candidate_id))
        if candidate_id
        else None
    )
    is_watched = watchlist_entry is not None

    if candidate_id:
        if is_watched:
            if st.button(
                "✓ İzleniyor — çıkar",
                use_container_width=True,
            ):
                watchlist_repo.deactivate(str(candidate_id))
                st.rerun()
        elif st.button(
            "⭐ İzleme listesine ekle",
            use_container_width=True,
        ):
            watchlist_repo.add_candidate(str(candidate_id))
            st.rerun()

    if is_watched and watchlist_entry and watchlist_entry.get("notes"):
        st.caption(f"İzleme notu: {watchlist_entry['notes']}")

    if st.button(
        "← Tarama ekranı",
        use_container_width=True,
    ):
        st.switch_page("pages/2_Scout_Tarama.py")

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("NABI Skoru", candidate.get("nabi_score") or 0)
c2.metric(
    "Veri Güveni",
    f"%{candidate.get('research_confidence') or 0}",
    help=(
        "Analizde kullanılan finansal verilerin kapsam ve "
        "güvenilirlik düzeyi."
    ),
)
c3.metric(
    "Araştırma Güveni",
    candidate.get("conviction_score") or 0,
    help=(
        "Şirket hakkındaki araştırma sonucunun ne kadar "
        "güçlü ve tutarlı olduğuna ilişkin birleşik puan."
    ),
)
c4.metric(
    "Fırsat Potansiyeli",
    candidate.get("opportunity_score") or 0,
    help=(
        "Kalite, büyüme ve değerleme birlikte "
        "değerlendirildiğinde araştırma fırsatı."
    ),
)
c5.metric(
    "Yatırım Notu",
    candidate.get("investment_grade") or "—",
)

user_id = get_current_user_id(client)
if user_id and symbol and symbol != "—":
    portfolio_ctx = build_symbol_portfolio_context(client, user_id, symbol)
    if portfolio_ctx is not None:
        st.markdown("**Portföy bağlamı**")
        pc1, pc2, pc3, pc4 = st.columns(4)
        pc1.metric("Portföyde", "Evet")
        pc2.metric("Adet", f"{portfolio_ctx.quantity:,.2f}" if portfolio_ctx.quantity else "—")
        pc3.metric(
            "Ağırlık",
            f"%{portfolio_ctx.portfolio_weight_pct:.1f}"
            if portfolio_ctx.portfolio_weight_pct is not None
            else "—",
        )
        pc4.metric(
            "Gerçekleşmemiş K/Z",
            f"{portfolio_ctx.unrealized_pl:,.2f}"
            if portfolio_ctx.unrealized_pl is not None
            else "—",
        )
        if portfolio_ctx.limitations:
            st.caption(" · ".join(portfolio_ctx.limitations))
        if portfolio_ctx.account_breakdown:
            st.markdown("**Kurum bazında**")
            for part in portfolio_ctx.account_breakdown:
                st.write(
                    f"- {part.account_label}: {part.quantity:g} adet"
                    + (
                        f" · maliyet {part.cost_basis:,.2f}"
                        if part.cost_basis is not None
                        else ""
                    )
                )
        st.page_link(
            "pages/11_Portfolio_Intelligence.py",
            label="Portfolio Intelligence",
            icon="📊",
        )
        try:
            monitor = MonitorIntelligenceService(client, user_id)
            from services.portfolio_intelligence_service import PortfolioIntelligenceService
            from services.candidate_price_service import CandidatePriceService
            from services.portfolio_intelligence_enrichment_service import (
                build_portfolio_intelligence_dashboard,
            )
            from services.wealth_core_service import WealthCoreService

            wealth = WealthCoreService(client, user_id)
            pf = wealth.ensure_default_portfolio()
            price_service = CandidatePriceService(client)
            intel = PortfolioIntelligenceService(wealth, price_service, nabi_client=client)
            view = intel.build_view(pf, enrich_nabi=False)
            dash = build_portfolio_intelligence_dashboard(view)
            monitor_summary = monitor.symbol_summary(symbol, dashboard=dash)
            if monitor_summary.get("event_count"):
                st.markdown("**Monitor**")
                st.caption(
                    f"Olay: {monitor_summary['event_count']} · "
                    f"Yüksek öncelik (yeni): {monitor_summary['unresolved_high_priority']}"
                )
                if monitor_summary.get("latest_title"):
                    st.write(monitor_summary["latest_title"])
                st.page_link("pages/12_Monitor.py", label="NABI Monitor", icon="📡")
        except Exception:
            pass
        with st.expander("Karar günlüğü / fırsat", expanded=False):
            try:
                from services.wealth_decision_journal_service import WealthDecisionJournalService
                from services.portfolio_opportunity_engine import build_portfolio_opportunities
                from services.portfolio_intelligence_service import PortfolioIntelligenceService
                from services.candidate_price_service import CandidatePriceService
                from services.wealth_core_service import WealthCoreService
                from services.portfolio_intelligence_enrichment_service import (
                    build_portfolio_intelligence_dashboard,
                )
                from repositories.candidate_repository import CandidateRepository

                wealth = WealthCoreService(client, user_id)
                pf = wealth.ensure_default_portfolio()
                entries = WealthDecisionJournalService(client, user_id).list_entries(
                    symbol=symbol,
                    portfolio_id=str(pf["id"]),
                    limit=5,
                )
                if entries:
                    for entry in entries:
                        st.write(
                            f"- {(entry.get('created_at') or '')[:10]} · "
                            f"{entry.get('action_context')} · "
                            f"{(entry.get('thesis') or '')[:120]}"
                        )
                else:
                    st.caption("Bu sembol için karar kaydı yok.")
                price_service = CandidatePriceService(client)
                intel = PortfolioIntelligenceService(
                    wealth, price_service, nabi_client=client
                )
                view = intel.build_view(pf, enrich_nabi=True)
                dash = build_portfolio_intelligence_dashboard(
                    view,
                    accounts_by_id={str(a["id"]): a for a in wealth.list_accounts()},
                )
                held = any(
                    row.valuation.symbol == symbol
                    for row in dash.enriched_positions
                )
                if not held:
                    candidates = CandidateRepository(client).get_all(limit=200)
                    opps = build_portfolio_opportunities(
                        dash.enriched_positions,
                        candidates,
                    )
                    match = next((o for o in opps if o.symbol == symbol), None)
                    if match:
                        st.info(match.explanation)
            except Exception:
                st.caption("Karar günlüğü / fırsat bağlamı şu an yüklenemedi.")

workflow = build_research_workflow(candidate)

st.subheader("📝 Araştırma Durumu")
st.caption(
    "Bu durum araştırma sürecinizi gösterir; Scanner Kararı veya "
    "Araştırma Önceliği değildir."
)

if candidate_id:
    status_labels, status_values = zip(*workflow_select_options())
    with st.form("company_report_workflow_form"):
        selected_status = st.selectbox(
            "Araştırma durumu",
            status_labels,
            index=workflow_select_index(workflow["research_status"]),
        )
        next_action_value = st.text_input(
            "Sıradaki adım",
            value=workflow.get("research_next_action") or "",
        )
        research_note_value = st.text_area(
            "Araştırma notu",
            value=workflow.get("research_note") or "",
        )
        st.caption(
            "Son inceleme: "
            + format_datetime_tr(workflow.get("last_reviewed_at"))
        )
        save_col, review_col = st.columns(2)
        save_clicked = save_col.form_submit_button("Kaydet", type="primary")
        review_clicked = review_col.form_submit_button(
            "✓ İncelendi olarak işaretle",
        )

    if save_clicked or review_clicked:
        try:
            status_index = list(status_labels).index(selected_status)
            status_value = status_values[status_index]
            from datetime import datetime, timezone

            if review_clicked:
                updated = repo.update_research_workflow(
                    str(candidate_id),
                    status=status_value,
                    next_action=next_action_value,
                    research_note=research_note_value,
                    last_reviewed_at=datetime.now(timezone.utc),
                )
            else:
                updated = repo.update_research_workflow(
                    str(candidate_id),
                    status=status_value,
                    next_action=next_action_value,
                    research_note=research_note_value,
                )
            candidate = {**candidate, **updated}
            st.session_state["company_report_candidate"] = candidate
            st.rerun()
        except ResearchWorkflowSchemaError as exc:
            st.error(str(exc))
        except Exception as exc:
            st.error(f"Araştırma durumu kaydedilemedi: {exc}")
else:
    st.info("Workflow durumu kaydetmek için geçerli bir aday kaydı gerekir.")
    st.caption(
        "Son inceleme: "
        + format_datetime_tr(workflow.get("last_reviewed_at"))
    )
    st.caption(
        f"Araştırma durumu: {workflow['research_status_label']}"
    )

intelligence = build_company_intelligence(
    candidate,
    scan_repo=scan_repo,
    is_watchlisted=is_watched,
    watchlist_note=(watchlist_entry or {}).get("notes") if watchlist_entry else None,
)

priority = intelligence.get("priority") or {}
history = intelligence.get("history_summary") or {}
timeline = intelligence.get("timeline") or []
badges = intelligence.get("badges") or []
data_quality = intelligence.get("data_quality") or {}

st.subheader("🎯 Araştırma Önceliği")
priority_label = priority.get("priority_label") or "—"
priority_score = priority.get("priority_score")
if priority_score is not None:
    st.markdown(
        f"**{priority_score:.0f} / {priority_label}**"
    )
else:
    st.markdown(f"**{priority_label}**")
st.caption(
    "Bu skor araştırma önceliğini gösterir; NABI Skoru veya scanner kararı "
    "ile aynı değildir."
)

priority_reasons = format_priority_reasons(priority.get("reasons") or [])
if priority_reasons:
    for reason in priority_reasons[:4]:
        st.markdown(f"• {reason}")
else:
    st.caption("Öncelik gerekçesi bulunmuyor.")

if badges:
    badge_line = format_badges_compact(badges)
    if badge_line:
        st.caption(badge_line)
for note in format_data_quality_notes(data_quality.get("notes") or [])[:2]:
    st.caption(note)

st.subheader("Karar özeti")
st.caption("Scanner Kararı")
decision = (
    candidate.get("decision_label")
    or candidate.get("decision")
    or "Karar üretilmedi."
)

if decision in {
    "ŞİMDİLİK UZAK DUR",
    "VERİ EKSİK — ÖN ELEME",
}:
    st.error(decision)
elif decision in {
    "YÜKSEK ÖNCELİKLİ ARAŞTIRMA ADAYI",
    "ARAŞTIRMA ADAYI",
}:
    st.success(decision)
else:
    st.warning(decision)

freshness_label = candidate.get("freshness_label")
if freshness_label:
    period_end = candidate.get("financial_period_end") or "—"
    period_age = candidate.get("period_age_days")
    age_text = f"{period_age} gün" if period_age is not None else "—"
    st.caption(
        f"Finansal dönem: {period_end} · {freshness_label} · {age_text}"
    )

st.write(
    candidate.get("decision_verdict")
    or candidate.get("memo_summary")
    or "Karar açıklaması bulunmuyor."
)
st.info(
    "**Önerilen araştırma adımı:** "
    + (
        candidate.get("decision_action")
        or "Ek finansal doğrulama yap."
    )
)

participation_history_result = fetch_participation_assessment_history(
    participation_repo,
    participation_symbol,
    limit=5,
)
participation_fmp_client = None
try:
    participation_fmp_client = FMPClient.from_streamlit_secrets()
except FMPError:
    pass

participation_sec_email = get_sec_contact_email()
participation_sec_lookup: dict = {}
try:
    participation_sec_lookup = load_sec_company_lookup(participation_sec_email)
except Exception:
    participation_sec_lookup = {}

participation_view = build_company_report_participation(
    candidate,
    sec_client=SECFinancialClient(contact_email=participation_sec_email),
    fmp_client=participation_fmp_client,
    persistence_available=participation_history_result.available,
    sec_ticker_lookup=participation_sec_lookup,
)
research_eligibility = evaluate_research_eligibility_from_participation_view(
    participation_view
)

company_intel_error = None
company_intel_view = None
if research_eligibility.research_allowed and symbol != "—":
    try:
        fmp_client = FMPClient.from_streamlit_secrets()
        company_intel_service = CompanyIntelligenceCoreService(fmp_client)
        company_intel_view = company_intel_service.build_view(
            str(symbol),
            research_eligibility=research_eligibility,
            sec_financials=(
                participation_view.result.sec_financials
                if participation_view.result is not None
                else None
            ),
            market_cap_fallback=candidate.get("market_cap"),
        )
    except FMPError as exc:
        company_intel_error = str(exc)
    except Exception as exc:
        company_intel_error = f"Şirket istihbaratı yüklenemedi: {exc}"

save_message_key = f"participation_save_message_{participation_symbol}"
save_skipped_key = f"participation_save_skipped_{participation_symbol}"
save_failed_key = f"participation_save_failed_{participation_symbol}"
save_clicked = render_company_report_participation_section(
    participation_view,
    history=participation_history_result.history,
    history_unavailable_message=(
        participation_history_result.message
        if not participation_history_result.available
        else None
    ),
    save_message=st.session_state.get(save_message_key),
    save_skipped_duplicate=st.session_state.get(save_skipped_key, False),
    save_failed=st.session_state.get(save_failed_key, False),
)
if save_clicked:
    save_result = save_participation_assessment_snapshot(
        participation_repo,
        participation_view,
    )
    st.session_state[save_message_key] = save_result.message
    st.session_state[save_skipped_key] = save_result.skipped_duplicate
    st.session_state[save_failed_key] = save_result.persistence_failed
    if save_result.saved or save_result.skipped_duplicate:
        st.rerun()

if not research_eligibility.research_allowed:
    render_research_eligibility_block(research_eligibility)
elif company_intel_view is not None:
    render_company_intelligence_sections(company_intel_view)
elif company_intel_error:
    st.info(f"Şirket istihbarat katmanı şu anda kullanılamıyor: {company_intel_error}")

investment_thesis_view = None
thesis_history_result = None
if research_eligibility.research_allowed and company_intel_view is not None:
    thesis_repo = InvestmentThesisRepository(client)
    thesis_history_result = fetch_investment_thesis_history(
        thesis_repo,
        participation_symbol,
        limit=5,
    )
    previous_snapshot = (
        thesis_history_result.history[0]
        if thesis_history_result.available and thesis_history_result.history
        else None
    )
    participation_context = None
    if participation_view.available and participation_view.result is not None:
        assessment = participation_view.result.participation_assessment
        participation_context = (
            f"Katılım durumu: {assessment.status} · "
            f"Güven: {assessment.confidence}"
        )
    investment_thesis_view = InvestmentThesisService().build_view(
        company_intel_view,
        research_eligibility=research_eligibility,
        candidate=candidate,
        participation_context=participation_context,
        previous_snapshot=previous_snapshot,
    )
    thesis_save_message_key = f"thesis_save_message_{participation_symbol}"
    thesis_save_skipped_key = f"thesis_save_skipped_{participation_symbol}"
    thesis_save_failed_key = f"thesis_save_failed_{participation_symbol}"
    thesis_save_clicked = render_investment_thesis_section(
        investment_thesis_view,
        history=thesis_history_result.history if thesis_history_result else (),
        history_unavailable_message=(
            thesis_history_result.message
            if thesis_history_result and not thesis_history_result.available
            else None
        ),
        save_message=st.session_state.get(thesis_save_message_key),
        save_skipped_duplicate=st.session_state.get(thesis_save_skipped_key, False),
        save_failed=st.session_state.get(thesis_save_failed_key, False),
    )
    render_investment_thesis_technical_details(investment_thesis_view)
    if thesis_save_clicked:
        thesis_save_result = save_investment_thesis_snapshot(
            thesis_repo,
            investment_thesis_view,
        )
        st.session_state[thesis_save_message_key] = thesis_save_result.message
        st.session_state[thesis_save_skipped_key] = thesis_save_result.skipped_duplicate
        st.session_state[thesis_save_failed_key] = thesis_save_result.persistence_failed
        if thesis_save_result.saved or thesis_save_result.skipped_duplicate:
            st.rerun()

    ai_summary_config = load_adviser_llm_config()
    ai_summary_service = AIResearchSummaryService(config=ai_summary_config)
    ai_summary_repo = AIResearchSummaryRepository(client)

    current_ai_identity = compute_context_semantic_identity(
        symbol=participation_symbol,
        participation_result=(
            participation_view.result
            if participation_view.result is not None
            else None
        ),
        company_intelligence_view=company_intel_view,
        investment_thesis_view=investment_thesis_view,
    )
    cached_ai_summary, cached_ai_identity = load_cached_ai_summary(participation_symbol)
    if cached_ai_summary and cached_ai_identity and cached_ai_identity != current_ai_identity:
        clear_ai_summary_cache(participation_symbol)
        cached_ai_summary = None
        cached_ai_identity = None

    active_ai_summary = cached_ai_summary
    if active_ai_summary is None:
        persisted_exact = fetch_exact_ai_research_summary(
            ai_summary_repo,
            participation_symbol,
            current_ai_identity,
        )
        if persisted_exact.view is not None:
            active_ai_summary = persisted_exact.view

    show_stale_ai_hint = False
    if active_ai_summary is None:
        show_stale_ai_hint = symbol_has_stale_persisted_summary(
            ai_summary_repo,
            participation_symbol,
            current_ai_identity,
        )

    def _polish_ai_summary_for_display(summary_view):
        if summary_view is None or summary_view.status != "AVAILABLE":
            return summary_view
        unified = ai_summary_service.build_unified_context(
            symbol=participation_symbol,
            research_eligibility=research_eligibility,
            company_intelligence_view=company_intel_view,
            investment_thesis_view=investment_thesis_view,
            candidate=candidate,
            participation_view=participation_view,
            previous_thesis_snapshot=previous_snapshot,
        )
        return polish_ai_research_summary_view(summary_view, unified=unified)

    if active_ai_summary is not None and active_ai_summary.status == "AVAILABLE":
        active_ai_summary = _polish_ai_summary_for_display(active_ai_summary)
        store_ai_summary(
            participation_symbol,
            active_ai_summary,
            identity=current_ai_identity,
        )

    def _generate_ai_summary():
        exact_match = fetch_exact_ai_research_summary(
            ai_summary_repo,
            participation_symbol,
            current_ai_identity,
        )
        if exact_match.view is not None:
            display_ready_summary = _polish_ai_summary_for_display(exact_match.view)
            store_ai_summary(
                participation_symbol,
                display_ready_summary,
                identity=current_ai_identity,
            )
            return display_ready_summary

        session_view, session_identity = load_cached_ai_summary(participation_symbol)
        generated_summary = ai_summary_service.generate(
            symbol=participation_symbol,
            research_eligibility=research_eligibility,
            company_intelligence_view=company_intel_view,
            investment_thesis_view=investment_thesis_view,
            candidate=candidate,
            participation_view=participation_view,
            previous_thesis_snapshot=previous_snapshot,
            cached_view=session_view,
            cached_identity=session_identity,
            force_refresh=False,
        )
        display_ready_summary = _polish_ai_summary_for_display(generated_summary)
        if generated_summary.status == "AVAILABLE":
            save_ai_research_summary_snapshot(
                ai_summary_repo,
                display_ready_summary,
                semantic_identity=current_ai_identity,
            )
        store_ai_summary(
            participation_symbol,
            display_ready_summary,
            identity=current_ai_identity,
        )
        return display_ready_summary

    render_ai_research_summary_section(
        view=active_ai_summary,
        feature_enabled=ai_summary_config.is_usable,
        symbol=participation_symbol,
        generate_callback=_generate_ai_summary if ai_summary_config.is_usable else None,
        display_polish_callback=_polish_ai_summary_for_display if ai_summary_config.is_usable else None,
        stale_context_hint=show_stale_ai_hint,
    )
    if os.environ.get("NABI_AI_SUMMARY_TRACE", "").strip().lower() in {"1", "true", "yes"}:
        trace = get_last_ai_summary_generation_trace()
        if trace:
            with st.expander("AI özet üretim izi (debug)", expanded=False):
                st.json(trace)

st.subheader("🔄 Son taramalarda ne değişti?")
history_events = history.get("events") or []
if not history_events:
    if history.get("history_count", 0) == 0:
        st.info("Son 7 günde bu sembol için tarama geçmişi bulunamadı.")
    else:
        st.info("Son 7 günde anlamlı değişiklik bulunamadı.")
else:
    st.caption(
        format_change_window_summary(
            history.get("window_change_score", 0),
            history_events,
        )
    )
    for event in history_events[:6]:
        severity = event.get("severity") or "—"
        date_label = format_datetime_tr(event.get("occurred_at"))
        st.markdown(f"**{date_label}** · {severity} — {event.get('message')}")

if timeline:
    st.subheader("📅 Araştırma zaman çizelgesi")
    for item in timeline[:8]:
        st.markdown(f"**{item['date_label']}** — {item['message']}")

with st.expander("Scanner v1 tez özeti (eski)"):
    st.info(
        candidate.get("thesis_type")
        or "Bu kayıt eski scanner tez motoru ile henüz analiz edilmedi."
    )
    st.write(candidate.get("thesis_summary") or "Yatırım tezi özeti bulunmuyor.")
    strengths = candidate.get("thesis_strengths") or []
    concerns = candidate.get("thesis_concerns") or []
    if strengths:
        st.markdown("**Destekleyen:**")
        for item in strengths:
            st.success(item)
    if concerns:
        st.markdown("**Zayıflatan:**")
        for item in concerns:
            st.error(item)

st.subheader("Puanın kanıtları")
factors = candidate.get("score_factors") or []

if factors:
    factor_rows = []

    for item in factors:
        impact = item.get("impact")
        impact_label = {
            "positive": "Olumlu",
            "negative": "Olumsuz",
            "neutral": "Nötr",
        }.get(impact, impact or "—")

        factor_rows.append({
            "Gösterge": item.get("label"),
            "Değer": item.get("value"),
            "Etkisi": impact_label,
            "Ne anlatıyor?": item.get("meaning"),
            "NABI yorumu": item.get("summary"),
        })

    st.dataframe(
        pd.DataFrame(factor_rows),
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info(
        "Puan gerekçeleri için şirketi güncel Scanner ile yeniden tarayın."
    )

st.subheader("Finansal göstergeler")
metric_map = [
    ("ROIC", "roic"),
    ("Gelir CAGR 3Y", "revenue_cagr_3y"),
    ("EPS CAGR 3Y", "eps_cagr_3y"),
    ("FCF CAGR 3Y", "fcf_cagr_3y"),
    ("FCF Marjı", "free_cash_flow_margin"),
    ("Borç/Özsermaye", "debt_to_equity"),
    ("Faiz Karşılama", "interest_coverage"),
    ("F/K", "pe_ratio"),
    ("EV/EBIT", "ev_to_ebit"),
    ("PEG", "peg_ratio_calculated"),
    ("Fiyat/FCF", "price_to_fcf"),
]

columns = st.columns(4)

for index, (label, key) in enumerate(metric_map):
    value = candidate.get(key)
    columns[index % 4].metric(
        label,
        "—" if value is None else f"{value:.2f}",
    )

st.subheader("🎓 NABI Academy — Bu rakamlar ne anlatıyor?")
st.caption(
    "Her kart finansal metriği sade dille açıklar ve bu şirket için yorumlar."
)

academy_tabs = st.tabs([
    "Kalite",
    "Büyüme",
    "Borç ve Güç",
    "Değerleme",
])

with academy_tabs[0]:
    render_metric_card(
        "roic",
        candidate.get("roic"),
    )
    render_metric_card(
        "free_cash_flow_margin",
        candidate.get("free_cash_flow_margin"),
    )

with academy_tabs[1]:
    render_metric_card(
        "revenue_cagr_3y",
        candidate.get("revenue_cagr_3y"),
    )
    render_metric_card(
        "eps_cagr_3y",
        candidate.get("eps_cagr_3y"),
    )
    render_metric_card(
        "fcf_cagr_3y",
        candidate.get("fcf_cagr_3y"),
    )

with academy_tabs[2]:
    render_metric_card(
        "debt_to_equity",
        candidate.get("debt_to_equity"),
    )
    render_metric_card(
        "interest_coverage",
        candidate.get("interest_coverage"),
    )

with academy_tabs[3]:
    render_metric_card(
        "pe_ratio",
        candidate.get("pe_ratio"),
    )
    render_metric_card(
        "ev_to_ebit",
        candidate.get("ev_to_ebit"),
    )
    render_metric_card(
        "peg_ratio_calculated",
        candidate.get("peg_ratio_calculated"),
    )
    render_metric_card(
        "price_to_fcf",
        candidate.get("price_to_fcf"),
    )

st.subheader("Raporun veri güveni")
render_metric_explanation(
    "data_completeness",
    candidate.get("data_completeness"),
    expanded=True,
)

st.caption(
    "NABI Academy yatırım tavsiyesi üretmez. "
    "Finansal metrikleri sade ve açıklanabilir hâle getirir."
)
