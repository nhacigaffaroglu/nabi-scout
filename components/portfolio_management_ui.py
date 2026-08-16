from __future__ import annotations

from typing import Any, Dict, List, Optional

import streamlit as st

from services.portfolio_account_helpers import (
    account_filter_options,
    accounts_for_portfolio,
    format_account_display,
)
from services.portfolio_intelligence_enrichment_contract import (
    EnrichedPositionRow,
    PortfolioIntelligenceDashboardView,
)
from services.portfolio_management_service import (
    ASSET_CLASS_OPTIONS,
    PortfolioManagementService,
)
from services.wealth_contract import (
    ASSET_CLASS_CASH,
    ASSET_CLASS_EQUITY,
    WealthValidationError,
)
from services.wealth_core_service import WealthCoreService


def render_account_scope_filter(
    accounts: List[Dict[str, Any]],
) -> Optional[str]:
    options = ["Tümü", *[label for label, _ in account_filter_options(accounts)]]
    labels_to_id = {"Tümü": None}
    for label, account_id in account_filter_options(accounts):
        labels_to_id[label] = account_id
    selected = st.selectbox(
        "Kurum / Hesap",
        options,
        key="pi_account_scope_filter",
    )
    return labels_to_id.get(selected)


def render_create_account_form(
    wealth: WealthCoreService,
    portfolio_id: str,
) -> None:
    with st.expander("+ Yeni Kurum / Hesap", expanded=False):
        with st.form("pi_create_account_form"):
            institution = st.text_input("Kurum", placeholder="Midas, YKB, TFK…")
            account_label = st.text_input("Hesap etiketi", placeholder="ABD Hisse")
            currency = st.text_input("Para birimi", value="USD")
            submitted = st.form_submit_button("Hesap oluştur", type="primary")
        if submitted:
            mgmt = PortfolioManagementService(wealth)
            try:
                created = mgmt.create_institution_account(
                    institution=institution,
                    account_label=account_label,
                    currency=currency,
                    portfolio_id=portfolio_id,
                )
                st.success(f"Hesap oluşturuldu: {format_account_display(created)}")
                st.rerun()
            except (WealthValidationError, Exception) as exc:
                st.error(str(exc))


def render_add_holding_form(
    wealth: WealthCoreService,
    portfolio: Dict[str, Any],
    accounts: List[Dict[str, Any]],
) -> None:
    portfolio_accounts = accounts_for_portfolio(accounts, str(portfolio["id"]))
    st.subheader("Portföye Ekle")
    if not portfolio_accounts:
        st.info("Önce bir kurum / hesap oluşturun.")
        return

    account_labels = account_filter_options(portfolio_accounts)
    with st.form("pi_add_holding_form"):
        account_choice = st.selectbox(
            "Kurum / Hesap",
            [label for label, _ in account_labels],
        )
        account_id = dict(account_labels)[account_choice]
        symbol = st.text_input("Yatırım aracı / Sembol", placeholder="CRM")
        display_name = st.text_input("Görünen ad (opsiyonel)", placeholder="Salesforce Inc.")
        asset_class = st.selectbox(
            "Varlık türü",
            ASSET_CLASS_OPTIONS,
            index=ASSET_CLASS_OPTIONS.index(ASSET_CLASS_EQUITY),
        )
        quantity = st.number_input("Adet", min_value=0.0, value=0.0, step=1.0)
        average_cost = st.number_input(
            "Alış fiyatı / ortalama maliyet",
            min_value=0.0,
            value=0.0,
            step=0.01,
        )
        currency = st.text_input("Para birimi", value="USD")
        notes = st.text_area("Not (opsiyonel)", placeholder="Manuel ekleme notu")
        purchase_date = st.date_input("Alış tarihi (opsiyonel)", value=None)
        submitted = st.form_submit_button("Portföye Ekle", type="primary")

    if submitted:
        mgmt = PortfolioManagementService(wealth)
        executed_at = purchase_date.isoformat() if purchase_date else None
        try:
            mgmt.add_holding(
                account_id=account_id,
                symbol=symbol,
                quantity=float(quantity),
                average_cost=float(average_cost),
                currency=currency,
                asset_class=asset_class,
                executed_at=executed_at,
                notes=notes.strip() or None,
                name=display_name.strip() or None,
            )
            st.success(f"{symbol.strip().upper()} eklendi.")
            st.rerun()
        except (WealthValidationError, Exception) as exc:
            st.error(str(exc))


def render_account_management_panel(
    wealth: WealthCoreService,
    portfolio: Dict[str, Any],
    accounts: List[Dict[str, Any]],
) -> None:
    portfolio_accounts = accounts_for_portfolio(accounts, str(portfolio["id"]))
    if not portfolio_accounts:
        return

    with st.expander("Kurum / Hesap yönetimi", expanded=False):
        rows = []
        open_positions = wealth.list_positions()
        txn_rows = wealth.list_transactions(limit=500)
        for account in portfolio_accounts:
            account_id = str(account["id"])
            position_count = sum(
                1
                for row in open_positions
                if str(row.get("account_id") or "") == account_id
            )
            txn_count = sum(
                1
                for row in txn_rows
                if str(row.get("account_id") or "") == account_id
            )
            rows.append(
                {
                    "Hesap": format_account_display(account),
                    "Para birimi": account.get("currency") or "—",
                    "Durum": "Aktif" if account.get("is_active", True) else "Pasif",
                    "Açık pozisyon": position_count,
                    "İşlem": txn_count,
                }
            )
        st.dataframe(rows, use_container_width=True, hide_index=True)

        inactive_candidates = [
            account
            for account in portfolio_accounts
            if account.get("is_active", True)
        ]
        if inactive_candidates:
            labels = [format_account_display(a) for a in inactive_candidates]
            label_to_id = {
                format_account_display(a): str(a["id"]) for a in inactive_candidates
            }
            selected = st.selectbox(
                "Pasifleştirilecek boş hesap",
                labels,
                key="pi_deactivate_account_select",
            )
            confirm = st.checkbox(
                "Bu hesabı pasifleştirmeyi onaylıyorum (silme değildir)",
                key="pi_deactivate_confirm",
            )
            if st.button("Boş hesabı pasifleştir", key="pi_deactivate_btn"):
                if not confirm:
                    st.error("Onay kutusunu işaretleyin.")
                else:
                    try:
                        PortfolioManagementService(wealth).deactivate_empty_account(
                            label_to_id[selected]
                        )
                        st.success("Hesap pasifleştirildi.")
                        st.rerun()
                    except (WealthValidationError, Exception) as exc:
                        st.error(str(exc))


def _position_options(
    dashboard: PortfolioIntelligenceDashboardView,
) -> List[tuple[str, EnrichedPositionRow]]:
    options: List[tuple[str, EnrichedPositionRow]] = []
    for row in dashboard.enriched_positions:
        label = (
            f"{row.valuation.symbol} · {row.account_label} · "
            f"{row.valuation.quantity:g} adet"
        )
        options.append((label, row))
    return options


def render_position_management_panel(
    wealth: WealthCoreService,
    portfolio: Dict[str, Any],
    accounts: List[Dict[str, Any]],
    dashboard: PortfolioIntelligenceDashboardView,
) -> None:
    options = _position_options(dashboard)
    if not options:
        return

    portfolio_accounts = accounts_for_portfolio(accounts, str(portfolio["id"]))
    account_labels = account_filter_options(portfolio_accounts)

    with st.expander("Pozisyon düzenle / transfer / kapat", expanded=False):
        labels = [label for label, _ in options]
        selected_label = st.selectbox("Pozisyon", labels, key="pi_manage_position")
        selected = dict(options)[selected_label]
        val = selected.valuation

        tab_edit, tab_transfer, tab_close = st.tabs(
            ["Düzelt", "Kurumlar Arası Transfer", "Kapat"]
        )

        with tab_edit:
            with st.form("pi_edit_position_form"):
                new_qty = st.number_input(
                    "Yeni adet",
                    min_value=0.0,
                    value=float(val.quantity),
                    step=1.0,
                )
                new_cost = st.number_input(
                    "Yeni ortalama maliyet",
                    min_value=0.0,
                    value=float(val.average_cost),
                    step=0.01,
                )
                confirm_edit = st.checkbox("Düzeltmeyi onaylıyorum")
                edit_submit = st.form_submit_button("Düzeltmeyi kaydet")
            if edit_submit:
                if not confirm_edit:
                    st.error("Onay kutusunu işaretleyin.")
                else:
                    try:
                        PortfolioManagementService(wealth).adjust_holding(
                            account_id=val.account_id,
                            asset_id=val.asset_id,
                            new_quantity=float(new_qty),
                            new_average_cost=float(new_cost),
                        )
                        st.success("Pozisyon düzeltildi.")
                        st.rerun()
                    except (WealthValidationError, Exception) as exc:
                        st.error(str(exc))

        with tab_transfer:
            if val.is_cash or val.asset_class == ASSET_CLASS_CASH:
                st.caption("Nakit transferi henüz bu panelden desteklenmiyor.")
            elif len(account_labels) < 2:
                st.caption("Transfer için en az iki hesap gerekli.")
            else:
                st.caption(
                    "Bu işlem satış değildir; maliyet bazını koruyarak "
                    "kurumlar arasında aktarım yapar."
                )
                with st.form("pi_transfer_position_form"):
                    dest_labels = [
                        label
                        for label, acc_id in account_labels
                        if acc_id != val.account_id
                    ]
                    dest_label = st.selectbox("Hedef hesap", dest_labels)
                    dest_id = dict(account_labels)[dest_label]
                    xfer_qty = st.number_input(
                        "Transfer adedi",
                        min_value=0.0,
                        max_value=float(val.quantity),
                        value=float(val.quantity),
                        step=1.0,
                    )
                    xfer_date = st.date_input("Transfer tarihi (opsiyonel)", value=None)
                    xfer_note = st.text_input("Not (opsiyonel)", value="")
                    confirm_xfer = st.checkbox(
                        "Bu işlem satış değildir; maliyet bazını koruyarak "
                        "kurumlar arasında aktarım yapar — onaylıyorum"
                    )
                    xfer_submit = st.form_submit_button("Transfer et")
                if xfer_submit:
                    if not confirm_xfer:
                        st.error("Onay kutusunu işaretleyin.")
                    else:
                        try:
                            executed_at = xfer_date.isoformat() if xfer_date else None
                            PortfolioManagementService(wealth).transfer_holding(
                                from_account_id=val.account_id,
                                to_account_id=dest_id,
                                asset_id=val.asset_id,
                                quantity=float(xfer_qty),
                                executed_at=executed_at,
                                notes=xfer_note.strip() or None,
                            )
                            st.success("Transfer tamamlandı.")
                            st.rerun()
                        except (WealthValidationError, Exception) as exc:
                            st.error(str(exc))

        with tab_close:
            st.warning(
                f"{val.symbol} pozisyonu {selected.account_label} hesabında "
                f"kapatılacak ({val.quantity:g} adet)."
            )
            confirm_close = st.checkbox(
                "Pozisyonu kapatmayı onaylıyorum",
                key="pi_close_confirm",
            )
            if st.button("Pozisyonu kapat", type="primary", key="pi_close_btn"):
                if not confirm_close:
                    st.error("Onay kutusunu işaretleyin.")
                else:
                    try:
                        PortfolioManagementService(wealth).close_holding(
                            account_id=val.account_id,
                            asset_id=val.asset_id,
                        )
                        st.success("Pozisyon kapatıldı.")
                        st.rerun()
                    except (WealthValidationError, Exception) as exc:
                        st.error(str(exc))
