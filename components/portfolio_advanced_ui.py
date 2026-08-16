from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

from services.portfolio_intelligence_charts import (
    build_income_timeline_chart,
    build_performance_vs_contributions_chart,
    build_performance_waterfall_chart,
    build_portfolio_value_history_chart,
)
from services.portfolio_performance_intelligence_service import PortfolioIntelligenceV13View
from services.wealth_decision_journal_service import WealthDecisionJournalService
from services.wealth_timeline_service import WealthTimelineService


def _money(value: Optional[float], currency: str) -> str:
    if value is None:
        return "—"
    return f"{value:,.2f} {currency}"


from components.nabi_design_system import render_chart_container, render_limitation_state


def render_v13_kpi_row(v13: PortfolioIntelligenceV13View) -> None:
    """Legacy compact KPI row — prefer executive hero on overview."""
    perf = v13.performance
    currency = v13.dashboard.base.base_currency
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Portföy değeri", _money(perf.current_value, currency))
    c2.metric("Toplam kazanç", _money(perf.total_gain, currency))
    c3.metric(
        "Getiri %",
        f"{perf.return_pct:.2f}%" if perf.return_pct is not None else "—",
    )
    c4.metric("Net katkı", _money(perf.net_contributions, currency))


def render_performance_section(v13: PortfolioIntelligenceV13View) -> None:
    render_chart_container(
        "Performans",
        subtitle="Persisted snapshot ve işlem verilerinden — sahte geçmiş yok.",
    )
    perf = v13.performance
    currency = v13.dashboard.base.base_currency

    if not perf.performance_available:
        render_limitation_state(
            "Yeterli geçmiş yok",
            "Geçmiş performans için en az iki portföy görüntüsü gerekli. "
            "Aşağıdaki düğümle güncel durumu kaydedin.",
        )
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Yatırım getirisi", _money(perf.investment_gain, currency))
        c2.metric("Net dış akış", _money(perf.net_external_flow, currency))
        c3.metric(
            "Bağlantılı getiri",
            f"{perf.linked_return_pct:.2f}%" if perf.linked_return_pct is not None else "—",
        )
        c4.metric("Temettü", _money(perf.dividend_income, currency))
        if perf.limitations:
            st.caption(" · ".join(perf.limitations))

    history = v13.performance_history.history_points
    if history:
        st.altair_chart(
            build_portfolio_value_history_chart(
                history,
                net_contributions=perf.net_contributions if perf.net_contributions else None,
                currency=currency,
            ),
            use_container_width=True,
        )
    else:
        st.info("Yeterli tarihsel snapshot bulunmuyor.")

    if perf.latest_period and perf.latest_period.performance_comparable:
        st.altair_chart(
            build_performance_waterfall_chart(perf.latest_period, currency=currency),
            use_container_width=True,
        )

    if perf.investment_gain is not None or perf.net_contributions:
        st.altair_chart(
            build_performance_vs_contributions_chart(
                investment_gain=perf.investment_gain,
                net_contributions=perf.net_contributions,
                currency=currency,
            ),
            use_container_width=True,
        )
        st.caption(
            "Net katkı: yatırma/çekme. Yatırım getirisi: portföy değişimi eksi net dış akış. "
            "Transferler dış akışa dahil edilmez."
        )


def render_income_section(v13: PortfolioIntelligenceV13View) -> None:
    st.subheader("Gelir")
    income = v13.income
    currency = income.base_currency
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Toplam temettü", _money(income.total_dividends, currency))
    c2.metric("YTD temettü", _money(income.dividends_ytd, currency))
    c3.metric("Son 12 ay", _money(income.trailing_twelve_months, currency))
    c4.metric(
        "Gelir verimi",
        f"{income.income_yield_pct:.2f}%" if income.income_yield_pct else "—",
    )
    if income.timeline:
        st.altair_chart(
            build_income_timeline_chart(income.timeline),
            use_container_width=True,
        )
    if income.by_symbol:
        rows = [
            {
                "Sembol": row.symbol,
                "Toplam": row.total_income,
                "Ödeme": row.payment_count,
            }
            for row in income.by_symbol[:10]
        ]
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


def render_cash_flow_section(v13: PortfolioIntelligenceV13View) -> None:
    st.subheader("Nakit akışı")
    cf = v13.cash_flow
    currency = cf.base_currency
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Yatırma", _money(cf.total_deposits, currency))
    c2.metric("Çekme", _money(cf.total_withdrawals, currency))
    c3.metric("Temettü", _money(cf.total_dividends, currency))
    c4.metric("Masraf", _money(cf.total_fees, currency))
    c5.metric("Net dış akış", _money(cf.net_external_flow, currency))
    st.caption("Kurumlar arası transferler dış nakit akışına dahil edilmez.")


def render_change_section(v13: PortfolioIntelligenceV13View) -> None:
    st.subheader("Ne Değişti?")
    if not v13.change_events:
        st.info("Karşılaştırılacak önceki portföy görüntüsü yok.")
        return
    for event in v13.change_events[:12]:
        st.markdown(f"**{event.title}** — {event.detail}")


def render_opportunity_section(v13: PortfolioIntelligenceV13View) -> None:
    st.subheader("Araştırma fırsatları")
    st.caption(
        "Kalıcı NABI araştırması ve katılım kurallarına göre deterministik "
        "portföy farkındalığı. Alım/satım önerisi değildir."
    )
    if not v13.opportunities:
        st.info("Şu an listelenecek fırsat adayı yok.")
        return
    rows = [
        {
            "Sembol": row.symbol,
            "Şirket": row.company_name,
            "Sektör": row.sector or "—",
            "Katılım": row.participation_status,
            "Etiket": row.opportunity_label,
            "Açıklama": row.explanation,
        }
        for row in v13.opportunities
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


def render_goals_section(v13: PortfolioIntelligenceV13View) -> None:
    st.subheader("Hedefler ve projeksiyon")
    if not v13.goal_projections:
        st.info("Aktif hedef yok. Wealth Danışman sekmesinden veya buradan eklenebilir.")
        return
    for projection in v13.goal_projections:
        with st.expander(projection.goal_title, expanded=False):
            st.caption("Tüm getiri varsayımları kullanıcı tahminidir; NABI tahmini değildir.")
            for scenario in projection.scenarios:
                st.markdown(
                    f"**{scenario.label}** (%{scenario.annual_return_assumption_pct:.1f} varsayım) · "
                    f"Projeksiyon: {_money(scenario.projected_value, projection.currency)} · "
                    f"İlerleme: "
                    f"{scenario.progress_pct:.1f}%"
                    if scenario.progress_pct is not None
                    else f"**{scenario.label}**"
                )


def render_data_quality_section(v13: PortfolioIntelligenceV13View) -> None:
    with st.expander("Veri kalitesi", expanded=False):
        dq = v13.data_quality
        st.markdown(
            f"- Fiyatlı pozisyon: **{dq.priced_positions}/{dq.total_positions}**"
            + (
                f" (%{dq.priced_weight_pct:.0f})"
                if dq.priced_weight_pct is not None
                else ""
            )
        )
        st.markdown(f"- Kayıtlı görüntü: **{dq.snapshot_count}**")
        st.markdown(
            f"- Performans hesabı: **{'evet' if dq.performance_available else 'kısmi/eksik'}**"
        )
        if dq.limitations:
            for item in dq.limitations:
                st.markdown(f"- {item}")


def render_snapshot_controls(
    wealth,
    portfolio: Dict[str, Any],
    intelligence_service,
) -> None:
    timeline = WealthTimelineService(wealth)
    if st.button("Güncel portföy görüntüsünü kaydet", key="pi_save_snapshot"):
        view = intelligence_service.build_view(portfolio, enrich_nabi=True)
        timeline.save_snapshot_from_view(portfolio, view)
        st.success("Portföy görüntüsü kaydedildi.")
        st.rerun()


def render_journal_section(
    client,
    user_id: str,
    portfolio_id: str,
    accounts: List[Dict[str, Any]],
) -> None:
    st.subheader("Karar günlüğü")
    journal = WealthDecisionJournalService(client, user_id)
    entries = journal.list_entries(portfolio_id=portfolio_id, limit=20)
    if entries:
        rows = [
            {
                "Tarih": (row.get("created_at") or "")[:10],
                "Sembol": row.get("symbol"),
                "Bağlam": row.get("action_context"),
                "Tez": (row.get("thesis") or "")[:80],
            }
            for row in entries
        ]
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    with st.expander("Yeni karar kaydı", expanded=False):
        account_labels = {
            f"{a.get('institution') or ''} — {a.get('name')}": str(a["id"])
            for a in accounts
        }
        with st.form("pi_journal_form"):
            symbol = st.text_input("Sembol", placeholder="CRM")
            action = st.selectbox(
                "Bağlam",
                ["considering", "added", "increased", "reduced", "exited", "reviewed"],
            )
            account_label = st.selectbox(
                "Hesap (opsiyonel)",
                ["—", *account_labels.keys()],
            )
            thesis = st.text_area("Tez")
            evidence = st.text_area("Kanıt")
            risks = st.text_area("Riskler")
            invalidation = st.text_area("Geçersiz kılma koşulları")
            submitted = st.form_submit_button("Kaydet")
        if submitted:
            account_id = (
                account_labels.get(account_label)
                if account_label != "—"
                else None
            )
            try:
                journal.create_entry(
                    symbol=symbol,
                    action_context=action,
                    portfolio_id=portfolio_id,
                    account_id=account_id,
                    thesis=thesis,
                    key_evidence=evidence,
                    key_risks=risks,
                    invalidation_conditions=invalidation,
                )
                st.success("Karar kaydı eklendi.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))


def render_cash_event_form(
    wealth,
    portfolio: Dict[str, Any],
    accounts: List[Dict[str, Any]],
) -> None:
    from services.portfolio_account_helpers import accounts_for_portfolio, account_filter_options
    from services.portfolio_management_service import PortfolioManagementService
    from services.wealth_contract import WealthValidationError

    portfolio_accounts = accounts_for_portfolio(accounts, str(portfolio["id"]))
    if not portfolio_accounts:
        return
    labels = account_filter_options(portfolio_accounts)
    with st.expander("Nakit işlem / temettü / masraf", expanded=False):
        with st.form("pi_cash_event_form"):
            account_choice = st.selectbox("Hesap", [label for label, _ in labels])
            txn_type = st.selectbox(
                "İşlem türü",
                ["dividend", "deposit", "withdraw", "fee"],
            )
            amount = st.number_input("Tutar", min_value=0.0, step=0.01)
            symbol = st.text_input("Sembol (temettü için)", value="")
            currency = st.text_input("Para birimi", value="USD")
            submitted = st.form_submit_button("Kaydet")
        if submitted:
            account_id = dict(labels)[account_choice]
            try:
                PortfolioManagementService(wealth).record_cash_event(
                    account_id=account_id,
                    txn_type=txn_type,
                    amount=float(amount),
                    currency=currency,
                    symbol=symbol.strip() or None,
                )
                st.success("İşlem kaydedildi.")
                st.rerun()
            except (WealthValidationError, Exception) as exc:
                st.error(str(exc))
