import streamlit as st

from services.academy_renderer import render_metric_explanation
from services.financial_glossary import GLOSSARY
from services.ui import prepare_protected_page

prepare_protected_page("NABI Akademi | NABI Scout", "📚")

st.title("📚 NABI Akademi")
st.caption(
    "Scout'ta kullanılan finansal kavramları sade Türkçeyle öğren."
)

search = st.text_input(
    "Kavram ara",
    placeholder="ROIC, borç, nakit, değerleme...",
).strip().lower()

categories = {
    "Kalite ve Verimlilik": [
        "roic",
        "roe",
        "free_cash_flow_margin",
    ],
    "Büyüme": [
        "revenue_cagr_3y",
        "eps_cagr_3y",
        "fcf_cagr_3y",
    ],
    "Borç ve Finansal Güç": [
        "debt_to_equity",
        "interest_coverage",
    ],
    "Değerleme": [
        "pe_ratio",
        "ev_to_ebit",
        "peg_ratio_calculated",
        "price_to_fcf",
    ],
    "Analiz Güveni": [
        "data_completeness",
    ],
}

for category, keys in categories.items():
    matching = []

    for key in keys:
        metric = GLOSSARY[key]
        haystack = (
            f"{key} {metric['title']} {metric['simple']} "
            f"{metric['why']}"
        ).lower()
        if not search or search in haystack:
            matching.append(key)

    if matching:
        st.header(category)
        for key in matching:
            render_metric_explanation(key, None)
