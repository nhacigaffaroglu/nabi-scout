import pandas as pd
import streamlit as st

from repositories.candidate_repository import CandidateRepository
from services.academy_renderer import render_metric_explanation
from services.supabase_client import get_supabase_client
from services.ui import configure_page, render_sidebar

configure_page("Decision Center | NABI Scout", "🎯")
render_sidebar()

st.title("🎯 NABI Decision Center")
repo = CandidateRepository(get_supabase_client())
rows = repo.get_all(order_by="nabi_score", descending=True)

if not rows:
    st.info("Henüz aday bulunmuyor.")
    st.stop()

labels = {
    f"{row['symbol']} — {row.get('company_name') or row['symbol']}": row["id"]
    for row in rows
}
selected = st.selectbox("Şirket seç", list(labels.keys()))
candidate = repo.get_by_id(labels[selected])

st.markdown(f"## {candidate.get('symbol')} — {candidate.get('company_name')}")

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("NABI Score", candidate.get("nabi_score") or 0)
c2.metric("Conviction", candidate.get("conviction_score") or 0)
c3.metric("Opportunity", candidate.get("opportunity_score") or 0)
c4.metric(
    "Confidence",
    f"%{candidate.get('research_confidence') or 0}",
)
c5.metric("Yatırım Notu", candidate.get("investment_grade") or "—")

st.subheader("NABI Kararı")
st.success(
    candidate.get("decision_label")
    or candidate.get("decision")
    or "Karar üretilmedi."
)
st.write(
    candidate.get("decision_verdict")
    or candidate.get("memo_summary")
    or "Açıklama yok."
)
st.info(
    "**Önerilen sonraki adım:** "
    + (
        candidate.get("decision_action")
        or "Ek doğrulama yap."
    )
)

left, right = st.columns(2)

with left:
    st.markdown("### Kararı destekleyen nedenler")
    reasons = candidate.get("decision_top_reasons") or []
    if reasons:
        for item in reasons:
            st.success(item)
    else:
        st.write("Belirgin pozitif neden bulunamadı.")

with right:
    st.markdown("### Başlıca riskler")
    risks = candidate.get("decision_top_risks") or []
    if risks:
        for item in risks:
            st.error(item)
    else:
        st.write("Belirgin negatif neden bulunamadı.")

st.markdown("### Neden şimdi?")
for item in candidate.get("decision_why_now") or []:
    st.warning(item)

c1, c2 = st.columns(2)
with c1:
    st.markdown("### Kimler için uygun olabilir?")
    for item in candidate.get("decision_suitable_for") or []:
        st.write(f"✓ {item}")

with c2:
    st.markdown("### Kimler için uygun olmayabilir?")
    for item in candidate.get("decision_not_suitable_for") or []:
        st.write(f"• {item}")

st.subheader("Puan nasıl oluştu?")
factors = candidate.get("score_factors") or []

if factors:
    factor_df = pd.DataFrame(factors)
    st.dataframe(
        factor_df[
            ["label", "value", "impact", "meaning", "summary"]
        ],
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("Bu kayıt eski taramadan geliyor. Scanner v7 ile yeniden tarayın.")

st.subheader("Analiz güveni")
st.write(
    candidate.get("research_confidence_explanation")
    or "Güven açıklaması henüz yok."
)
for item in candidate.get("research_confidence_reasons") or []:
    st.warning(item)

st.subheader("İlgili kavramları öğren")
academy_keys = []
for item in factors:
    key = item.get("academy_key")
    if key and key not in academy_keys:
        academy_keys.append(key)

for key in academy_keys[:4]:
    render_metric_explanation(
        key,
        candidate.get(key),
    )

st.caption(
    "Decision Center yatırım kararını kullanıcı yerine vermez; "
    "araştırma önceliğini ve kararın dayanaklarını gösterir."
)
