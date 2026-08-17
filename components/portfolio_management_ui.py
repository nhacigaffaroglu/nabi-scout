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
from services.ui_formatters import (
    DATE_DMY_HELP,
    DATE_DMY_PLACEHOLDER,
    format_date_dmy,
    parse_date_dmy,
)
from services.wealth_contract import (
    ASSET_CLASS_CASH,
    ASSET_CLASS_EQUITY,
    BuyCostBasis,
    WealthValidationError,
    compute_buy_cost_basis,
)
from services.wealth_core_service import WealthCoreService


def _optional_dmy_date_text(label: str) -> str:
    """User-facing date field. Streamlit date_input is locale-pinned to en-US."""
    return str(
        st.text_input(
            label,
            value="",
            placeholder=DATE_DMY_PLACEHOLDER,
            help=DATE_DMY_HELP,
        )
        or ""
    )


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


def _format_cost_money(value: float, currency: str) -> str:
    return f"{value:,.2f} {currency}"


def render_buy_cost_preview(basis: BuyCostBasis, currency: str) -> None:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Brüt alış", _format_cost_money(basis.gross_cost, currency))
    c2.metric("Komisyon", _format_cost_money(basis.commission, currency))
    c3.metric("Toplam maliyet", _format_cost_money(basis.total_cost_basis, currency))
    c4.metric(
        "Komisyon dahil birim maliyet",
        f"{basis.effective_unit_cost:,.6f} {currency}",
    )


def render_create_account_form(
    wealth: WealthCoreService,
    portfolio_id: str,
    *,
    expanded: bool = False,
) -> None:
    with st.expander("+ Yeni Kurum / Hesap", expanded=expanded):
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
    flash = st.session_state.pop("pi_add_holding_flash", None)
    if flash:
        st.success(flash)
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
        unit_price = st.number_input(
            "Birim alış fiyatı",
            min_value=0.0,
            value=0.0,
            step=0.01,
        )
        commission = st.number_input(
            "Komisyon / masraf",
            min_value=0.0,
            value=0.0,
            step=0.01,
            help="Boş veya 0 ise komisyon yok. Maliyet bazına eklenir; adedi artırmaz.",
        )
        currency = st.text_input("Para birimi", value="USD")
        notes = st.text_area("Not (opsiyonel)", placeholder="Manuel ekleme notu")
        purchase_date_raw = _optional_dmy_date_text("Alış tarihi (opsiyonel)")
        st.caption(
            "Kayıt öncesi özet: Brüt alış · Komisyon · Toplam maliyet · "
            "Komisyon dahil birim maliyet"
        )
        submitted = st.form_submit_button("Portföye Ekle", type="primary")

    last_preview = st.session_state.get("pi_last_buy_cost_preview")
    if last_preview:
        render_buy_cost_preview(
            BuyCostBasis(**last_preview["basis"]),
            str(last_preview.get("currency") or "USD"),
        )

    if submitted:
        mgmt = PortfolioManagementService(wealth)
        try:
            purchase_date = parse_date_dmy(purchase_date_raw)
        except ValueError as exc:
            st.error(str(exc))
            return
        executed_at = purchase_date.isoformat() if purchase_date else None
        try:
            if asset_class != ASSET_CLASS_CASH:
                preview = compute_buy_cost_basis(
                    quantity=float(quantity),
                    unit_price=float(unit_price),
                    commission=float(commission),
                )
                render_buy_cost_preview(preview, currency.strip().upper() or "USD")
                st.session_state["pi_last_buy_cost_preview"] = {
                    "basis": preview.to_dict(),
                    "currency": currency.strip().upper() or "USD",
                }
            mgmt.add_holding(
                account_id=account_id,
                symbol=symbol,
                quantity=float(quantity),
                average_cost=float(unit_price),
                currency=currency,
                asset_class=asset_class,
                executed_at=executed_at,
                notes=notes.strip() or None,
                name=display_name.strip() or None,
                commission=float(commission),
            )
            symbol_label = symbol.strip().upper()
            if purchase_date:
                st.session_state["pi_add_holding_flash"] = (
                    f"{symbol_label} eklendi. Alış tarihi: {format_date_dmy(purchase_date)}"
                )
            else:
                st.session_state["pi_add_holding_flash"] = f"{symbol_label} eklendi."
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
                    xfer_date_raw = _optional_dmy_date_text("Transfer tarihi (opsiyonel)")
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
                            xfer_date = parse_date_dmy(xfer_date_raw)
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
