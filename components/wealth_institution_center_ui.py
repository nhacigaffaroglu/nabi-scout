"""Kurum Merkezi UI. Read-only institution grouping of canonical valuation."""

from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

import streamlit as st

from components.nabi_design_system import (
    render_kpi_row,
    render_section_title,
    render_status_badge,
)
from services.portfolio_intelligence_contract import PortfolioIntelligenceView
from services.wealth_goal_center_presentation import format_money_display, format_pct_display
from services.wealth_institution_center_presentation import (
    CASH_UNAVAILABLE,
    CONCENTRATION_TITLE,
    HOLDINGS_EXPANDER,
    MULTI_INSTITUTION_TITLE,
    SECTION_TITLE,
    InstitutionCard,
    InstitutionCenterView,
    present_institution_center,
)


def render_institution_center(
    *,
    portfolio_view: PortfolioIntelligenceView,
    accounts: Sequence[Dict[str, Any]] = (),
    center: Optional[InstitutionCenterView] = None,
) -> InstitutionCenterView:
    view = center or present_institution_center(portfolio_view, accounts)
    render_section_title(SECTION_TITLE)
    tone = "success" if view.valuation_complete else "warning"
    status = "Değerleme tamam" if view.valuation_complete else (view.limitation or "")
    if status:
        st.markdown(render_status_badge(status, tone), unsafe_allow_html=True)
    if view.limitation:
        st.caption(view.limitation)

    totals = view.totals
    cash_label = (
        format_money_display(totals.cash_value, totals.base_currency)
        if totals.cash_available
        else CASH_UNAVAILABLE
    )
    render_kpi_row(
        [
            (
                "Portföy toplamı",
                format_money_display(totals.total_value, totals.base_currency),
                None,
            ),
            ("Menkul", format_money_display(totals.securities_market_value, totals.base_currency), None),
            ("Nakit", cash_label, None),
            ("Kurum", str(len(view.institutions)), None),
        ]
    )

    for card in view.institutions:
        _render_institution_card(card, totals.base_currency)

    st.markdown(f"**{CONCENTRATION_TITLE}**")
    if view.concentration.top_name and view.concentration.top_share_pct is not None:
        st.write(
            f"En büyük kurum: **{view.concentration.top_name}** · "
            f"{format_pct_display(view.concentration.top_share_pct)}"
        )
    else:
        st.caption("Kurum yoğunlaşması hesaplanamadı.")

    st.markdown(f"**{MULTI_INSTITUTION_TITLE}**")
    if not view.multi_institution_holdings:
        st.caption("Aynı ürün birden fazla kurumda tutulmuyor.")
    else:
        for row in view.multi_institution_holdings:
            parts = ", ".join(
                f"{name} {qty:g}" for name, qty in row.quantities_by_account
            )
            st.write(
                f"**{row.symbol}** · {', '.join(row.institutions)} · "
                f"{parts} · toplam {row.total_quantity:g}"
            )
    return view


def _render_institution_card(card: InstitutionCard, base_currency: str) -> None:
    cash_label = (
        format_money_display(card.cash_value, base_currency)
        if card.cash_available
        else CASH_UNAVAILABLE
    )
    st.markdown(f"**{card.name}**")
    st.caption(
        f"{card.currency} · {card.holdings_count} varlık · "
        f"{', '.join(card.symbols) if card.symbols else '—'}"
    )
    render_kpi_row(
        [
            ("Toplam", format_money_display(card.total_value, base_currency), None),
            (
                "Menkul",
                format_money_display(card.securities_market_value, base_currency),
                None,
            ),
            ("Nakit", cash_label, None),
            ("Pay", format_pct_display(card.portfolio_share_pct), None),
        ]
    )
    with st.expander(f"{HOLDINGS_EXPANDER} — {card.name}", expanded=False):
        if not card.holdings:
            st.caption("Bu kurumda varlık yok.")
        for holding in card.holdings:
            value = (
                format_money_display(holding.market_value, base_currency)
                if holding.market_value is not None
                else "—"
            )
            weight = (
                format_pct_display(holding.portfolio_weight_pct)
                if holding.portfolio_weight_pct is not None
                else "—"
            )
            st.write(
                f"{holding.symbol} · {holding.quantity:g} · {value} · "
                f"{weight} · {holding.asset_type or '—'}"
            )
