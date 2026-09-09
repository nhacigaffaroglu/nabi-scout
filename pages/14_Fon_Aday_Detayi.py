from __future__ import annotations

import streamlit as st

from components.turkiye_fund_candidate_detail_ui import (
    render_turkiye_fund_candidate_detail,
)
from services.turkiye_fund_candidate_detail import (
    CandidateDetailContractError,
    build_candidate_detail,
)
from services.turkiye_fund_navigation import (
    apply_turkiye_fund_report_handoff,
    is_turkiye_fund_nav_identity,
)
from services.turkiye_fund_scanner import load_default_scanner_result
from services.ui import prepare_protected_page

QUERY_PARAM = "candidate_fund"
SESSION_KEY = "turkiye_fund_candidate_detail_code"

client = prepare_protected_page("Fon Aday Detayı | NABI Scout", "🔎")
_ = client

st.title("🔎 Türkiye Fon Aday Detayı")
st.caption(
    "FUND14B aday mantığıyla uyumlu salt-okunur araştırma ekranı. "
    "Alım/satım, tahsis, 8E veya New Money kararı değildir."
)


@st.cache_data(show_spinner=True)
def _load_scanner() -> dict:
    return load_default_scanner_result().to_dict()


payload = _load_scanner()
rows = list(payload.get("rows") or [])
codes = [str(row.get("fund_code")) for row in rows if row.get("fund_code")]

requested = st.query_params.get(QUERY_PARAM)
session_code = st.session_state.get(SESSION_KEY)

default_code = requested or session_code
if default_code not in codes:
    eligible = [
        row
        for row in rows
        if row.get("scanner_status") == "READY"
        and row.get("participation") == "Uygun"
        and row.get("research_allowed") is True
        and isinstance(row.get("fi_score"), (int, float))
        and not isinstance(row.get("fi_score"), bool)
    ]
    eligible.sort(
        key=lambda row: (
            -(row.get("fi_score") if row.get("fi_score") is not None else -1.0),
            -(row.get("data_completeness") if row.get("data_completeness") is not None else -1.0),
            -(row.get("confidence") if row.get("confidence") is not None else -1.0),
            row.get("fund_code"),
        )
    )
    default_code = eligible[0]["fund_code"] if eligible else (codes[0] if codes else None)

if not codes or default_code is None:
    st.info("Scanner satırı yok.")
    st.stop()

index = codes.index(default_code) if default_code in codes else 0
selected = st.selectbox("Fon", codes, index=index)

st.session_state[SESSION_KEY] = selected
st.query_params[QUERY_PARAM] = selected

try:
    detail = build_candidate_detail(payload, selected)
except CandidateDetailContractError as exc:
    st.error(f"Candidate detail açılamadı: {exc}")
    st.stop()

st.markdown(f"### {detail.fund_code} — {detail.fund_name or detail.fund_code}")
if detail.founder:
    st.caption(detail.founder)

render_turkiye_fund_candidate_detail(detail)

st.divider()
nav_cols = st.columns([1, 1, 2])

with nav_cols[0]:
    if st.button("← Fon Tarama", use_container_width=True):
        st.switch_page("pages/13_Turkiye_Fon_Tarama.py")

with nav_cols[1]:
    if is_turkiye_fund_nav_identity(selected):
        if st.button("Fon Raporu →", use_container_width=True):
            apply_turkiye_fund_report_handoff(
                st.session_state,
                st.query_params,
                selected,
            )
            st.switch_page("pages/9_Fund_Report.py")
    else:
        st.caption(
            "Bu fon için standart Fon Raporu bağlantısı henüz etkin değil."
        )
