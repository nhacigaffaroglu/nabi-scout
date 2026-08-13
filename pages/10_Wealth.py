import pandas as pd
import streamlit as st

from services.auth_service import get_current_user_id
from services.fmp_client import FMPClient, FMPError
from services.nabi_intelligence_facade import get_investment_intelligence
from services.portfolio_intelligence_service import PortfolioIntelligenceService
from services.ui import prepare_protected_page
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
from services.wealth_diagnostics_contract import DiagnosticCategory, DiagnosticSeverity
from services.wealth_diagnostics_engine import effective_position_count
from services.wealth_diagnostics_service import WealthDiagnosticsService
from services.wealth_price_service import WealthPriceService
from services.wealth_timeline_service import WealthTimelineService


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


def _severity_badge(severity: DiagnosticSeverity) -> str:
    if severity == DiagnosticSeverity.HIGH:
        return "🔴 Yüksek"
    if severity == DiagnosticSeverity.WATCH:
        return "🟡 İzle"
    return "🔵 Bilgi"


def _render_diagnostic_card(diagnostic) -> None:
    with st.expander(f"{_severity_badge(diagnostic.severity)} · {diagnostic.title}"):
        st.write(diagnostic.summary)
        st.caption(
            f"Kod: `{diagnostic.code}` · Güven: {diagnostic.confidence.value} · "
            f"Kaynak: {diagnostic.source}"
        )
        if diagnostic.affected_symbols:
            st.caption(f"Semboller: {', '.join(diagnostic.affected_symbols)}")
        if diagnostic.evidence:
            st.json(diagnostic.evidence)

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

tab_summary, tab_accounts, tab_assets, tab_txn, tab_positions, tab_liabilities, tab_history, tab_analysis = st.tabs(
    [
        "Özet",
        "Hesaplar",
        "Varlıklar",
        "İşlemler",
        "Pozisyonlar",
        "Borçlar",
        "Geçmiş",
        "Analiz",
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
                f"{row.get('executed_at')} · {row.get('txn_type')} · "
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
                f"@ {saved.captured_at}"
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
                    f"- {point.captured_at}: {', '.join(point.partial_reasons)}"
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
                f"- {snap.captured_at} · "
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
        st.write(f"{period.period_start_at} → {period.period_end_at}")
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
        st.write(f"{linked.period_start_at} → {linked.period_end_at}")
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
