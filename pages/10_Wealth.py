import pandas as pd
import streamlit as st

from services.auth_service import get_current_user_id
from services.fmp_client import FMPClient, FMPError
from services.nabi_intelligence_facade import get_investment_intelligence
from services.portfolio_intelligence_service import PortfolioIntelligenceService
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
from services.wealth_adviser_interpretation_service import WealthAdviserInterpretationService
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
from services.company_intelligence_core_service import CompanyIntelligenceCoreService
from services.company_report_participation_service import build_company_report_participation
from services.sec_contact_config import get_sec_contact_email
from services.sec_financial_client import SECFinancialClient
from services.research_eligibility_service import (
    evaluate_research_eligibility_from_participation_view,
)
from services.unified_adviser_service import UnifiedAdviserService
from services.unified_research_service import UnifiedResearchService
from services.wealth_adviser_prompt import extract_focus_symbol
from services.wealth_diagnostics_contract import DiagnosticCategory, DiagnosticSeverity
from services.wealth_diagnostics_engine import effective_position_count
from services.wealth_diagnostics_service import WealthDiagnosticsService
from services.wealth_price_service import WealthPriceService
from services.wealth_timeline_service import WealthTimelineService


from components.portfolio_holdings_ui import render_valuation_holdings_analysis


def _format_money(value, currency: str) -> str:
    if value is None:
        return "—"
    return f"{value:,.2f} {currency}"


def _load_price_service() -> WealthPriceService:
    try:
        fmp = FMPClient.from_streamlit_secrets()
    except FMPError:
        fmp = None
    return WealthPriceService(fmp)


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

st.info(
    "**Portföy analitiği** için **Portföy Zekâsı** sayfasını kullanın. "
    "Bu sayfa Wealth Danışman (AI) modülünü içerir."
)
if st.button("Portföy Zekâsı'na git", key="wealth_go_pi"):
    st.switch_page("pages/11_Portfolio_Intelligence.py")
st.divider()

user_id = get_current_user_id(client)
wealth = WealthCoreService(client, user_id)
price_service = _load_price_service()
intelligence = PortfolioIntelligenceService(
    wealth,
    price_service,
    nabi_client=client,
)
timeline = WealthTimelineService(wealth)
diagnostics_service = WealthDiagnosticsService(wealth)
adviser_service = WealthAdviserService()
unified_adviser_service = UnifiedAdviserService()
unified_research_service = UnifiedResearchService()
candidate_repo = CandidateRepository(client)
adviser_profile_service = WealthAdviserProfileService(client, user_id)
adviser_goal_service = WealthAdviserGoalService(client, user_id)
adviser_llm_config = load_adviser_llm_config()
adviser_interpretation_service = WealthAdviserInterpretationService(config=adviser_llm_config)


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


st.title("💰 Wealth Core")
st.caption(
    "Manuel portföy, hesap, varlık ve işlem kaydı. "
    "Pozisyonlar işlem defterinden türetilir. "
    "Alış/satış tek taraflıdır; nakit bakiyesi otomatik güncellenmez."
)

portfolio = wealth.ensure_default_portfolio()
summary = wealth.get_summary()
portfolio_view = intelligence.build_view(portfolio, enrich_nabi=True)

col1, col2, col3, col4, col5, col6 = st.columns(6)
col1.metric("Portföy", summary.portfolio_count)
col2.metric("Hesap", summary.account_count)
col3.metric("Varlık", summary.asset_count)
col4.metric("Pozisyon", summary.position_count)
col5.metric("Borç", summary.liability_count)
col6.metric("İşlem", summary.transaction_count)

st.divider()

tab_summary, tab_accounts, tab_assets, tab_txn, tab_positions, tab_liabilities, tab_history, tab_analysis, tab_adviser = st.tabs(
    [
        "Özet",
        "Hesaplar",
        "Varlıklar",
        "İşlemler",
        "Pozisyonlar",
        "Borçlar",
        "Geçmiş",
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
    st.subheader("Portföy özeti")
    st.write(
        f"**{portfolio_view.portfolio_name}** "
        f"({portfolio_view.base_currency})"
    )

    if portfolio_view.total_position_count == 0 and not accounts and not liabilities:
        st.info("Henüz wealth kaydı yok. Hesap ve varlık ekleyerek başlayın.")
    else:
        base_ccy = portfolio_view.base_currency
        v1, v2, v3, v4 = st.columns(4)
        partial = (
            portfolio_view.unpriced_position_count > 0
            or portfolio_view.foreign_currency_position_count > 0
            or portfolio_view.priced_position_count < portfolio_view.total_position_count
        )
        if partial:
            st.caption(
                f"Toplamlar yalnızca fiyatlı {base_ccy} pozisyonlarını kapsar; "
                "tam portföy değeri değildir."
            )

        v1.metric(
            f"Piyasa değeri (fiyatlı {base_ccy})",
            _format_money(portfolio_view.priced_total_market_value, base_ccy),
        )
        v2.metric(
            f"Maliyet (fiyatlı {base_ccy})",
            _format_money(portfolio_view.priced_total_cost_basis, base_ccy),
        )
        v3.metric(
            f"Gerçekleşmemiş K/Z ({base_ccy})",
            _format_money(portfolio_view.priced_total_unrealized_pl, base_ccy),
        )
        v4.metric(
            "Nakit / Yatırım (fiyatlı)",
            f"{portfolio_view.health.cash_pct:.1f}% / "
            f"{portfolio_view.health.invested_pct:.1f}%",
        )

        if portfolio_view.mixed_currency_warning:
            st.warning(
                f"{portfolio_view.foreign_currency_position_count} pozisyon "
                f"baz para birimi ({base_ccy}) dışında. "
                "FX dönüşümü yok; bu pozisyonlar toplam değere dahil değil."
            )
        if portfolio_view.unpriced_position_count:
            st.warning(
                f"{portfolio_view.unpriced_position_count} pozisyon için güncel "
                "fiyat yok; toplamlardan hariç tutuldu."
            )
        if portfolio_view.valuation_errors:
            with st.expander("Fiyat sağlayıcı uyarıları"):
                for msg in portfolio_view.valuation_errors:
                    st.write(f"- {msg}")

        st.markdown("**Sağlık göstergeleri**")
        st.caption(
            "Ağırlık ve yoğunluk: fiyatlı baz para birimi pozisyonları."
        )
        h1, h2, h3, h4, h5 = st.columns(5)
        h1.metric(
            "En büyük ağırlık",
            f"{portfolio_view.health.largest_position_weight_pct:.1f}%",
        )
        h2.metric(
            "Top-3 yoğunluk",
            f"{portfolio_view.health.top3_concentration_pct:.1f}%",
        )
        h3.metric(
            "Varlık sınıfı yoğunluğu",
            f"{portfolio_view.health.largest_asset_class_concentration_pct:.1f}%",
        )
        priced_any = portfolio_view.total_position_count - portfolio_view.unpriced_position_count
        h4.metric(
            "Fiyat kapsamı (pozisyon)",
            f"{portfolio_view.health.priced_position_coverage_pct:.0f}%",
            delta=f"{priced_any}/{portfolio_view.total_position_count}",
            delta_color="off",
        )
        h5.metric(
            "Fiyat çağrısı",
            f"{portfolio_view.unique_price_symbols_fetched}",
        )

        _render_allocation(
            f"Varlık sınıfı dağılımı (fiyatlı {base_ccy})",
            portfolio_view.asset_class_allocation,
            base_ccy,
        )
        _render_allocation(
            f"Hesap dağılımı (fiyatlı {base_ccy})",
            portfolio_view.account_allocation,
            base_ccy,
        )

        if accounts:
            st.markdown("**Hesaplar**")
            for row in accounts:
                st.write(
                    f"- {row.get('name')} · {row.get('account_type')} · "
                    f"{row.get('currency')}"
                )
        if liabilities:
            st.markdown("**Borçlar**")
            for row in liabilities:
                st.write(
                    f"- {row.get('name')} · {row.get('liability_type')} · "
                    f"{row.get('principal')} {row.get('currency')}"
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
    st.subheader("Portföy geçmişi")
    st.caption(
        "Anlık görüntüler yalnızca açıkça kaydedildiğinde oluşturulur. "
        "Performans, fiyatlı baz para birimi değerleri üzerinden hesaplanır."
    )

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

    timeline_view = timeline.build_timeline_view(portfolio)
    performance_view = timeline.build_performance_view(portfolio)

    if performance_view.history_points:
        st.divider()
        st.markdown("**Kayıtlı görüntü geçmişi**")
        st.caption(
            "Grafik yalnızca kaydedilmiş anlık görüntülerin fiyatlı baz para birimi "
            "değerini gösterir; yeni değerleme veya sağlayıcı çağrısı yapılmaz."
        )
        history_df = pd.DataFrame(
            {
                "priced_market_value": [
                    point.priced_market_value for point in performance_view.history_points
                ],
            },
            index=[point.captured_at for point in performance_view.history_points],
        )
        st.line_chart(history_df)
        partial_points = [
            point for point in performance_view.history_points if point.is_partial
        ]
        if partial_points:
            st.warning(
                "Bazı görüntüler kısmi: fiyatlanmamış pozisyon, karışık para birimi "
                "veya %100 altı kapsam."
            )
            for point in partial_points:
                st.write(
                    f"- {format_date_dmy(point.captured_at)}: {', '.join(point.partial_reasons)}"
                )

    if not timeline_view.snapshots:
        st.info("Henüz kayıtlı görüntü yok. Mevcut değerlendirmeyi kaydetmek için düğmeyi kullanın.")
    else:
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

    period = timeline_view.latest_period
    if period is None:
        st.info("Performans karşılaştırması için en az iki görüntü gerekir.")
    else:
        st.divider()
        st.markdown("**Son dönem karşılaştırması**")
        st.write(
            f"{format_date_dmy(period.period_start_at)} → {format_date_dmy(period.period_end_at)}"
        )
        p1, p2, p3, p4 = st.columns(4)
        p1.metric(
            "Değer değişimi",
            _format_money(period.portfolio_value_change, period.base_currency),
        )
        p2.metric(
            "Net dış akış",
            _format_money(period.net_external_flow, period.base_currency),
        )
        p3.metric(
            "Yatırım kazancı/kaybı",
            _format_money(period.investment_gain, period.base_currency),
        )
        p4.metric(
            "Temettü / ücret",
            f"{period.dividend_income:.2f} / {period.fee_cost:.2f} {period.base_currency}",
        )

        st.caption(
            f"Başlangıç: {_format_money(period.start_priced_value, period.base_currency)} · "
            f"Bitiş: {_format_money(period.end_priced_value, period.base_currency)} · "
            f"Giriş: {_format_money(period.external_inflows, period.base_currency)} · "
            f"Çıkış: {_format_money(period.external_outflows, period.base_currency)}"
        )
        st.caption(
            f"Kapsam başlangıç/bitiş: {period.start_coverage_pct:.0f}% / "
            f"{period.end_coverage_pct:.0f}%"
        )

        if not period.performance_comparable:
            st.warning(
                "Bu dönem performansı tam karşılaştırılabilir değil. "
                "Kazanç/kayıp bilgilendirme amaçlıdır; yatırım getirisi olarak yorumlamayın."
            )
            for warning in period.warnings:
                st.write(f"- {warning}")
        elif period.simple_period_return_pct is not None:
            st.caption(
                f"Dönem değişimi (dış akış yok): {period.simple_period_return_pct:.2f}%"
            )
        else:
            st.caption(
                "Basit dönem yüzdesi gösterilmedi; dış nakit akışı veya veri kalitesi "
                "nedeniyle yatırım getirisi iddiası yok."
            )

    linked = performance_view.linked_performance
    if linked is not None:
        st.divider()
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
        st.divider()
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

        st.caption(f"Benchmark sağlayıcı çağrısı (bu görünüm): {provider_calls}")

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
    st.subheader("Danışman")
    st.warning(
        "Bu özellik yatırım tavsiyesi değildir ve otomatik işlem gerçekleştirmez."
    )
    st.caption(
        "Deterministik Wealth verileri kaynak gerçektir; AI bölümü yalnızca yorum katmanıdır."
    )

    portfolio_id = portfolio.get("id", portfolio_view.portfolio_id)
    chat_key = conversation_session_key(user_id, portfolio_id)
    response_cache_key = adviser_response_cache_key(user_id, portfolio_id)

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

    st.divider()
    st.markdown("**AI sohbet yorumu**")
    st.caption(
        "Şirket sorularında sembol belirtin veya odak sembol girin. "
        "Her gönderimde en fazla bir AI çağrısı yapılır."
    )
    if not adviser_llm_config.is_usable:
        st.info(
            "AI yorumu etkin değil. WEALTH_ADVISER_LLM_API_KEY ve "
            "WEALTH_ADVISER_LLM_ENABLED yapılandırması gerekir."
        )
    else:
        conversation_history = get_conversation_history(st.session_state, chat_key)
        for turn in conversation_history:
            if turn.role == "user":
                st.markdown(f"**Siz:** {turn.content}")
            else:
                label = "AI (doğrulandı)" if turn.grounded else "AI (deterministik yedek)"
                st.markdown(f"**{label}:** {turn.content}")

        clear_col, _ = st.columns([1, 3])
        if clear_col.button("Sohbeti temizle", key=f"clear_chat_{portfolio_id}"):
            clear_conversation_history(st.session_state, chat_key)
            st.session_state.pop(response_cache_key, None)
            st.rerun()

        with st.form("adviser_chat_form", clear_on_submit=True):
            adviser_question = st.text_input(
                "Sorunuz",
                placeholder="Örn: AAPL yatırımımı bugün yeniden değerlendir.",
            )
            focus_symbol = st.text_input(
                "Odak sembol (isteğe bağlı)",
                placeholder="AAPL",
                max_chars=8,
            )
            send_message = st.form_submit_button("Gönder")

        if send_message and adviser_question.strip():
            unified_research = None
            symbol = extract_focus_symbol(
                adviser_question.strip(),
                explicit_symbol=focus_symbol.strip() or None,
            )
            if symbol:
                try:
                    candidate = candidate_repo.get_by_symbol(symbol) or {"symbol": symbol}
                    participation_fmp_client = None
                    try:
                        participation_fmp_client = FMPClient.from_streamlit_secrets()
                    except FMPError:
                        pass
                    participation_view = build_company_report_participation(
                        candidate,
                        sec_client=SECFinancialClient(contact_email=get_sec_contact_email()),
                        fmp_client=participation_fmp_client,
                    )
                    research_eligibility = evaluate_research_eligibility_from_participation_view(
                        participation_view
                    )
                    if not research_eligibility.research_allowed:
                        st.warning(research_eligibility.block_message)
                    else:
                        fmp_client = participation_fmp_client or FMPClient.from_streamlit_secrets()
                        intel_view = CompanyIntelligenceCoreService(fmp_client).build_view(
                            symbol,
                            research_eligibility=research_eligibility,
                            sec_financials=(
                                participation_view.result.sec_financials
                                if participation_view.result is not None
                                else None
                            ),
                        )
                        unified_research = unified_research_service.build_context(
                            symbol=symbol,
                            research_eligibility=research_eligibility,
                            company_intelligence_view=intel_view,
                            candidate=candidate,
                            participation_view=participation_view,
                            portfolio_view=portfolio_view,
                            user_context=user_context,
                            diagnostics_items=tuple(adviser_diagnostics_view.diagnostics[:3]),
                        )
                        adviser_brief = unified_adviser_service.enrich_brief(
                            adviser_brief,
                            unified_research,
                        )
                except FMPError:
                    st.warning(
                        f"{symbol} için şirket verisi yüklenemedi; yanıt yalnızca portföy bağlamında üretilecek."
                    )
                except Exception:
                    st.warning(
                        "Birleşik araştırma bağlamı oluşturulamadı; portföy bağlamı kullanılacak."
                    )
            response = adviser_interpretation_service.interpret(
                adviser_brief,
                user_question=adviser_question.strip(),
                conversation_history=conversation_history,
                unified_research=unified_research,
            )
            record_chat_exchange(
                st.session_state,
                chat_key,
                user_question=adviser_question.strip(),
                response=response,
            )
            st.session_state[response_cache_key] = response
            st.rerun()

    with st.expander("Teknik bağlam"):
        st.json(adviser_brief.to_dict())
