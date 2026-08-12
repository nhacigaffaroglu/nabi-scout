import pandas as pd
import streamlit as st

from repositories.candidate_repository import CandidateRepository
from services.academy_renderer import render_metric_explanation
from services.ui import prepare_protected_page

client = prepare_protected_page("Investment Thesis | NABI Scout", "📑")
st.title("📑 NABI Investment Thesis")

repo = CandidateRepository(client)
rows = repo.get_all(order_by="nabi_score", descending=True)
if not rows:
    st.info("Henüz aday bulunmuyor.")
    st.stop()

labels = {f"{r['symbol']} — {r.get('company_name') or r['symbol']}": r["id"] for r in rows}
selected = st.selectbox("Şirket seç", list(labels.keys()))
candidate = repo.get_by_id(labels[selected])

st.markdown(f"## {candidate.get('symbol')} — {candidate.get('company_name')}")
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("NABI Score", candidate.get("nabi_score") or 0)
c2.metric("Conviction", candidate.get("conviction_score") or 0)
c3.metric("Opportunity", candidate.get("opportunity_score") or 0)
c4.metric("Confidence", f"%{candidate.get('research_confidence') or 0}")
c5.metric("Yatırım Notu", candidate.get("investment_grade") or "—")

st.subheader("Yatırım Tezi")
st.info(candidate.get("thesis_type") or "Bu kayıt Scanner v8 ile henüz taranmadı.")
st.write(candidate.get("thesis_summary") or candidate.get("decision_verdict") or "Tez özeti yok.")

left, right = st.columns(2)
with left:
    st.markdown("### Tezi destekleyen noktalar")
    for item in candidate.get("thesis_strengths") or []:
        st.success(item)
with right:
    st.markdown("### Tezi zayıflatan noktalar")
    for item in candidate.get("thesis_concerns") or []:
        st.error(item)

st.subheader("Senaryolar")
st.markdown("#### Olumlu senaryo")
st.write(candidate.get("thesis_bull_case") or "Olumlu senaryo henüz üretilmedi.")
st.markdown("#### Olumsuz senaryo")
st.write(candidate.get("thesis_bear_case") or "Olumsuz senaryo henüz üretilmedi.")

st.subheader("Hangi koşullarda yeniden incelenmeli?")
conditions = candidate.get("thesis_revisit_conditions") or []
if conditions:
    for item in conditions:
        st.warning(item)
else:
    st.write(candidate.get("thesis_revisit_trigger") or "Bir sonraki finansal raporda yeniden değerlendir.")

st.subheader("Değerleme görüşü")
st.write(candidate.get("thesis_valuation_view") or "Değerleme görüşü üretilemedi.")

st.subheader("Puanın kanıtları")
factors = candidate.get("score_factors") or []
if factors:
    st.dataframe(
        pd.DataFrame(factors)[["label", "value", "impact", "meaning", "summary"]],
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("Scanner v8 ile yeniden tarama yapın.")

st.subheader("İlgili finansal kavramları öğren")
academy_keys = []
for item in factors:
    key = item.get("academy_key")
    if key and key not in academy_keys:
        academy_keys.append(key)

for key in academy_keys[:4]:
    render_metric_explanation(key, candidate.get(key))

st.caption(
    "Investment Thesis Engine yatırım tavsiyesi üretmez; "
    "mevcut finansal verilerden araştırma tezi oluşturur."
)
