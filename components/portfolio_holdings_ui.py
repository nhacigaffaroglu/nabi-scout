from __future__ import annotations

from typing import Sequence

import streamlit as st

from components.nabi_design_system import render_section_title
from services.portfolio_intelligence_charts import (
    build_holdings_pl_chart,
    build_holdings_weight_chart,
    count_unpriced_holdings,
    normalize_enriched_holdings,
    normalize_valuation_holdings,
)
from services.portfolio_intelligence_contract import PositionValuationRow
from services.portfolio_intelligence_enrichment_contract import EnrichedPositionRow


def _render_unpriced_notice(holdings_count: int, unpriced_count: int) -> None:
    if unpriced_count <= 0:
        return
    st.caption(
        f"{unpriced_count}/{holdings_count} pozisyon güncel fiyat olmadığı için "
        "grafiklerde gösterilmedi — tabloda ayrı listelenir."
    )


def render_enriched_holdings_analysis(
    rows: Sequence[EnrichedPositionRow],
    *,
    currency: str,
) -> None:
    holdings = normalize_enriched_holdings(rows)
    _render_holdings_charts(holdings, currency=currency)


def render_valuation_holdings_analysis(
    rows: Sequence[PositionValuationRow],
    *,
    currency: str,
) -> None:
    holdings = normalize_valuation_holdings(rows)
    _render_holdings_charts(holdings, currency=currency)


def _render_holdings_charts(holdings, *, currency: str) -> None:
    if not holdings:
        st.info("Görselleştirme için pozisyon bulunmuyor.")
        return

    render_section_title(
        "Pozisyon analizi",
        description=f"Baz para: {currency} · En büyük pozisyonlar ve K/Z dağılımı",
    )
    unpriced = count_unpriced_holdings(holdings)
    _render_unpriced_notice(len(holdings), unpriced)

    c1, c2 = st.columns(2)
    with c1:
        st.altair_chart(build_holdings_weight_chart(holdings), use_container_width=True)
    with c2:
        st.altair_chart(build_holdings_pl_chart(holdings), use_container_width=True)
