from __future__ import annotations

from typing import Optional

import pandas as pd
import streamlit as st

from services.participation_filter_service import (
    PARTICIPATION_FILTER_ALL,
    PORTFOLIO_PARTICIPATION_FILTERS,
    filter_by_participation,
)
from services.portfolio_intelligence_charts import (
    build_allocation_bar_chart,
    build_pl_by_position_chart,
    build_position_allocation_chart,
)
from services.portfolio_intelligence_enrichment_contract import (
    ATTENTION_SEVERITY_HIGH,
    ATTENTION_SEVERITY_INFO,
    ATTENTION_SEVERITY_WATCH,
    PortfolioIntelligenceDashboardView,
)
from services.ui_formatters import format_research_status


def _format_money(value: Optional[float], currency: str) -> str:
    if value is None:
        return "—"
    return f"{value:,.2f} {currency}"


def _format_pct(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return f"{value:+.2f}%" if abs(value) < 1000 else f"{value:,.2f}%"


def render_portfolio_kpi_cards(dashboard: PortfolioIntelligenceDashboardView) -> None:
    base = dashboard.base
    currency = base.base_currency
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric(
        "Portföy değeri",
        _format_money(base.priced_total_market_value, currency),
        help="Yalnızca fiyatlı baz-para pozisyonları",
    )
    c2.metric(
        "Maliyet",
        _format_money(base.priced_total_cost_basis, currency),
    )
    c3.metric(
        "Gerçekleşmemiş K/Z",
        _format_money(base.priced_total_unrealized_pl, currency),
    )
    c4.metric(
        "Getiri %",
        _format_pct(dashboard.return_pct),
    )
    c5.metric("Pozisyon", base.total_position_count)
    c6.metric(
        "Araştırma kapsamı",
        f"%{dashboard.research_coverage_weight_pct:.1f}",
        help="Uygun + tamamlanmış NABI araştırması ağırlığı",
    )

    if base.unpriced_position_count:
        st.info(
            f"{base.unpriced_position_count} pozisyon kayıtlı ancak güncel fiyat "
            f"mevcut değil. Portföy değeri kısmi kapsamdadır "
            f"(%{base.health.priced_position_coverage_pct:.0f} fiyatlı)."
        )

    if dashboard.coverage.limitations:
        st.caption(" · ".join(dashboard.coverage.limitations))


def render_portfolio_charts(dashboard: PortfolioIntelligenceDashboardView) -> None:
    rows = list(dashboard.enriched_positions)
    if not rows:
        st.info("Görselleştirme için pozisyon bulunmuyor.")
        return

    row1_a, row1_b = st.columns(2)
    with row1_a:
        st.altair_chart(build_position_allocation_chart(rows), use_container_width=True)
    with row1_b:
        st.altair_chart(
            build_allocation_bar_chart(
                dashboard.account_allocation,
                title="Kurum dağılımı",
            ),
            use_container_width=True,
        )

    row2_a, row2_b = st.columns(2)
    with row2_a:
        st.altair_chart(
            build_allocation_bar_chart(
                dashboard.sector_allocation,
                title="Sektör dağılımı",
            ),
            use_container_width=True,
        )
    with row2_b:
        st.altair_chart(
            build_allocation_bar_chart(
                dashboard.participation_allocation,
                title="Katılım / uygunluk dağılımı",
            ),
            use_container_width=True,
        )

    row3_a, row3_b = st.columns(2)
    with row3_a:
        st.altair_chart(
            build_allocation_bar_chart(
                dashboard.research_coverage_allocation,
                title="Araştırma kapsamı",
            ),
            use_container_width=True,
        )
    with row3_b:
        st.altair_chart(build_pl_by_position_chart(rows), use_container_width=True)


def _attention_badge(severity: str) -> str:
    if severity == ATTENTION_SEVERITY_HIGH:
        return "🔴"
    if severity == ATTENTION_SEVERITY_WATCH:
        return "🟠"
    return "🔵"


def render_attention_section(dashboard: PortfolioIntelligenceDashboardView) -> None:
    st.subheader("Dikkat gerektirenler")
    st.caption(
        "Araştırma ve risk odaklı uyarılar; yatırım tavsiyesi veya alım/satım "
        "önerisi içermez."
    )
    if not dashboard.attention_items:
        st.success("Belirgin dikkat maddesi yok.")
        return
    for item in dashboard.attention_items[:12]:
        st.markdown(
            f"{_attention_badge(item.severity)} **{item.title}** — {item.detail}"
        )
    if len(dashboard.attention_items) > 12:
        st.caption(f"+ {len(dashboard.attention_items) - 12} ek madde")


def render_position_table(
    dashboard: PortfolioIntelligenceDashboardView,
    *,
    symbol_search: str,
    sector_filter: str,
    participation_filter: str,
    research_filter: str,
) -> None:
    rows = list(dashboard.enriched_positions)
    if symbol_search.strip():
        needle = symbol_search.strip().upper()
        rows = [
            row
            for row in rows
            if needle in row.valuation.symbol.upper()
            or needle in (row.company_name or "").upper()
        ]

    if sector_filter and sector_filter != "Tümü":
        rows = [row for row in rows if (row.sector or "Bilinmiyor") == sector_filter]

    rows = filter_by_participation(
        rows,
        status_getter=lambda row: row.participation_status,
        filter_key=participation_filter,
        uygun_only=participation_filter == "Sadece uygun olanları göster",
    )

    if research_filter and research_filter != "Tümü":
        rows = [row for row in rows if row.research_coverage_label == research_filter]

    if not rows:
        st.info("Filtrelere uyan pozisyon yok.")
        return

    currency = dashboard.base.base_currency
    table_rows = []
    for row in rows:
        val = row.valuation
        pl_pct = None
        if val.unrealized_pl is not None and val.cost_basis:
            pl_pct = (val.unrealized_pl / val.cost_basis) * 100.0
        table_rows.append(
            {
                "Sembol": val.symbol,
                "Şirket": row.company_name,
                "Kurum / Hesap": row.account_label,
                "Adet": val.quantity,
                "Ort. maliyet": val.average_cost,
                "Fiyat durumu": (
                    "Güncel fiyat mevcut"
                    if val.price_available
                    else "Güncel fiyat mevcut değil"
                ),
                "Fiyat": val.price if val.price_available else None,
                "Piyasa değeri": val.market_value if val.price_available else None,
                "K/Z": val.unrealized_pl if val.price_available else None,
                "K/Z %": pl_pct if val.price_available else None,
                "Portföy ağırlığı %": val.weight_pct if val.price_available else None,
                "Kurum ağırlığı %": row.account_weight_pct if val.price_available else None,
                "Para birimi": val.valuation_currency,
                "Sektör": row.sector or "—",
                "Katılım": row.participation_status,
                "Araştırma": format_research_status(row.research_status),
            }
        )

    frame = pd.DataFrame(table_rows)
    st.dataframe(
        frame,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Ort. maliyet": st.column_config.NumberColumn(format="%.2f"),
            "Fiyat": st.column_config.NumberColumn(format="%.2f"),
            "Piyasa değeri": st.column_config.NumberColumn(format="%.2f"),
            "K/Z": st.column_config.NumberColumn(format="%.2f"),
            "K/Z %": st.column_config.NumberColumn(format="%.2f"),
            "Portföy ağırlığı %": st.column_config.NumberColumn(format="%.1f"),
            "Kurum ağırlığı %": st.column_config.NumberColumn(format="%.1f"),
        },
    )
    st.caption(f"Gösterilen: {len(rows)} pozisyon · Baz para: {currency}")


def render_consolidated_exposure_table(
    dashboard: PortfolioIntelligenceDashboardView,
) -> None:
    if not dashboard.consolidated_symbols:
        return
    st.subheader("Birleşik enstrüman görünümü")
    st.caption(
        "Aynı sembol birden fazla kurumda tutuluyorsa burada toplanır; "
        "hesap seviyesi kayıtlar korunur."
    )
    rows = []
    for item in dashboard.consolidated_symbols:
        breakdown = ", ".join(
            f"{part.account_label}: {part.quantity:g}"
            for part in item.account_breakdown
        )
        pl_pct = None
        if item.total_unrealized_pl is not None and item.total_cost_basis:
            pl_pct = (item.total_unrealized_pl / item.total_cost_basis) * 100.0
        rows.append(
            {
                "Sembol": item.symbol,
                "Şirket": item.company_name,
                "Toplam adet": item.total_quantity,
                "Maliyet": item.total_cost_basis,
                "Piyasa değeri": item.total_market_value,
                "K/Z": item.total_unrealized_pl,
                "K/Z %": pl_pct,
                "Portföy ağırlığı %": item.portfolio_weight_pct,
                "Katılım": item.participation_status,
                "Kurumlar": breakdown,
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def render_empty_portfolio_onboarding(
    wealth: WealthCoreService,
    portfolio: Dict[str, Any],
    accounts: list,
) -> None:
    from components.portfolio_management_ui import (
        render_add_holding_form,
        render_create_account_form,
    )

    st.info("İlk yatırım aracını portföyüne ekle")
    st.markdown(
        "1. Kurum / hesap oluştur\n"
        "2. İlk enstrümanı ekle\n"
        "3. Portföy panosu otomatik güncellenir"
    )
    render_create_account_form(wealth, str(portfolio["id"]))
    render_add_holding_form(wealth, portfolio, accounts)


def render_position_filters(
    dashboard: PortfolioIntelligenceDashboardView,
) -> tuple[str, str, str, str]:
    sectors = sorted(
        {
            row.sector or "Bilinmiyor"
            for row in dashboard.enriched_positions
        }
    )
    research_labels = sorted(
        {
            row.research_coverage_label
            for row in dashboard.enriched_positions
        }
    )

    c1, c2, c3, c4, c5 = st.columns([2, 1, 1, 1, 1])
    symbol_search = c1.text_input("Sembol / şirket ara", value="", key="pi_symbol_search")
    sector_filter = c2.selectbox(
        "Sektör",
        ["Tümü", *sectors],
        key="pi_sector_filter",
    )
    participation_filter = c3.selectbox(
        "Katılım",
        list(PORTFOLIO_PARTICIPATION_FILTERS),
        key="pi_participation_filter",
    )
    research_filter = c4.selectbox(
        "Araştırma kapsamı",
        ["Tümü", *research_labels],
        key="pi_research_filter",
    )
    if participation_filter == PARTICIPATION_FILTER_ALL:
        c5.caption("Tüm katılım durumları")
    return symbol_search, sector_filter, participation_filter, research_filter
