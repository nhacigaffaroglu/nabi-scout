"""Arındırma & Zekât UI. Session-only user assumptions; no writes or providers."""

from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

import streamlit as st

from components.nabi_design_system import (
    render_kpi_row,
    render_section_title,
    render_status_badge,
)
from services.portfolio_intelligence_contract import PortfolioIntelligenceView
from services.wealth_purification_zakat import (
    CASH_UNAVAILABLE,
    PurificationBasis,
    PurificationZakatResult,
    PurificationZakatScenario,
    ProductAssumption,
    calculate_purification_zakat,
)
from services.wealth_purification_zakat_presentation import (
    BASIS_DIVIDEND_LABEL,
    BASIS_MARKET_LABEL,
    BASIS_UNSELECTED_LABEL,
    DISCLAIMER,
    GLOBAL_ELIGIBLE_HELP,
    GLOBAL_ELIGIBLE_LABEL,
    SECTION_ASSUMPTIONS,
    SECTION_MISSING,
    SECTION_PRODUCTS,
    SECTION_SUMMARY,
    SECTION_TITLE,
    ZAKAT_RATE_HELP,
    ZAKAT_RATE_LABEL,
    basis_label,
    money_or_dash,
    pct_or_dash,
    row_status_label,
    missing_product_lines,
)

RESULT_STATE_KEY = "wealth_purification_zakat_result"
BASIS_CHOICES = (
    BASIS_UNSELECTED_LABEL,
    BASIS_DIVIDEND_LABEL,
    BASIS_MARKET_LABEL,
)
_BASIS_BY_LABEL = {
    BASIS_UNSELECTED_LABEL: None,
    BASIS_DIVIDEND_LABEL: PurificationBasis.DIVIDEND_INCOME,
    BASIS_MARKET_LABEL: PurificationBasis.MARKET_VALUE,
}


def scenario_from_session(
    position_ids: Sequence[str],
    *,
    session: Optional[Any] = None,
) -> Optional[PurificationZakatScenario]:
    try:
        state = session if session is not None else st.session_state
    except Exception:
        return None
    if state is None:
        return None
    try:
        if "wealth_pz_basis" not in state:
            return None
    except Exception:
        return None
    assumptions: list[ProductAssumption] = []
    for position_id in position_ids:
        ratio = _parse_optional_pct(state.get(f"wealth_pz_ratio_{position_id}"))
        eligible = _parse_optional_pct(state.get(f"wealth_pz_eligible_{position_id}"))
        if ratio is None and eligible is None:
            continue
        assumptions.append(
            ProductAssumption(
                position_id=position_id,
                purification_ratio_pct=ratio,
                zakat_eligible_pct=eligible,
            )
        )
    include_all = bool(state.get("wealth_pz_include_all"))
    if not assumptions and not include_all:
        return None
    return PurificationZakatScenario(
        basis=_BASIS_BY_LABEL.get(str(state.get("wealth_pz_basis") or "")),
        zakat_rate_pct=_parse_optional_pct(state.get("wealth_pz_zakat_rate")) or 2.5,
        include_all_eligible_at_100=include_all,
        assumptions=tuple(assumptions),
    )


def try_session_result(
    portfolio_view: PortfolioIntelligenceView,
    *,
    accounts: Sequence[Dict[str, Any]] = (),
    assets: Sequence[Dict[str, Any]] = (),
    transactions: Sequence[Dict[str, Any]] = (),
    session: Optional[Any] = None,
) -> Optional[PurificationZakatResult]:
    position_ids = [
        str(row.position_id)
        for row in (
            *portfolio_view.priced_positions,
            *portfolio_view.unpriced_positions,
            *portfolio_view.foreign_currency_positions,
        )
        if row.position_id
    ]
    scenario = scenario_from_session(position_ids, session=session)
    if scenario is None:
        return None
    return calculate_purification_zakat(
        portfolio_view,
        scenario=scenario,
        accounts=accounts,
        assets=assets,
        transactions=transactions,
    )


def _parse_optional_pct(raw: Any) -> Optional[float]:
    text = str(raw or "").strip().replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _tone(result: PurificationZakatResult) -> str:
    if not result.valuation_complete:
        return "warning"
    if result.missing_input_count:
        return "warning"
    return "success"


def render_purification_zakat_center(
    *,
    portfolio_view: PortfolioIntelligenceView,
    accounts: Sequence[Dict[str, Any]] = (),
    assets: Sequence[Dict[str, Any]] = (),
    transactions: Sequence[Dict[str, Any]] = (),
) -> PurificationZakatResult:
    render_section_title(SECTION_TITLE)
    st.caption(DISCLAIMER)

    preview = calculate_purification_zakat(
        portfolio_view,
        scenario=PurificationZakatScenario(basis=None, zakat_rate_pct=None),
        accounts=accounts,
        assets=assets,
        transactions=transactions,
    )
    currency = portfolio_view.base_currency

    st.markdown(f"**{SECTION_ASSUMPTIONS}**")
    basis_label_value = st.radio(
        "Arındırma matrahı",
        BASIS_CHOICES,
        index=0,
        horizontal=True,
        key="wealth_pz_basis",
    )
    zakat_rate = st.number_input(
        ZAKAT_RATE_LABEL,
        min_value=0.0,
        max_value=100.0,
        value=2.5,
        step=0.1,
        help=ZAKAT_RATE_HELP,
        key="wealth_pz_zakat_rate",
    )
    st.caption(ZAKAT_RATE_HELP)
    include_all = st.checkbox(
        GLOBAL_ELIGIBLE_LABEL,
        value=False,
        help=GLOBAL_ELIGIBLE_HELP,
        key="wealth_pz_include_all",
    )
    st.caption(GLOBAL_ELIGIBLE_HELP)

    assumptions: list[ProductAssumption] = []
    if preview.rows:
        st.markdown("Ürün varsayımları")
        for row in preview.rows:
            cols = st.columns(3)
            cols[0].write(f"**{row.symbol}** · {row.institution}")
            ratio_raw = cols[1].text_input(
                "Arındırma oranı %",
                value="",
                key=f"wealth_pz_ratio_{row.position_id}",
                placeholder="Girilmedi",
            )
            eligible_raw = cols[2].text_input(
                "Zekât dahil %",
                value="",
                key=f"wealth_pz_eligible_{row.position_id}",
                placeholder="Girilmedi",
            )
            ratio = _parse_optional_pct(ratio_raw)
            eligible = _parse_optional_pct(eligible_raw)
            if ratio is not None or eligible is not None:
                assumptions.append(
                    ProductAssumption(
                        position_id=row.position_id,
                        purification_ratio_pct=ratio,
                        zakat_eligible_pct=eligible,
                    )
                )

    result = calculate_purification_zakat(
        portfolio_view,
        scenario=PurificationZakatScenario(
            basis=_BASIS_BY_LABEL.get(str(basis_label_value)),
            zakat_rate_pct=float(zakat_rate),
            include_all_eligible_at_100=bool(include_all),
            assumptions=tuple(assumptions),
        ),
        accounts=accounts,
        assets=assets,
        transactions=transactions,
    )
    st.session_state[RESULT_STATE_KEY] = result

    status = (
        "Değerleme tamam" if result.valuation_complete else "Değerleme kısmi"
    )
    st.markdown(
        render_status_badge(status, _tone(result)),
        unsafe_allow_html=True,
    )
    st.caption(f"Seçilen matrah: {basis_label(result.basis)}")
    for note in result.limitations:
        st.caption(note)

    st.markdown(f"**{SECTION_SUMMARY}**")
    render_kpi_row(
        [
            ("Tahmini arındırma", money_or_dash(result.estimated_purification, currency), None),
            ("Tahmini zekât", money_or_dash(result.estimated_zakat, currency), None),
            ("Eksik veri", str(result.missing_input_count), None),
            (
                "Nakit",
                "—" if result.cash_available else CASH_UNAVAILABLE,
                None,
            ),
        ]
    )

    st.markdown(f"**{SECTION_PRODUCTS}**")
    if not result.rows:
        st.caption("Gösterilecek varlık yok.")
    for row in result.rows:
        st.write(
            f"**{row.symbol}** · {row.institution} · "
            f"{money_or_dash(row.market_value, currency)} · "
            f"arındırma {pct_or_dash(row.purification_ratio_pct)} → "
            f"{money_or_dash(row.purification_amount, currency)} · "
            f"zekât {pct_or_dash(row.zakat_eligible_pct)} · "
            f"matrah {money_or_dash(row.zakat_base, currency)} · "
            f"{money_or_dash(row.zakat_amount, currency)} · "
            f"{row_status_label(row)}"
        )

    st.markdown(f"**{SECTION_MISSING}**")
    missing = missing_product_lines(result)
    if not missing:
        st.caption("Eksik ürün girdisi yok.")
    for line in missing:
        st.write(line)
    return result
