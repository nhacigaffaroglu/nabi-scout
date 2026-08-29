import pandas as pd
import streamlit as st

from services.auth_service import get_current_user_id
from services.fmp_client import FMPClient, FMPError
from services.nabi_intelligence_facade import get_investment_intelligence
from services.ui import prepare_protected_page
from services.ui_formatters import format_date_dmy
from services.wealth_benchmark_service import WealthBenchmarkService
from services.wealth_comparison_chart import (
    build_benchmark_comparison_altair_chart,
    build_benchmark_comparison_chart_frame,
)
from services.wealth_contract import (
    ACCOUNT_TYPE_BROKERAGE,
    ACCOUNT_TYPE_CASH,
    ACCOUNT_TYPE_OTHER,
    ACCOUNT_TYPE_RETIREMENT,
    ASSET_CLASS_CASH,
    ASSET_CLASS_EQUITY,
    ASSET_CLASS_ETF,
    ASSET_CLASS_FUND,
    ASSET_CLASS_OTHER,
    TXN_TYPES,
    TXN_TYPE_BUY,
    TXN_TYPE_SELL,
    WealthMaterializationError,
    WealthValidationError,
)
from services.wealth_core_service import WealthCoreService
from services.wealth_adviser_config import load_adviser_llm_config
from services.wealth_adviser_conversation import (
    adviser_response_cache_key,
    clear_conversation_history,
    conversation_session_key,
    get_conversation_history,
    record_chat_exchange,
)
from services.wealth_adviser_preference_engine import build_adviser_user_context
from services.wealth_adviser_profile_contract import GoalType, InvestorProfile
from services.wealth_adviser_service import WealthAdviserService
from services.wealth_adviser_profile_service import (
    GOAL_TYPE_OPTIONS,
    PROFILE_ENUM_OPTIONS,
    WealthAdviserGoalService,
    WealthAdviserProfileService,
)
from repositories.candidate_repository import CandidateRepository
from repositories.participation_assessment_repository import (
    ParticipationAssessmentRepository,
)
from services.candidate_surface_service import filter_equity_candidate_surface
from services.participation_authority import overlay_candidate_rows
from services.wealth_diagnostics_contract import DiagnosticCategory, DiagnosticSeverity
from services.wealth_diagnostics_engine import effective_position_count
from services.wealth_diagnostics_service import WealthDiagnosticsService
from services.canonical_current_valuation import build_canonical_current_view
from services.wealth_timeline_service import WealthTimelineService
from components.nabi_adviser_ui import render_nabi_adviser
from components.wealth_brief_ui import compose_wealth_operating_views
from services.portfolio_allocation_policy_service import PortfolioAllocationPolicyService


from components.portfolio_holdings_ui import render_valuation_holdings_analysis
from components.wealth_command_center_ui import render_wealth_command_center
from components.wealth_goal_center_ui import render_wealth_goal_center
from components.wealth_history_ui import render_wealth_history
from components.wealth_institution_center_ui import render_institution_center
from components.wealth_purification_zakat_ui import render_purification_zakat_center
from services.wealth_external_cash_flow import contribution_reconciliations_for_wealth
from services.wealth_history_service import build_wealth_history


def _format_money(value, currency: str) -> str:
    if value is None:
        return "—"
    return f"{value:,.2f} {currency}"


def _load_benchmark_service() -> WealthBenchmarkService:
    try:
        fmp = FMPClient.from_streamlit_secrets()
    except FMPError:
        fmp = None
    return WealthBenchmarkService(fmp)


def _render_allocation(title: str, slices, currency: str) -> None:
    if not slices:
        return
    st.markdown(f"**{title}**")
    for row in slices:
        st.progress(min(max(row.weight_pct / 100.0, 0.0), 1.0))
        st.caption(
            f"{row.label}: {_format_money(row.market_value, currency)} "
            f"({row.weight_pct:.1f}%)"
        )


client = prepare_protected_page("Wealth | NABI Scout", "💰")

if st.button("Portföy Zekâsı'na git", key="wealth_go_pi"):
    st.switch_page("pages/11_Portfolio_Intelligence.py")
st.caption("Şimdi neye odaklanmalıyım? → **Portföy Zekâsı**")
st.divider()

user_id = get_current_user_id(client)
wealth = WealthCoreService(client, user_id)
timeline = WealthTimelineService(wealth)
diagnostics_service = WealthDiagnosticsService(wealth)
adviser_service = WealthAdviserService()
candidate_repo = CandidateRepository(client)
adviser_profile_service = WealthAdviserProfileService(client, user_id)
adviser_goal_service = WealthAdviserGoalService(client, user_id)
adviser_llm_config = load_adviser_llm_config()


def _severity_badge(severity: DiagnosticSeverity) -> str:
    if severity == DiagnosticSeverity.HIGH:
        return "🔴 Yüksek"
    if severity == DiagnosticSeverity.WATCH:
        return "🟡 İzle"
    return "🔵 Bilgi"


def _top3_position_count(diagnostic) -> int:
    symbols = list(diagnostic.affected_symbols or diagnostic.evidence.get("symbols") or [])
    return len(symbols)


def _display_diagnostic_title(diagnostic) -> str:
    if diagnostic.code in {"CONCENTRATION_TOP3_HIGH", "CONCENTRATION_TOP3_WATCH"}:
        count = _top3_position_count(diagnostic)
        if count <= 1:
            return "En büyük pozisyon yoğunlaşması"
        if count == 2:
            return "En büyük 2 pozisyon yoğunlaşması"
    return diagnostic.title


def _display_diagnostic_summary(diagnostic) -> str:
    if diagnostic.code in {"CONCENTRATION_TOP3_HIGH", "CONCENTRATION_TOP3_WATCH"}:
        count = _top3_position_count(diagnostic)
        pct = diagnostic.metric_value
        if pct is not None:
            if count <= 1:
                return f"En büyük fiyatlı pozisyon toplam ağırlığı %{pct:.1f}."
            if count == 2:
                return f"En büyük iki fiyatlı pozisyon toplam ağırlığı %{pct:.1f}."
    return diagnostic.summary


def _render_diagnostic_card(diagnostic) -> None:
    title = _display_diagnostic_title(diagnostic)
    with st.expander(f"{_severity_badge(diagnostic.severity)} · {title}"):
        st.write(_display_diagnostic_summary(diagnostic))
        symbols = [symbol for symbol in (diagnostic.affected_symbols or []) if symbol]
        if symbols:
            st.caption(f"Semboller: {', '.join(symbols)}")
        with st.expander("Teknik ayrıntılar"):
            st.caption(f"Kod: `{diagnostic.code}`")
            st.caption(f"Kategori: {diagnostic.category.value}")
            st.caption(f"Önem seviyesi: {diagnostic.severity.value}")
            st.caption(f"Güven: {diagnostic.confidence.value}")
            st.caption(f"Kaynak: {diagnostic.source}")
            if symbols:
                st.caption(f"Etkilenen semboller: {', '.join(symbols)}")
            if diagnostic.metric_value is not None:
                st.caption(f"Metrik değeri: {diagnostic.metric_value}")
            if diagnostic.threshold is not None:
                st.caption(f"Eşik: {diagnostic.threshold}")
            if diagnostic.evidence:
                st.json(diagnostic.evidence)

def _render_adviser_finding(finding) -> None:
    with st.expander(f"{finding.title}"):
        st.write(finding.statement)
        if finding.affected_symbols:
            st.caption(f"Semboller: {', '.join(finding.affected_symbols)}")
        if finding.limitations:
            for note in finding.limitations:
                st.caption(f"Not: {note}")


def _render_adviser_response(response) -> None:
    if response.grounded:
        st.success("AI yorumu deterministik verilerle doğrulandı.")
    else:
        st.info(
            "Deterministik yedek yanıt gösteriliyor; AI yorumu doğrulanamadı "
            "veya kullanılamıyor."
        )
    st.markdown(response.answer)
    if response.key_points:
        st.markdown("**Ana noktalar**")
        for point in response.key_points:
            st.write(f"- {point}")
    if response.referenced_finding_ids:
        st.caption(
            "Referans verilen bulgular: "
            + ", ".join(response.referenced_finding_ids)
        )
    if response.limitations:
        st.markdown("**Sınırlamalar**")
        for note in response.limitations:
            st.write(f"- {note}")
    if response.follow_up_questions:
        st.markdown("**Takip soruları**")
        for question in response.follow_up_questions:
            st.write(f"- {question}")
    if response.options_to_consider:
        st.markdown("**Değerlendirilebilecek seçenekler**")
        for option in response.options_to_consider:
            st.write(f"- {option}")
    if response.safety_flags:
        st.caption(f"Güvenlik bayrakları: {', '.join(response.safety_flags)}")
    st.caption(
        f"Kaynak: {'AI yorumu (doğrulandı)' if response.grounded else 'Deterministik yedek'} · "
        f"Model: {response.model_name}"
    )


st.title("NABI Wealth")

portfolio = wealth.ensure_default_portfolio()
summary = wealth.get_summary()
portfolio_view = build_canonical_current_view(
    wealth,
    enrich_nabi=True,
    portfolio=portfolio,
)

tab_summary, tab_goal, tab_history, tab_institutions, tab_purification, tab_accounts, tab_assets, tab_txn, tab_positions, tab_liabilities, tab_analysis, tab_adviser = st.tabs(
    [
        "Özet",
        "2031 Hedef",
        "Performans",
        "Kurum Merkezi",
        "Arındırma & Zekât",
        "Hesaplar",
        "Varlıklar",
        "İşlemler",
        "Pozisyonlar",
        "Borçlar",
        "Analiz",
        "Danışman",
    ]
)

accounts = wealth.list_accounts()
assets = wealth.list_assets()
positions = wealth.list_positions()
liabilities = wealth.list_liabilities()
transactions = wealth.list_transactions(limit=50)

account_by_id = {row["id"]: row for row in accounts}
asset_by_id = {row["id"]: row for row in assets}

with tab_summary:
    if portfolio_view.total_position_count == 0 and not accounts and not liabilities:
        st.info("Henüz wealth kaydı yok. Hesap ve varlık ekleyerek başlayın.")
    try:
        command_candidates = list(candidate_repo.get_all(limit=500) or [])
    except Exception:
        command_candidates = []
    render_wealth_command_center(
        portfolio_view=portfolio_view,
        wealth=wealth,
        accounts=accounts,
        assets=assets,
        positions=positions,
        candidates=command_candidates,
        snapshots=timeline.list_snapshots(str(portfolio.get("id") or ""), limit=50),
        transactions=wealth.list_transactions(limit=2000),
        account_ids=[str(row.get("id") or "") for row in accounts],
        portfolio_id=str(portfolio.get("id") or ""),
        summary=summary,
        liabilities=liabilities,
    )

with tab_goal:
    render_wealth_goal_center(
        portfolio_view=portfolio_view,
        wealth=wealth,
        accounts=accounts,
    )

with tab_institutions:
    render_institution_center(
        portfolio_view=portfolio_view,
        accounts=accounts,
    )

with tab_purification:
    render_purification_zakat_center(
        portfolio_view=portfolio_view,
        accounts=accounts,
        assets=assets,
        transactions=wealth.list_transactions(limit=2000),
    )

with tab_accounts:
    st.subheader("Hesap oluştur")
    with st.form("wealth_create_account"):
        account_name = st.text_input("Hesap adı")
        account_type = st.selectbox(
            "Hesap türü",
            [
                ACCOUNT_TYPE_BROKERAGE,
                ACCOUNT_TYPE_CASH,
                ACCOUNT_TYPE_RETIREMENT,
                ACCOUNT_TYPE_OTHER,
            ],
        )
        account_currency = st.text_input("Para birimi", value="USD")
        institution = st.text_input("Kurum (opsiyonel)")
        submitted_account = st.form_submit_button("Hesap ekle", type="primary")
    if submitted_account:
        if not account_name.strip():
            st.error("Hesap adı gerekli.")
        else:
            try:
                created = wealth.create_account(
                    name=account_name,
                    account_type=account_type,
                    currency=account_currency,
                    institution=institution or None,
                )
                st.success(f"Hesap oluşturuldu: {created.get('name')}")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    st.divider()
    if not accounts:
        st.info("Henüz hesap yok.")
    else:
        for row in accounts:
            st.write(
                f"**{row.get('name')}** · {row.get('account_type')} · "
                f"{row.get('currency')}"
            )

with tab_assets:
    st.subheader("Varlık kaydı")
    with st.form("wealth_register_asset"):
        symbol = st.text_input("Sembol", placeholder="AAPL")
        market = st.text_input("Piyasa", value="US")
        asset_class = st.selectbox(
            "Varlık sınıfı",
            [
                ASSET_CLASS_EQUITY,
                ASSET_CLASS_ETF,
                ASSET_CLASS_FUND,
                ASSET_CLASS_CASH,
                ASSET_CLASS_OTHER,
            ],
        )
        asset_currency = st.text_input("Para birimi", value="USD", key="asset_currency")
        asset_name = st.text_input("Ad (opsiyonel)")
        submitted_asset = st.form_submit_button("Varlık ekle", type="primary")
    if submitted_asset:
        if not symbol.strip():
            st.error("Sembol gerekli.")
        else:
            try:
                created = wealth.register_asset(
                    symbol=symbol,
                    market=market,
                    asset_class=asset_class,
                    currency=asset_currency,
                    name=asset_name or None,
                )
                st.success(f"Varlık kaydedildi: {created.get('symbol')}")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    st.divider()
    if not assets:
        st.info("Henüz varlık yok.")
    else:
        for row in assets:
            intel = get_investment_intelligence(client, row.get("symbol", ""))
            label = (
                f"**{row.get('symbol')}** · {row.get('asset_class')} · "
                f"{row.get('market')}"
            )
            if intel.has_candidate:
                label += f" · NABI: {intel.decision or '—'}"
            st.write(label)

with tab_txn:
    st.subheader("İşlem girişi")
    st.caption(
        "Alış/satış yalnızca seçilen varlık pozisyonunu etkiler. "
        "Nakit hareketleri için ayrı yatırma/çekme işlemi girin."
    )
    if not accounts:
        st.warning("Önce en az bir hesap oluşturun.")
    elif not assets:
        st.warning("Önce en az bir varlık kaydedin.")
    else:
        with st.form("wealth_post_transaction"):
            account_id = st.selectbox(
                "Hesap",
                options=[row["id"] for row in accounts],
                format_func=lambda value: account_by_id[value]["name"],
            )
            asset_id = st.selectbox(
                "Varlık",
                options=[row["id"] for row in assets],
                format_func=lambda value: asset_by_id[value]["symbol"],
            )
            txn_type = st.selectbox("İşlem türü", list(TXN_TYPES))
            quantity = st.number_input("Miktar", min_value=0.0, value=0.0, step=1.0)
            price = st.number_input("Birim fiyat", min_value=0.0, value=0.0, step=0.01)
            is_trade = txn_type in {TXN_TYPE_BUY, TXN_TYPE_SELL}
            if is_trade:
                st.caption("Alış/satış tutarı otomatik hesaplanır: miktar × birim fiyat.")
                computed_preview = quantity * price if quantity > 0 and price > 0 else 0.0
                st.write(f"Hesaplanan tutar: **{computed_preview:.2f}**")
                amount = 0.0
            else:
                amount = st.number_input("Tutar", min_value=0.0, value=0.0, step=1.0)
            txn_currency = st.text_input("İşlem para birimi", value="USD")
            notes = st.text_input("Not (opsiyonel)")
            submitted_txn = st.form_submit_button("İşlem kaydet", type="primary")

        if submitted_txn:
            if is_trade:
                if quantity <= 0:
                    st.error("Alış/satış için miktar gerekli.")
                elif price <= 0:
                    st.error("Alış/satış için birim fiyat gerekli.")
                else:
                    computed_amount = quantity * price
                    try:
                        wealth.post_transaction(
                            account_id=account_id,
                            asset_id=asset_id,
                            txn_type=txn_type,
                            quantity=quantity,
                            price=price,
                            amount=computed_amount,
                            currency=txn_currency,
                            notes=notes or None,
                        )
                        st.success("İşlem kaydedildi; pozisyon güncellendi.")
                        st.rerun()
                    except WealthValidationError as exc:
                        st.error(str(exc))
                    except WealthMaterializationError as exc:
                        st.error(str(exc))
                    except Exception as exc:
                        st.error(str(exc))
            else:
                computed_amount = amount
                if computed_amount <= 0 and quantity > 0:
                    computed_amount = quantity
                try:
                    wealth.post_transaction(
                        account_id=account_id,
                        asset_id=asset_id,
                        txn_type=txn_type,
                        quantity=quantity,
                        price=price if price > 0 else None,
                        amount=computed_amount,
                        currency=txn_currency,
                        notes=notes or None,
                    )
                    st.success("İşlem kaydedildi; pozisyon güncellendi.")
                    st.rerun()
                except WealthValidationError as exc:
                    st.error(str(exc))
                except WealthMaterializationError as exc:
                    st.error(str(exc))
                except Exception as exc:
                    st.error(str(exc))

    st.divider()
    st.markdown("**Son işlemler**")
    if not transactions:
        st.info("Henüz işlem yok.")
    else:
        reversed_original_ids = wealth.collect_reversed_original_ids(transactions)
        for row in transactions:
            asset = asset_by_id.get(row.get("asset_id"), {})
            account = account_by_id.get(row.get("account_id"), {})
            txn_id = str(row.get("id") or "")
            label = (
                f"{format_date_dmy(row.get('executed_at'))} · {row.get('txn_type')} · "
                f"{asset.get('symbol', '?')} @ {account.get('name', '?')} · "
                f"qty={row.get('quantity')} amount={row.get('amount')}"
            )
            if row.get("reversal_of_id"):
                label += " · ters kayıt"
            cols = st.columns([5, 1])
            cols[0].write(f"- {label}")
            if wealth.is_transaction_reversal_eligible(row, reversed_original_ids):
                if cols[1].button("Geri Al", key=f"wealth_reverse_{txn_id}"):
                    try:
                        wealth.reverse_transaction(txn_id)
                        st.success("İşlem geri alındı; pozisyon güncellendi.")
                        st.rerun()
                    except WealthValidationError as exc:
                        st.error(str(exc))
                    except WealthMaterializationError as exc:
                        st.error(str(exc))
                    except Exception as exc:
                        st.error(str(exc))

with tab_positions:
    st.subheader("Güncel pozisyonlar")
    if not positions:
        st.info("Henüz açık pozisyon yok.")
    else:
        base_ccy = portfolio_view.base_currency
        if portfolio_view.mixed_currency_warning:
            st.warning(
                "Baz para birimi dışı pozisyonlar yerel para biriminde gösterilir; "
                "portföy toplamlarına dahil değildir."
            )

        all_positions = (
            list(portfolio_view.priced_positions)
            + list(portfolio_view.unpriced_positions)
            + list(portfolio_view.foreign_currency_positions)
        )
        render_valuation_holdings_analysis(all_positions, currency=base_ccy)
        st.divider()

        st.markdown("**Fiyatlı pozisyonlar**")
        if not portfolio_view.priced_positions:
            st.info("Fiyatlı pozisyon yok.")
        else:
            for row in portfolio_view.priced_positions:
                pl_label = _format_money(row.unrealized_pl, row.valuation_currency)
                weight = f"{row.weight_pct:.1f}%" if row.weight_pct is not None else "—"
                nabi_label = ""
                if row.nabi and row.nabi.has_candidate:
                    nabi_label = (
                        f" · NABI {row.nabi.decision or '—'}"
                        f" ({row.nabi.nabi_score or '—'})"
                    )
                st.write(
                    f"**{row.symbol}** · {row.account_name} · "
                    f"miktar={row.quantity} · ort. maliyet={row.average_cost} · "
                    f"fiyat={_format_money(row.price, row.valuation_currency)} · "
                    f"piyasa değeri={_format_money(row.market_value, row.valuation_currency)} · "
                    f"K/Z={pl_label} · ağırlık={weight}{nabi_label}"
                )

        if portfolio_view.unpriced_positions:
            st.markdown("**Fiyatı olmayan pozisyonlar**")
            for row in portfolio_view.unpriced_positions:
                st.write(
                    f"**{row.symbol}** · {row.account_name} · "
                    f"miktar={row.quantity} · ort. maliyet={row.average_cost} "
                    f"{row.valuation_currency} · _fiyat mevcut değil_"
                )

        if portfolio_view.foreign_currency_positions:
            st.markdown("**Farklı para birimi (toplama dahil değil)**")
            for row in portfolio_view.foreign_currency_positions:
                if row.price_available:
                    st.write(
                        f"**{row.symbol}** · {row.account_name} · "
                        f"miktar={row.quantity} · "
                        f"piyasa değeri={_format_money(row.market_value, row.valuation_currency)} "
                        f"({row.valuation_currency})"
                    )
                else:
                    st.write(
                        f"**{row.symbol}** · {row.account_name} · "
                        f"miktar={row.quantity} · _fiyat mevcut değil_ "
                        f"({row.valuation_currency})"
                    )

with tab_liabilities:
    st.subheader("Borç ekle")
    with st.form("wealth_create_liability"):
        liability_name = st.text_input("Borç adı")
        liability_type = st.text_input("Borç türü", value="loan")
        liability_currency = st.text_input("Para birimi", value="USD", key="liability_currency")
        principal = st.number_input("Anapara", min_value=0.0, value=0.0, step=100.0)
        liability_notes = st.text_input("Not (opsiyonel)")
        submitted_liability = st.form_submit_button("Borç ekle", type="primary")
    if submitted_liability:
        if not liability_name.strip():
            st.error("Borç adı gerekli.")
        else:
            try:
                created = wealth.create_liability(
                    name=liability_name,
                    liability_type=liability_type,
                    currency=liability_currency,
                    principal=principal,
                    portfolio_id=portfolio.get("id"),
                    notes=liability_notes or None,
                )
                st.success(f"Borç kaydedildi: {created.get('name')}")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    st.divider()
    if not liabilities:
        st.info("Henüz borç kaydı yok.")
    else:
        for row in liabilities:
            st.write(
                f"**{row.get('name')}** · {row.get('liability_type')} · "
                f"{row.get('principal')} {row.get('currency')}"
            )

with tab_history:
    if st.button("Anlık görüntü kaydet", type="primary", key="wealth_save_snapshot"):
        try:
            saved = timeline.save_snapshot_from_view(portfolio, portfolio_view)
            st.success(
                f"Görüntü kaydedildi: {_format_money(saved.priced_market_value, saved.base_currency)} "
                f"@ {format_date_dmy(saved.captured_at)}"
            )
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    st.caption("Anlık görüntüler yalnızca açıkça kaydedildiğinde oluşturulur.")

    timeline_view = timeline.build_timeline_view(portfolio)
    performance_view = timeline.build_performance_view(portfolio)
    history_txns = wealth.list_transactions(limit=2000)
    history_account_ids = [str(row.get("id") or "") for row in accounts]
    history_recons = contribution_reconciliations_for_wealth(
        wealth, str(portfolio["id"])
    )
    history_view = build_wealth_history(
        timeline_view.snapshots,
        transactions=history_txns,
        account_ids=history_account_ids,
        contribution_reconciliations=history_recons,
        portfolio_id=str(portfolio["id"]),
    )
    render_wealth_history(
        history_view,
        snapshots=timeline_view.snapshots,
        transactions=history_txns,
        account_ids=history_account_ids,
        contribution_reconciliations=history_recons,
        portfolio_id=str(portfolio["id"]),
    )

    with st.expander("Kayıt ve teknik geçmiş", expanded=False):
        if timeline_view.snapshots:
            st.markdown("**Son görüntüler**")
            for snap in timeline_view.snapshots[:10]:
                partial_note = ""
                if snap.unpriced_position_count or snap.mixed_currency_warning:
                    partial_note = " · kısmi"
                st.write(
                    f"- {format_date_dmy(snap.captured_at)} · "
                    f"{_format_money(snap.priced_market_value, snap.base_currency)} · "
                    f"kapsam {snap.priced_position_coverage_pct:.0f}%"
                    f"{partial_note}"
                )

        linked = performance_view.linked_performance
        if linked is not None:
            st.markdown("**Zincirlenmiş dönem getirisi**")
            st.caption(
                "Fiyatlı baz para birimi portföyü; dış akışlar (yatırım/çekim) ayıklanmış "
                "alt dönem getirilerinin Modified Dietz ile zincirlenmesi."
            )
            st.write(
                f"{format_date_dmy(linked.period_start_at)} → {format_date_dmy(linked.period_end_at)}"
            )
            if linked.performance_comparable and linked.linked_return_pct is not None:
                st.metric(
                    "Portföy dönem getirisi",
                    f"{linked.linked_return_pct:.2f}%",
                )
            else:
                st.warning(
                    "Portföy dönem getirisi tam karşılaştırılabilir değil; "
                    "eksik veya kısmi veri nedeniyle yüzde gösterilmiyor."
                )
                for warning in linked.warnings:
                    st.write(f"- {warning}")

        if len(timeline_view.snapshots) >= 2:
            st.markdown("**Tarihsel karşılaştırma (portföy vs SPY)**")
            st.caption(
                "Normalleştirilmiş seriler ilk karşılaştırılabilir görüntüde 100'e "
                "ölçeklenir. Yalnızca bilgilendirme amaçlı tarihsel karşılaştırmadır."
            )
            benchmark_service = _load_benchmark_service()
            fetch_before = benchmark_service.fetch_count
            benchmark_view = timeline.build_benchmark_comparison(
                portfolio,
                performance_view,
                benchmark_service,
            )
            provider_calls = benchmark_service.fetch_count - fetch_before

            if benchmark_view.performance_comparable:
                comparison_df = build_benchmark_comparison_chart_frame(
                    benchmark_view.portfolio_normalized,
                )
                st.altair_chart(
                    build_benchmark_comparison_altair_chart(comparison_df),
                    use_container_width=True,
                )

                c1, c2, c3 = st.columns(3)
                if benchmark_view.portfolio_return_pct is not None:
                    c1.metric(
                        "Portföy getirisi",
                        f"{benchmark_view.portfolio_return_pct:.2f}%",
                    )
                if benchmark_view.benchmark_return_pct is not None:
                    c2.metric(
                        f"{benchmark_view.benchmark_symbol} getirisi",
                        f"{benchmark_view.benchmark_return_pct:.2f}%",
                    )
                if benchmark_view.relative_return_pct is not None:
                    c3.metric(
                        "Göreli tarihsel performans",
                        f"{benchmark_view.relative_return_pct:+.2f} puan",
                    )
            else:
                st.warning(
                    "SPY karşılaştırması tam karşılaştırılabilir değil; "
                    "eksik benchmark fiyatı veya portföy veri kalitesi."
                )
                for warning in benchmark_view.warnings:
                    st.write(f"- {warning}")

            st.caption(f"Karşılaştırma fiyat çağrısı: {provider_calls}")

with tab_analysis:
    st.subheader("Portföy analizi")
    st.caption(
        "Deterministik yapısal tanılar; kişiselleştirilmiş yatırım kararı veya "
        "alım/satım yönlendirmesi içermez."
    )

    analysis_performance_view = timeline.build_performance_view(portfolio)
    diagnostics_view = diagnostics_service.build_diagnostics_view(
        portfolio,
        portfolio_view,
        performance_view=analysis_performance_view,
        benchmark_view=None,
    )

    view = portfolio_view
    if diagnostics_view.data_quality_ok:
        st.success(
            f"Analiz kapsamı: {view.priced_position_count}/{view.total_position_count} "
            f"fiyatlı pozisyon · {view.base_currency} baz · tam kapsam"
        )
    else:
        st.warning(
            f"Analiz kısmi: {view.unpriced_position_count} pozisyon fiyatlanamadı · "
            f"kapsam %{view.health.priced_position_coverage_pct:.0f}"
        )

    st.markdown("**Öne çıkanlar**")
    if not diagnostics_view.diagnostics:
        st.info("Üretilen tanı yok.")
    else:
        for diagnostic in diagnostics_view.diagnostics:
            if diagnostic.severity in {DiagnosticSeverity.HIGH, DiagnosticSeverity.WATCH}:
                _render_diagnostic_card(diagnostic)
        info_items = [
            item
            for item in diagnostics_view.diagnostics
            if item.severity == DiagnosticSeverity.INFO
        ]
        if info_items:
            with st.expander(f"Bilgi düzeyi tanılar ({len(info_items)})"):
                for diagnostic in info_items:
                    _render_diagnostic_card(diagnostic)

    st.divider()
    st.markdown("**Yoğunlaşma**")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(
        "En büyük pozisyon",
        f"{view.health.largest_position_weight_pct:.1f}%",
    )
    c2.metric(
        "İlk 3 yoğunlaşma",
        f"{view.health.top3_concentration_pct:.1f}%",
    )
    effective = effective_position_count(view)
    c3.metric(
        "Etkin pozisyon sayısı",
        f"{effective:.2f}" if effective is not None else "—",
    )
    c4.metric(
        "Varlık sınıfı yoğunlaşması",
        f"{view.health.largest_asset_class_concentration_pct:.1f}%",
    )

    st.divider()
    st.markdown("**Performans yapısı**")
    invested_rows = [
        row
        for row in view.priced_positions
        if row.included_in_base_totals and not row.is_cash and row.unrealized_pl is not None
    ]
    profitable = sum(1 for row in invested_rows if row.unrealized_pl > 0)
    losing = sum(1 for row in invested_rows if row.unrealized_pl < 0)
    p1, p2 = st.columns(2)
    p1.metric("Kârlı pozisyon", profitable)
    p2.metric("Zararda pozisyon", losing)

    drawdown_diag = next(
        (
            item
            for item in diagnostics_view.diagnostics
            if item.code == "DRAWDOWN_PERFORMANCE"
        ),
        None,
    )
    if drawdown_diag is not None:
        st.caption(
            "Performans endeksi drawdown: "
            f"güncel {drawdown_diag.evidence.get('current_drawdown_pct', 0):.2f}%, "
            f"maksimum {drawdown_diag.evidence.get('max_observed_drawdown_pct', 0):.2f}%"
        )
    else:
        st.caption(
            "Performans endeksi drawdown yalnızca karşılaştırılabilir zincirlenmiş "
            "getiri geçmişi olduğunda gösterilir."
        )

    st.divider()
    st.markdown("**Benchmark**")
    if diagnostics_view.benchmark_available:
        st.caption("Benchmark tanıları mevcut görünümden türetildi.")
    else:
        st.info(
            "SPY tarihsel karşılaştırması bu sekmede yüklenmedi. "
            "Geçmiş sekmesindeki karşılaştırma görünümü sağlandığında "
            "benchmark tanıları türetilebilir."
        )

    st.divider()
    st.markdown("**NABI bağlamı**")
    st.caption(
        "NABI verileri portföy değerleme veya getiri hesaplarını değiştirmez."
    )
    nabi_items = [
        item
        for item in diagnostics_view.diagnostics
        if item.category == DiagnosticCategory.NABI_CONTEXT
    ]
    if not nabi_items:
        st.info("NABI bağlam tanısı üretilmedi.")
    else:
        for diagnostic in nabi_items:
            _render_diagnostic_card(diagnostic)

with tab_adviser:
    portfolio_id = portfolio.get("id", portfolio_view.portfolio_id)
    chat_key = conversation_session_key(user_id, portfolio_id)
    response_cache_key = adviser_response_cache_key(user_id, portfolio_id)
    try:
        adviser_candidates = overlay_candidate_rows(
            filter_equity_candidate_surface(
                candidate_repo.get_all(order_by="nabi_score", descending=True) or []
            ),
            ParticipationAssessmentRepository(client).list_latest_by_symbol() or {},
        )
        adviser_snapshots = ParticipationAssessmentRepository(client).list_latest_by_symbol() or {}
    except Exception:
        adviser_candidates = []
        adviser_snapshots = {}
    operating = compose_wealth_operating_views(
        portfolio_view=portfolio_view,
        wealth=wealth,
        accounts=accounts,
        candidates=adviser_candidates,
    )
    try:
        adviser_policy = PortfolioAllocationPolicyService(client, user_id).get_policy(
            str(portfolio_id or "")
        )
    except Exception:
        adviser_policy = None
    from components.portfolio_economic_exposure_ui import load_persisted_fund_snapshots

    fund_symbols = [
        str(row.symbol or "").strip().upper()
        for row in (
            list(portfolio_view.priced_positions)
            + list(portfolio_view.unpriced_positions)
            + list(portfolio_view.foreign_currency_positions)
        )
        if str(row.asset_class or "").strip().lower() in {"etf", "fund"}
        and str(row.symbol or "").strip()
    ]
    adviser_fund_snapshots = load_persisted_fund_snapshots(wealth, fund_symbols)
    from services.security_master_service import security_master_from_wealth

    adviser_security_master = security_master_from_wealth(wealth)
    render_nabi_adviser(
        candidates=adviser_candidates,
        snapshots=adviser_snapshots,
        portfolio_view=portfolio_view,
        decision=operating.decision,
        presented_actions=None,
        allocation=operating.allocation,
        goal_dashboard=operating.goal_dashboard,
        new_money_brief=operating.brief.new_money if operating.brief else None,
        llm_config=adviser_llm_config,
        session_state=st.session_state,
        chat_key=chat_key,
        policy=adviser_policy,
        assets=assets,
        positions=positions,
        fund_snapshots=adviser_fund_snapshots,
        security_master=adviser_security_master,
    )

    with st.expander("Detaylar", expanded=False):
        st.markdown("**Yatırım profili**")
        current_profile = adviser_profile_service.load_profile()
        with st.form("adviser_profile_form", clear_on_submit=False):
            profile_cols = st.columns(2)
            investment_horizon = profile_cols[0].selectbox(
                "Yatırım ufku",
                ["", *PROFILE_ENUM_OPTIONS["investment_horizon"]],
                index=(
                    PROFILE_ENUM_OPTIONS["investment_horizon"].index(current_profile.investment_horizon) + 1
                    if current_profile.investment_horizon in PROFILE_ENUM_OPTIONS["investment_horizon"]
                    else 0
                ),
            )
            risk_preference = profile_cols[1].selectbox(
                "Risk tercihi",
                ["", *PROFILE_ENUM_OPTIONS["risk_preference"]],
                index=(
                    PROFILE_ENUM_OPTIONS["risk_preference"].index(current_profile.risk_preference) + 1
                    if current_profile.risk_preference in PROFILE_ENUM_OPTIONS["risk_preference"]
                    else 0
                ),
            )
            profile_cols2 = st.columns(2)
            liquidity_need = profile_cols2[0].selectbox(
                "Likidite ihtiyacı",
                ["", *PROFILE_ENUM_OPTIONS["liquidity_need"]],
                index=(
                    PROFILE_ENUM_OPTIONS["liquidity_need"].index(current_profile.liquidity_need) + 1
                    if current_profile.liquidity_need in PROFILE_ENUM_OPTIONS["liquidity_need"]
                    else 0
                ),
            )
            concentration_preference = profile_cols2[1].selectbox(
                "Yoğunlaşma tercihi",
                ["", *PROFILE_ENUM_OPTIONS["concentration_preference"]],
                index=(
                    PROFILE_ENUM_OPTIONS["concentration_preference"].index(
                        current_profile.concentration_preference
                    )
                    + 1
                    if current_profile.concentration_preference
                    in PROFILE_ENUM_OPTIONS["concentration_preference"]
                    else 0
                ),
            )
            profile_cols3 = st.columns(2)
            income_need = profile_cols3[0].selectbox(
                "Gelir ihtiyacı",
                ["", *PROFILE_ENUM_OPTIONS["income_need"]],
                index=(
                    PROFILE_ENUM_OPTIONS["income_need"].index(current_profile.income_need) + 1
                    if current_profile.income_need in PROFILE_ENUM_OPTIONS["income_need"]
                    else 0
                ),
            )
            experience_level = profile_cols3[1].selectbox(
                "Deneyim seviyesi",
                ["", *PROFILE_ENUM_OPTIONS["experience_level"]],
                index=(
                    PROFILE_ENUM_OPTIONS["experience_level"].index(current_profile.experience_level) + 1
                    if current_profile.experience_level in PROFILE_ENUM_OPTIONS["experience_level"]
                    else 0
                ),
            )
            profile_notes = st.text_area(
                "Notlar (isteğe bağlı)",
                value=current_profile.notes or "",
            )
            save_profile = st.form_submit_button("Profili kaydet")
        if save_profile:
            adviser_profile_service.save_profile(
                investment_horizon=investment_horizon or None,
                risk_preference=risk_preference or None,
                liquidity_need=liquidity_need or None,
                concentration_preference=concentration_preference or None,
                income_need=income_need or None,
                experience_level=experience_level or None,
                notes=profile_notes or None,
            )
            st.success("Yatırım profili kaydedildi.")
            current_profile = adviser_profile_service.load_profile()
        st.markdown("**Hedefler**")
        active_goals = adviser_goal_service.list_active_goals(portfolio_id=portfolio_id)
        if active_goals:
            for goal in active_goals:
                scope = "Portföy" if goal.portfolio_id else "Genel"
                st.write(f"- [{scope}] {goal.title} ({goal.goal_type})")
                if st.button("Arşivle", key=f"archive_goal_{goal.id}"):
                    adviser_goal_service.archive_goal(goal.id)
                    st.rerun()
        else:
            st.caption("Aktif hedef yok.")
        with st.form("adviser_goal_form", clear_on_submit=True):
            goal_title = st.text_input("Hedef başlığı")
            goal_type = st.selectbox("Hedef türü", GOAL_TYPE_OPTIONS)
            goal_scope = st.selectbox("Kapsam", ["Bu portföy", "Genel"])
            goal_notes = st.text_input("Hedef notu (isteğe bağlı)")
            add_goal = st.form_submit_button("Hedef ekle")
        if add_goal and goal_title.strip():
            adviser_goal_service.create_goal(
                portfolio_id=portfolio_id if goal_scope == "Bu portföy" else None,
                goal_type=goal_type,
                title=goal_title.strip(),
                notes=goal_notes or None,
            )
            st.success("Hedef eklendi.")
            active_goals = adviser_goal_service.list_active_goals(portfolio_id=portfolio_id)
        adviser_performance_view = timeline.build_performance_view(portfolio)
        adviser_diagnostics_view = diagnostics_service.build_diagnostics_view(
            portfolio,
            portfolio_view,
            performance_view=adviser_performance_view,
            benchmark_view=None,
        )
        user_context = build_adviser_user_context(
            profile=current_profile,
            goals=active_goals,
            context=adviser_service.build_context(
                portfolio_view,
                adviser_diagnostics_view,
                performance_view=adviser_performance_view,
                benchmark_view=None,
                generated_from_snapshot_count=len(adviser_performance_view.history_points),
            ),
        )
        _, adviser_brief = adviser_service.build_preview(
            portfolio_view,
            adviser_diagnostics_view,
            performance_view=adviser_performance_view,
            benchmark_view=None,
            generated_from_snapshot_count=len(adviser_performance_view.history_points),
            user_context=user_context,
        )
        st.markdown("**Deterministik bulgular**")
        st.markdown(f"**{adviser_brief.headline}**")
        st.write(adviser_brief.portfolio_summary)
        if adviser_brief.data_quality_notes:
            st.warning("Veri kalitesi sınırlamaları:")
            for note in adviser_brief.data_quality_notes:
                st.write(f"- {note}")
        if adviser_brief.preference_summary:
            st.markdown("**Profil / hedef ilişki gözlemleri**")
            for line in adviser_brief.preference_summary:
                st.write(f"- {line}")
        st.markdown("**Öne çıkan bulgular**")
        if not adviser_brief.top_findings:
            st.info("Öne çıkan bulgu yok.")
        else:
            for finding in adviser_brief.top_findings:
                _render_adviser_finding(finding)
        if adviser_brief.questions_for_user:
            st.markdown("**Sorulabilecek sorular**")
            for question in adviser_brief.questions_for_user:
                st.write(f"- {question}")
