import streamlit as st

from components.candidate_cards import render_candidate_card
from repositories.candidate_repository import CandidateRepository
from services.candidate_surface_service import filter_equity_candidate_surface
from services.research_workflow_service import (
    DEFAULT_RESEARCH_STATUS,
    normalize_research_status,
    workflow_select_index,
    workflow_select_options,
)
from services.scoring_engine import (
    calculate_nabi_score_v2,
    financial_health_score,
    valuation_score_from_prices,
)
from services.ui import prepare_protected_page

client = prepare_protected_page("Aday Havuzu | NABI Scout", "🧭")

st.title("🧭 Aday Havuzu")
repo = CandidateRepository(client)

if "candidate_editor_id" not in st.session_state:
    st.session_state.candidate_editor_id = None

with st.expander("➕ Yeni aday ekle", expanded=False):
    with st.form("candidate_create_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        symbol = c1.text_input("Sembol *", placeholder="MSFT").strip().upper()
        company_name = c2.text_input("Şirket / Fon adı")
        asset_type = c3.selectbox(
            "Varlık türü",
            ["Hisse", "Fon", "Sukuk", "Altın", "Gümüş", "Diğer"],
        )

        c4, c5, c6 = st.columns(3)
        market = c4.selectbox(
            "Piyasa",
            ["ABD", "BIST", "TEFAS", "Global", "Diğer"],
        )
        currency = c5.selectbox(
            "Para birimi",
            ["USD", "TRY", "EUR", "GBP", "Diğer"],
        )
        country = c6.text_input("Ülke")

        c7, c8, c9 = st.columns(3)
        sector_theme = c7.text_input("Sektör / Tema")
        participation_status = c8.selectbox(
            "Katılım uygunluğu",
            ["Kontrol Et", "Uygun", "Uygun Değil"],
        )
        research_labels, research_values = zip(*workflow_select_options())
        research_status_label = c9.selectbox(
            "Araştırma durumu",
            research_labels,
            index=workflow_select_index(DEFAULT_RESEARCH_STATUS),
        )
        research_status = research_values[
            list(research_labels).index(research_status_label)
        ]

        st.markdown("#### Fiyat ve değerleme")
        p1, p2, p3, p4 = st.columns(4)
        current_price = p1.number_input("Güncel fiyat", min_value=0.0)
        fair_value = p2.number_input("Adil değer", min_value=0.0)
        pe_ratio = p3.number_input("F/K", min_value=0.0)
        peg_ratio = p4.number_input("PEG", min_value=0.0)

        st.markdown("#### Finansal kalite")
        f1, f2, f3, f4 = st.columns(4)
        revenue_growth = f1.number_input("Gelir büyümesi (%)", value=0.0)
        eps_growth = f2.number_input("EPS büyümesi (%)", value=0.0)
        operating_margin = f3.number_input("Faaliyet marjı (%)", value=0.0)
        roic = f4.number_input("ROIC (%)", value=0.0)

        f5, f6, f7 = st.columns(3)
        net_debt_ebitda = f5.number_input("Net borç / EBITDA", value=0.0)
        free_cash_flow_margin = f6.number_input("FCF marjı (%)", value=0.0)
        dividend_yield = f7.number_input("Temettü verimi (%)", value=0.0)

        st.markdown("#### Araştırma puanları")
        s1, s2, s3, s4 = st.columns(4)
        quality = s1.number_input("Kalite", 0, 100, 50)
        growth = s2.number_input("Büyüme", 0, 100, 50)
        manual_valuation = s3.number_input("Manuel değerleme", 0, 100, 50)
        news_catalyst = s4.number_input("Haber & katalizör", 0, 100, 50)

        s5, s6, s7 = st.columns(3)
        portfolio_fit = s5.number_input("Portföy uyumu", 0, 100, 50)
        liquidity = s6.number_input("Likidite", 0, 100, 50)
        participation_score = s7.number_input("Katılım skoru", 0, 100, 100)

        investment_thesis = st.text_area("Yatırım tezi")
        growth_catalysts = st.text_area("Büyüme katalizörleri")
        critical_risk = st.text_area("Kritik risk")
        notes = st.text_area("Not")

        submitted = st.form_submit_button("Adayı kaydet", type="primary")

    if submitted:
        if not symbol:
            st.error("Sembol zorunludur.")
        else:
            health = financial_health_score(
                roic=roic,
                operating_margin=operating_margin,
                net_debt_ebitda=net_debt_ebitda,
                free_cash_flow_margin=free_cash_flow_margin,
            )

            valuation_result = valuation_score_from_prices(
                current_price=current_price or None,
                fair_value=fair_value or None,
                manual_valuation_score=manual_valuation,
            )

            score_result = calculate_nabi_score_v2(
                quality=quality,
                growth=growth,
                valuation=valuation_result["valuation_score"],
                news_catalyst=news_catalyst,
                portfolio_fit=portfolio_fit,
                financial_health=health,
                liquidity=liquidity,
                participation_score=participation_score,
                participation_status=participation_status,
            )

            payload = {
                "symbol": symbol,
                "company_name": company_name or None,
                "asset_type": asset_type,
                "market": market,
                "currency": currency,
                "country": country or None,
                "sector_theme": sector_theme or None,
                "participation_status": participation_status,
                "research_status": research_status,
                "current_price": current_price or None,
                "fair_value": fair_value or None,
                "discount_to_fair_value": valuation_result["discount_to_fair_value"],
                "pe_ratio": pe_ratio or None,
                "peg_ratio": peg_ratio or None,
                "revenue_growth": revenue_growth,
                "eps_growth": eps_growth,
                "operating_margin": operating_margin,
                "roic": roic,
                "net_debt_ebitda": net_debt_ebitda,
                "free_cash_flow_margin": free_cash_flow_margin,
                "dividend_yield": dividend_yield,
                "quality_score": quality,
                "growth_score": growth,
                "valuation_score": valuation_result["valuation_score"],
                "news_catalyst_score": news_catalyst,
                "portfolio_fit_score": portfolio_fit,
                "financial_health_score": health,
                "liquidity_score": liquidity,
                "participation_score": participation_score,
                "nabi_score": score_result["score"],
                "decision": score_result["decision"],
                "investment_thesis": investment_thesis or None,
                "growth_catalysts": growth_catalysts or None,
                "main_reason": investment_thesis or None,
                "critical_risk": critical_risk or None,
                "notes": notes or None,
            }

            try:
                repo.create(payload)
                st.success(
                    f"{symbol} kaydedildi. "
                    f"NABI Score: {score_result['score']} — "
                    f"{score_result['decision']}"
                )
                st.rerun()
            except Exception as exc:
                st.error(f"Kayıt başarısız: {exc}")

st.subheader("Ara ve filtrele")
st.caption(
    "ETF/fon takibi Dashboard'daki Takip Edilen Fonlar bölümünden yönetilir."
)
q1, q2, q3, q4, q5 = st.columns([2, 1, 1, 1, 1])

query = q1.text_input("Ara")
asset_filter = q2.selectbox(
    "Tür",
    ["Tümü", "Hisse", "Fon", "Sukuk", "Altın", "Gümüş", "Diğer"],
)
market_filter = q3.selectbox(
    "Piyasa",
    ["Tümü", "ABD", "BIST", "TEFAS", "Global", "Diğer"],
)
decision_filter = q4.selectbox(
    "Karar",
    ["Tümü", "GÜÇLÜ ADAY", "İZLE", "UZAK DUR", "ELE"],
)
participation_filter = q5.selectbox(
    "Katılım",
    ["Tümü", "Uygun", "Kontrol Et", "Uygun Değil"],
)

rows = filter_equity_candidate_surface(
    repo.search(
        query=query,
        asset_type=None if asset_filter == "Tümü" else asset_filter,
        market=None if market_filter == "Tümü" else market_filter,
        decision=None if decision_filter == "Tümü" else decision_filter,
        participation_status=(
            None if participation_filter == "Tümü"
            else participation_filter
        ),
    )
)

st.caption(f"{len(rows)} aday bulundu")

for candidate in rows:
    action = render_candidate_card(candidate)

    if action == "edit":
        st.session_state.candidate_editor_id = candidate["id"]
        st.rerun()

    if action == "delete":
        st.session_state[f"delete_{candidate['id']}"] = True
        st.rerun()

for candidate in rows:
    delete_key = f"delete_{candidate['id']}"

    if st.session_state.get(delete_key):
        with st.container(border=True):
            st.warning(f"{candidate['symbol']} silinsin mi?")
            yes, no = st.columns(2)

            if yes.button(
                "Evet, sil",
                key=f"yes_{candidate['id']}",
                type="primary",
            ):
                repo.delete(candidate["id"])
                st.session_state.pop(delete_key, None)
                st.rerun()

            if no.button(
                "Vazgeç",
                key=f"no_{candidate['id']}",
            ):
                st.session_state.pop(delete_key, None)
                st.rerun()

edit_id = st.session_state.candidate_editor_id

if edit_id:
    candidate = repo.get_by_id(edit_id)

    if candidate:
        st.divider()
        st.subheader(f"✏️ {candidate['symbol']} düzenle")

        with st.form("candidate_edit_form"):
            company_name = st.text_input(
                "Şirket / Fon adı",
                value=candidate.get("company_name") or "",
            )
            edit_labels, edit_values = zip(*workflow_select_options())
            edit_status_label = st.selectbox(
                "Araştırma durumu",
                edit_labels,
                index=workflow_select_index(candidate.get("research_status")),
            )
            research_status = edit_values[
                list(edit_labels).index(edit_status_label)
            ]
            investment_thesis = st.text_area(
                "Yatırım tezi",
                value=candidate.get("investment_thesis") or "",
            )
            growth_catalysts = st.text_area(
                "Büyüme katalizörleri",
                value=candidate.get("growth_catalysts") or "",
            )
            critical_risk = st.text_area(
                "Kritik risk",
                value=candidate.get("critical_risk") or "",
            )
            notes = st.text_area(
                "Not",
                value=candidate.get("notes") or "",
            )

            save, cancel = st.columns(2)
            save_clicked = save.form_submit_button(
                "Değişiklikleri kaydet",
                type="primary",
            )
            cancel_clicked = cancel.form_submit_button("Vazgeç")

        if save_clicked:
            repo.update(
                edit_id,
                {
                    "company_name": company_name or None,
                    "research_status": research_status,
                    "investment_thesis": investment_thesis or None,
                    "growth_catalysts": growth_catalysts or None,
                    "main_reason": investment_thesis or None,
                    "critical_risk": critical_risk or None,
                    "notes": notes or None,
                },
            )
            st.session_state.candidate_editor_id = None
            st.rerun()

        if cancel_clicked:
            st.session_state.candidate_editor_id = None
            st.rerun()
