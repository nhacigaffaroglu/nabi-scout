import pandas as pd
import streamlit as st

from repositories.candidate_repository import CandidateRepository
from repositories.watchlist_repository import WatchlistRepository
from services.academy_ui import (
    render_metric_card,
    render_metric_explanation,
)
from services.supabase_client import get_supabase_client
from services.ui import configure_page, render_sidebar

configure_page("Company Report | NABI Scout", "📄")
render_sidebar()

st.title("📄 NABI Company Report")

repo = CandidateRepository(get_supabase_client())
watchlist_repo = WatchlistRepository(get_supabase_client())
candidate = st.session_state.get("company_report_candidate")

if candidate is None:
    rows = repo.get_all(
        order_by="nabi_score",
        descending=True,
    )

    if not rows:
        st.info(
            "Henüz raporlanacak şirket bulunmuyor. "
            "Önce Scout Scanner ekranında tarama yapın."
        )
        st.stop()

    query_symbol = st.query_params.get("symbol")
    default_index = 0
    labels = []
    row_lookup = {}

    for index, row in enumerate(rows):
        label = (
            f"{row['symbol']} — "
            f"{row.get('company_name') or row['symbol']}"
        )
        labels.append(label)
        row_lookup[label] = row["id"]

        if query_symbol and row["symbol"] == query_symbol:
            default_index = index

    selected = st.selectbox(
        "Şirket seç",
        labels,
        index=default_index,
    )
    candidate = repo.get_by_id(row_lookup[selected])

candidate_id = candidate.get("id")
if not candidate_id and candidate.get("symbol"):
    db_candidate = repo.get_by_symbol(candidate["symbol"])
    if db_candidate:
        candidate_id = db_candidate.get("id")
        candidate = {**db_candidate, **candidate, "id": candidate_id}

symbol = candidate.get("symbol") or "—"
company = candidate.get("company_name") or symbol

top_left, top_right = st.columns([4, 1])

with top_left:
    st.markdown(f"## {symbol} — {company}")
    st.caption(
        f"{candidate.get('thesis_type') or 'Tez türü yok'} · "
        f"{candidate.get('investment_profile') or 'Profil yok'}"
    )

with top_right:
    is_watched = (
        watchlist_repo.is_watched(str(candidate_id))
        if candidate_id
        else False
    )

    if candidate_id:
        if is_watched:
            if st.button(
                "✓ İzleniyor — çıkar",
                use_container_width=True,
            ):
                watchlist_repo.deactivate(str(candidate_id))
                st.rerun()
        elif st.button(
            "⭐ İzleme listesine ekle",
            use_container_width=True,
        ):
            watchlist_repo.add_candidate(str(candidate_id))
            st.rerun()

    if st.button(
        "← Tarama ekranı",
        use_container_width=True,
    ):
        st.switch_page("pages/2_Scout_Tarama.py")

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("NABI Skoru", candidate.get("nabi_score") or 0)
c2.metric(
    "Veri Güveni",
    f"%{candidate.get('research_confidence') or 0}",
    help=(
        "Analizde kullanılan finansal verilerin kapsam ve "
        "güvenilirlik düzeyi."
    ),
)
c3.metric(
    "Araştırma Güveni",
    candidate.get("conviction_score") or 0,
    help=(
        "Şirket hakkındaki araştırma sonucunun ne kadar "
        "güçlü ve tutarlı olduğuna ilişkin birleşik puan."
    ),
)
c4.metric(
    "Fırsat Potansiyeli",
    candidate.get("opportunity_score") or 0,
    help=(
        "Kalite, büyüme ve değerleme birlikte "
        "değerlendirildiğinde araştırma fırsatı."
    ),
)
c5.metric(
    "Yatırım Notu",
    candidate.get("investment_grade") or "—",
)

st.subheader("Karar özeti")
decision = (
    candidate.get("decision_label")
    or candidate.get("decision")
    or "Karar üretilmedi."
)

if decision in {
    "ŞİMDİLİK UZAK DUR",
    "VERİ EKSİK — ÖN ELEME",
}:
    st.error(decision)
elif decision in {
    "YÜKSEK ÖNCELİKLİ ARAŞTIRMA ADAYI",
    "ARAŞTIRMA ADAYI",
}:
    st.success(decision)
else:
    st.warning(decision)

freshness_label = candidate.get("freshness_label")
if freshness_label:
    period_end = candidate.get("financial_period_end") or "—"
    period_age = candidate.get("period_age_days")
    age_text = f"{period_age} gün" if period_age is not None else "—"
    st.caption(
        f"Finansal dönem: {period_end} · {freshness_label} · {age_text}"
    )

st.write(
    candidate.get("decision_verdict")
    or candidate.get("memo_summary")
    or "Karar açıklaması bulunmuyor."
)
st.info(
    "**Önerilen araştırma adımı:** "
    + (
        candidate.get("decision_action")
        or "Ek finansal doğrulama yap."
    )
)

st.subheader("Yatırım tezi")
st.info(
    candidate.get("thesis_type")
    or "Bu kayıt Investment Thesis Engine ile henüz analiz edilmedi."
)
st.write(
    candidate.get("thesis_summary")
    or "Yatırım tezi özeti bulunmuyor."
)

left, right = st.columns(2)

with left:
    st.markdown("### Tezi destekleyen noktalar")
    strengths = candidate.get("thesis_strengths") or []
    if strengths:
        for item in strengths:
            st.success(item)
    else:
        st.write("Belirgin güçlü tez unsuru bulunamadı.")

with right:
    st.markdown("### Tezi zayıflatan noktalar")
    concerns = candidate.get("thesis_concerns") or []
    if concerns:
        for item in concerns:
            st.error(item)
    else:
        st.write("Belirgin tez riski bulunamadı.")

st.subheader("Senaryo analizi")
bull_col, bear_col = st.columns(2)

with bull_col:
    st.markdown("### Olumlu senaryo")
    st.write(
        candidate.get("thesis_bull_case")
        or "Olumlu senaryo henüz üretilmedi."
    )

with bear_col:
    st.markdown("### Olumsuz senaryo")
    st.write(
        candidate.get("thesis_bear_case")
        or "Olumsuz senaryo henüz üretilmedi."
    )

st.subheader("Hangi koşullarda yeniden incelenmeli?")
conditions = candidate.get("thesis_revisit_conditions") or []

if conditions:
    for item in conditions:
        st.warning(item)
else:
    st.write(
        candidate.get("thesis_revisit_trigger")
        or (
            "Bir sonraki finansal raporda büyüme, "
            "nakit üretimi ve değerleme yeniden kontrol edilmeli."
        )
    )

st.subheader("Değerleme görüşü")
st.write(
    candidate.get("thesis_valuation_view")
    or "Değerleme görüşü üretilemedi."
)

st.subheader("Puanın kanıtları")
factors = candidate.get("score_factors") or []

if factors:
    factor_rows = []

    for item in factors:
        impact = item.get("impact")
        impact_label = {
            "positive": "Olumlu",
            "negative": "Olumsuz",
            "neutral": "Nötr",
        }.get(impact, impact or "—")

        factor_rows.append({
            "Gösterge": item.get("label"),
            "Değer": item.get("value"),
            "Etkisi": impact_label,
            "Ne anlatıyor?": item.get("meaning"),
            "NABI yorumu": item.get("summary"),
        })

    st.dataframe(
        pd.DataFrame(factor_rows),
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info(
        "Puan gerekçeleri için şirketi güncel Scanner ile yeniden tarayın."
    )

st.subheader("Finansal göstergeler")
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

st.subheader("🎓 NABI Academy — Bu rakamlar ne anlatıyor?")
st.caption(
    "Her kart finansal metriği sade dille açıklar ve bu şirket için yorumlar."
)

academy_tabs = st.tabs([
    "Kalite",
    "Büyüme",
    "Borç ve Güç",
    "Değerleme",
])

with academy_tabs[0]:
    render_metric_card(
        "roic",
        candidate.get("roic"),
    )
    render_metric_card(
        "free_cash_flow_margin",
        candidate.get("free_cash_flow_margin"),
    )

with academy_tabs[1]:
    render_metric_card(
        "revenue_cagr_3y",
        candidate.get("revenue_cagr_3y"),
    )
    render_metric_card(
        "eps_cagr_3y",
        candidate.get("eps_cagr_3y"),
    )
    render_metric_card(
        "fcf_cagr_3y",
        candidate.get("fcf_cagr_3y"),
    )

with academy_tabs[2]:
    render_metric_card(
        "debt_to_equity",
        candidate.get("debt_to_equity"),
    )
    render_metric_card(
        "interest_coverage",
        candidate.get("interest_coverage"),
    )

with academy_tabs[3]:
    render_metric_card(
        "pe_ratio",
        candidate.get("pe_ratio"),
    )
    render_metric_card(
        "ev_to_ebit",
        candidate.get("ev_to_ebit"),
    )
    render_metric_card(
        "peg_ratio_calculated",
        candidate.get("peg_ratio_calculated"),
    )
    render_metric_card(
        "price_to_fcf",
        candidate.get("price_to_fcf"),
    )

st.subheader("Raporun veri güveni")
render_metric_explanation(
    "data_completeness",
    candidate.get("data_completeness"),
    expanded=True,
)

st.caption(
    "NABI Academy yatırım tavsiyesi üretmez. "
    "Finansal metrikleri sade ve açıklanabilir hâle getirir."
)
