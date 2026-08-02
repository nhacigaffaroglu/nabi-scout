import pandas as pd
import streamlit as st

from repositories.candidate_repository import CandidateRepository
from services.academy_renderer import (
    render_compact_help,
    render_metric_explanation,
)
from services.supabase_client import get_supabase_client
from services.ui import configure_page, render_sidebar

configure_page("Aday Detayı 2.0 | NABI Scout", "🔎")
render_sidebar()

st.title("🔎 Aday Detayı 2.0")
repo = CandidateRepository(get_supabase_client())
rows = repo.get_all(order_by="nabi_score", descending=True)

if not rows:
    st.info("Henüz aday bulunmuyor.")
    st.stop()

labels = {
    f"{row['symbol']} — {row.get('company_name') or row['symbol']}": row["id"]
    for row in rows
}
selected = st.selectbox("Aday seç", list(labels.keys()))
candidate = repo.get_by_id(labels[selected])

a, b, c, d = st.columns([2.5, 1, 1, 1])
a.markdown(f"## {candidate['symbol']}")
a.write(candidate.get("company_name") or "Şirket adı yok")
a.caption(
    f"{candidate.get('investment_profile') or 'Profil yok'} · "
    f"Analiz güveni: {candidate.get('score_confidence') or '—'}"
)
b.metric("NABI Score", candidate.get("nabi_score") or 0)
c.metric(
    "Veri Tamlığı",
    f"%{candidate.get('data_completeness') or 0}",
)
d.metric("Karar", candidate.get("decision") or "—")

render_compact_help(
    "data_completeness",
    candidate.get("data_completeness"),
)

st.subheader("Yönetici Özeti")
st.write(
    candidate.get("memo_summary")
    or "Bu kayıt için yatırım özeti henüz üretilmedi."
)
st.info(
    candidate.get("memo_conclusion")
    or "Ek doğrulama gerekli."
)

left, right = st.columns(2)

with left:
    st.markdown("### Neden incelenebilir?")
    strengths = candidate.get("memo_strengths") or []
    if strengths:
        for item in strengths:
            st.success(item)
    else:
        st.write("Belirgin güçlü taraf bulunamadı.")

with right:
    st.markdown("### Neden uzak durulabilir?")
    risks = candidate.get("memo_risks") or []
    if risks:
        for item in risks:
            st.error(item)
    else:
        st.write("Belirgin kırmızı bayrak bulunamadı.")

watch_items = candidate.get("memo_watch_items") or []
if watch_items:
    st.markdown("### Hangi durumda yeniden incelenmeli?")
    for item in watch_items:
        st.warning(item)

st.subheader("Finansal Karnesi")
metric_map = [
    ("ROIC", "roic"),
    ("Gelir CAGR 3Y", "revenue_cagr_3y"),
    ("EPS CAGR 3Y", "eps_cagr_3y"),
    ("FCF CAGR 3Y", "fcf_cagr_3y"),
    ("FCF Marjı", "free_cash_flow_margin"),
    ("Borç/Özsermaye", "debt_to_equity"),
    ("Faiz Karşılama", "interest_coverage"),
    ("F/K", "pe_ratio"),
    ("EV/EBIT", "ev_to_ebit"),
    ("PEG", "peg_ratio_calculated"),
    ("Fiyat/FCF", "price_to_fcf"),
]

columns = st.columns(4)
for index, (label, key) in enumerate(metric_map):
    value = candidate.get(key)
    columns[index % 4].metric(
        label,
        "—" if value is None else f"{value:.2f}",
    )

st.subheader("Bu terimler ne anlama geliyor?")
tabs = st.tabs([
    "Kalite",
    "Büyüme",
    "Borç",
    "Değerleme",
])

with tabs[0]:
    render_metric_explanation("roic", candidate.get("roic"), expanded=True)
    render_metric_explanation(
        "free_cash_flow_margin",
        candidate.get("free_cash_flow_margin"),
    )

with tabs[1]:
    render_metric_explanation(
        "revenue_cagr_3y",
        candidate.get("revenue_cagr_3y"),
        expanded=True,
    )
    render_metric_explanation(
        "eps_cagr_3y",
        candidate.get("eps_cagr_3y"),
    )
    render_metric_explanation(
        "fcf_cagr_3y",
        candidate.get("fcf_cagr_3y"),
    )

with tabs[2]:
    render_metric_explanation(
        "debt_to_equity",
        candidate.get("debt_to_equity"),
        expanded=True,
    )
    render_metric_explanation(
        "interest_coverage",
        candidate.get("interest_coverage"),
    )

with tabs[3]:
    render_metric_explanation(
        "pe_ratio",
        candidate.get("pe_ratio"),
    )
    render_metric_explanation(
        "ev_to_ebit",
        candidate.get("ev_to_ebit"),
        expanded=True,
    )
    render_metric_explanation(
        "peg_ratio_calculated",
        candidate.get("peg_ratio_calculated"),
    )
    render_metric_explanation(
        "price_to_fcf",
        candidate.get("price_to_fcf"),
    )

st.subheader("Skor Haritası")
score_data = {
    "Kalite": candidate.get("quality_score") or 0,
    "Büyüme": candidate.get("growth_score") or 0,
    "Değerleme": candidate.get("valuation_score") or 0,
    "Finansal Güç": candidate.get("financial_health_score") or 0,
    "Risk": candidate.get("risk_score") or 0,
    "Likidite": candidate.get("liquidity_score") or 0,
}
st.bar_chart(
    pd.DataFrame(
        {"Puan": list(score_data.values())},
        index=list(score_data.keys()),
    )
)

st.caption(
    "NABI Score bir araştırma önceliklendirme puanıdır; "
    "tek başına yatırım tavsiyesi değildir."
)
