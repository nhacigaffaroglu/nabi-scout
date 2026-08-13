import streamlit as st

from services.auth_service import get_current_user_id
from services.nabi_intelligence_facade import get_investment_intelligence
from services.ui import prepare_protected_page
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

client = prepare_protected_page("Wealth | NABI Scout", "💰")
user_id = get_current_user_id(client)
wealth = WealthCoreService(client, user_id)

st.title("💰 Wealth Core")
st.caption(
    "Manuel portföy, hesap, varlık ve işlem kaydı. "
    "Pozisyonlar işlem defterinden türetilir. "
    "Alış/satış tek taraflıdır; nakit bakiyesi otomatik güncellenmez."
)

portfolio = wealth.ensure_default_portfolio()
summary = wealth.get_summary()

col1, col2, col3, col4, col5, col6 = st.columns(6)
col1.metric("Portföy", summary.portfolio_count)
col2.metric("Hesap", summary.account_count)
col3.metric("Varlık", summary.asset_count)
col4.metric("Pozisyon", summary.position_count)
col5.metric("Borç", summary.liability_count)
col6.metric("İşlem", summary.transaction_count)

st.divider()

tab_summary, tab_accounts, tab_assets, tab_txn, tab_positions, tab_liabilities = st.tabs(
    [
        "Özet",
        "Hesaplar",
        "Varlıklar",
        "İşlemler",
        "Pozisyonlar",
        "Borçlar",
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
    st.write(f"**{portfolio.get('name')}** ({portfolio.get('base_currency')})")
    if not accounts and not positions and not liabilities:
        st.info("Henüz wealth kaydı yok. Hesap ve varlık ekleyerek başlayın.")
    else:
        if accounts:
            st.markdown("**Hesaplar**")
            for row in accounts:
                st.write(
                    f"- {row.get('name')} · {row.get('account_type')} · "
                    f"{row.get('currency')}"
                )
        if positions:
            st.markdown("**Açık pozisyonlar**")
            for row in positions:
                asset = asset_by_id.get(row.get("asset_id"), {})
                account = account_by_id.get(row.get("account_id"), {})
                st.write(
                    f"- {asset.get('symbol', '?')} @ {account.get('name', '?')}: "
                    f"{row.get('quantity')} (ort. maliyet {row.get('average_cost')})"
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
        for row in transactions:
            asset = asset_by_id.get(row.get("asset_id"), {})
            account = account_by_id.get(row.get("account_id"), {})
            st.write(
                f"- {row.get('executed_at')} · {row.get('txn_type')} · "
                f"{asset.get('symbol', '?')} @ {account.get('name', '?')} · "
                f"qty={row.get('quantity')} amount={row.get('amount')}"
            )

with tab_positions:
    st.subheader("Güncel pozisyonlar")
    if not positions:
        st.info("Henüz açık pozisyon yok.")
    else:
        for row in positions:
            asset = asset_by_id.get(row.get("asset_id"), {})
            account = account_by_id.get(row.get("account_id"), {})
            st.write(
                f"**{asset.get('symbol', '?')}** · {account.get('name', '?')} · "
                f"miktar={row.get('quantity')} · ort. maliyet={row.get('average_cost')} "
                f"{row.get('cost_currency')}"
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
