import streamlit as st
from components.candidate_cards import render_candidate_card
from repositories.candidate_repository import CandidateRepository
from services.scoring_engine import calculate_nabi_score
from services.supabase_client import get_supabase_client
from services.ui import configure_page, render_sidebar

configure_page("Aday Havuzu | NABI Scout", "🧭")
render_sidebar()
st.title("🧭 Aday Havuzu")
repo = CandidateRepository(get_supabase_client())
st.session_state.setdefault("candidate_editor_id", None)

with st.expander("➕ Yeni aday ekle"):
    with st.form("create_candidate", clear_on_submit=True):
        c1,c2,c3 = st.columns(3)
        symbol = c1.text_input("Sembol *").strip().upper()
        company_name = c2.text_input("Şirket / Fon adı")
        asset_type = c3.selectbox("Varlık türü", ["Hisse","ETF","Fon","Sukuk","Altın","Gümüş","Diğer"])
        c4,c5,c6 = st.columns(3)
        market = c4.selectbox("Piyasa", ["ABD","BIST","TEFAS","Global","Diğer"])
        currency = c5.selectbox("Para birimi", ["USD","TRY","EUR","GBP","Diğer"])
        country = c6.text_input("Ülke")
        c7,c8 = st.columns(2)
        participation_status = c7.selectbox("Katılım uygunluğu", ["Kontrol Et","Uygun","Uygun Değil"])
        sector_theme = c8.text_input("Sektör / Tema")
        p1,p2,p3,p4 = st.columns(4)
        quality = p1.number_input("Kalite",0,100,50)
        growth = p2.number_input("Büyüme",0,100,50)
        valuation = p3.number_input("Değerleme",0,100,50)
        news_catalyst = p4.number_input("Haber & katalizör",0,100,50)
        p5,p6,p7,p8 = st.columns(4)
        portfolio_fit = p5.number_input("Portföy uyumu",0,100,50)
        risk = p6.number_input("Risk",0,100,50)
        liquidity = p7.number_input("Likidite",0,100,50)
        participation_score = p8.number_input("Katılım skoru",0,100,100)
        main_reason = st.text_area("Ana gerekçe")
        critical_risk = st.text_area("Kritik risk")
        notes = st.text_area("Not")
        submit = st.form_submit_button("Adayı kaydet", type="primary")

    if submit:
        if not symbol:
            st.error("Sembol zorunludur.")
        else:
            result = calculate_nabi_score(
                quality=quality,growth=growth,valuation=valuation,
                news_catalyst=news_catalyst,portfolio_fit=portfolio_fit,
                risk=risk,liquidity=liquidity,
                participation_score=participation_score,
                participation_status=participation_status
            )
            try:
                repo.create({
                    "symbol":symbol,"company_name":company_name or None,
                    "asset_type":asset_type,"market":market,"currency":currency,
                    "country":country or None,"participation_status":participation_status,
                    "sector_theme":sector_theme or None,"quality_score":quality,
                    "growth_score":growth,"valuation_score":valuation,
                    "news_catalyst_score":news_catalyst,
                    "portfolio_fit_score":portfolio_fit,"risk_score":risk,
                    "liquidity_score":liquidity,"participation_score":participation_score,
                    "nabi_score":result["score"],"decision":result["decision"],
                    "main_reason":main_reason or None,"critical_risk":critical_risk or None,
                    "notes":notes or None,"research_status":"Araştırılacak"
                })
                st.success(f"{symbol} kaydedildi.")
                st.rerun()
            except Exception as exc:
                st.error(f"Kayıt başarısız: {exc}")

f1,f2,f3,f4 = st.columns([2,1,1,1])
query = f1.text_input("Ara")
asset = f2.selectbox("Tür", ["Tümü","Hisse","ETF","Fon","Sukuk","Altın","Gümüş","Diğer"])
market = f3.selectbox("Piyasa", ["Tümü","ABD","BIST","TEFAS","Global","Diğer"])
decision = f4.selectbox("Karar", ["Tümü","GÜÇLÜ ADAY","İZLE","UZAK DUR","ELE","VERİ EKSİK"])

rows = repo.search(
    query=query,
    asset_type=None if asset=="Tümü" else asset,
    market=None if market=="Tümü" else market,
    decision=None if decision=="Tümü" else decision
)
st.caption(f"{len(rows)} aday bulundu")

for candidate in rows:
    action = render_candidate_card(candidate)
    if action == "edit":
        st.session_state.candidate_editor_id = candidate["id"]
        st.rerun()
    if action == "delete":
        if st.button(f"{candidate['symbol']} silmeyi onayla", key=f"confirm_{candidate['id']}", type="primary"):
            repo.delete(candidate["id"])
            st.rerun()

edit_id = st.session_state.candidate_editor_id
if edit_id:
    c = repo.get_by_id(edit_id)
    st.divider()
    st.subheader(f"✏️ {c['symbol']} düzenle")
    with st.form("edit_candidate"):
        company_name = st.text_input("Şirket / Fon adı", value=c.get("company_name") or "")
        research_status = st.selectbox("Araştırma durumu", ["Araştırılacak","İnceleniyor","Tamamlandı","Arşiv"], index=["Araştırılacak","İnceleniyor","Tamamlandı","Arşiv"].index(c.get("research_status") or "Araştırılacak"))
        main_reason = st.text_area("Ana gerekçe", value=c.get("main_reason") or "")
        critical_risk = st.text_area("Kritik risk", value=c.get("critical_risk") or "")
        notes = st.text_area("Not", value=c.get("notes") or "")
        save = st.form_submit_button("Kaydet", type="primary")
        cancel = st.form_submit_button("Vazgeç")
    if save:
        repo.update(edit_id, {"company_name":company_name or None,"research_status":research_status,"main_reason":main_reason or None,"critical_risk":critical_risk or None,"notes":notes or None})
        st.session_state.candidate_editor_id = None
        st.rerun()
    if cancel:
        st.session_state.candidate_editor_id = None
        st.rerun()
