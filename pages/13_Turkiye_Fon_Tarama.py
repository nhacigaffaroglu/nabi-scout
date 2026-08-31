import pandas as pd
import streamlit as st

from services.turkiye_fund_navigation import (
    apply_turkiye_fund_report_handoff,
    is_turkiye_fund_nav_identity,
)
from services.turkiye_fund_scanner import load_default_scanner_result
from services.turkiye_fund_universe_contract import SCANNER_NOT_A_BUY
from services.ui import prepare_protected_page

client = prepare_protected_page("Türkiye Fon Tarama | NABI Scout", "🧭")
_ = client

st.title("🧭 Türkiye Katılım Fonu Tarama")
st.caption(
    "Araştırma adayları. Satın alma, 8E veya New Money kararı değildir. "
    + SCANNER_NOT_A_BUY
)


@st.cache_data(show_spinner=True)
def _load_scanner():
    result = load_default_scanner_result()
    return result.to_dict()


payload = _load_scanner()
st.markdown(
    f"Keşfedilen **{payload['discovered_count']}** · "
    f"Aktif **{payload['active_count']}** · "
    f"Uygun **{payload['participation_uygun_count']}** · "
    f"Scanner READY **{payload['scanner_ready_count']}** · "
    f"İnceleme **{payload['review_required_count']}**"
)

cols = st.columns(5)
with cols[0]:
    categories = ["(tümü)"] + sorted({row["category"] for row in payload["rows"]})
    category = st.selectbox("Kategori", categories)
with cols[1]:
    participation = st.selectbox(
        "Participation",
        ["(tümü)", "Uygun", "Kontrol Et", "Uygun Değil"],
    )
with cols[2]:
    fi_state = st.selectbox(
        "FI state",
        ["(tümü)"] + sorted({str(row.get("fi_state") or "") for row in payload["rows"] if row.get("fi_state")}),
    )
with cols[3]:
    min_completeness = st.slider("Min. completeness", 0.0, 1.0, 0.0, 0.05)
with cols[4]:
    top_n = st.number_input("Top N", min_value=1, max_value=50, value=10)

rows = list(payload["rows"])
if category != "(tümü)":
    rows = [row for row in rows if row["category"] == category]
if participation != "(tümü)":
    rows = [row for row in rows if row.get("participation") == participation]
if fi_state != "(tümü)":
    rows = [row for row in rows if row.get("fi_state") == fi_state]
rows = [
    row
    for row in rows
    if (row.get("data_completeness") or 0) >= min_completeness or row.get("data_completeness") is None
]
ready = [row for row in rows if row.get("scanner_status") == "READY"]
ready = sorted(ready, key=lambda item: item.get("rank") or 99)[: int(top_n)]

st.subheader("Kategori adayları")
if ready:
    table = pd.DataFrame(
        [
            {
                "CATEGORY": row["category"],
                "RANK": row["rank"],
                "FUND": row["fund_code"],
                "FI SCORE": row["fi_score"],
                "FI STATE": row["fi_state"],
                "CONFIDENCE": row["confidence"],
                "PARTICIPATION": row["participation"],
                "EXPOSURE": row["exposure"],
                "1Y RETURN": row["return_1y"],
                "MAX DRAWDOWN": row["max_drawdown"],
                "DATA COMPLETENESS": row["data_completeness"],
                "STATUS": row["scanner_status"],
                "REASON": row["reason"],
            }
            for row in ready
        ]
    )
    st.dataframe(table, hide_index=True, use_container_width=True)
else:
    st.info("READY araştırma adayı yok.")

selected = st.selectbox(
    "Fon detayı",
    ["(seçiniz)"] + [row["fund_code"] for row in payload["rows"]],
)
if selected != "(seçiniz)":
    detail = next(row for row in payload["rows"] if row["fund_code"] == selected)
    st.json(detail)
    if is_turkiye_fund_nav_identity(selected):
        if st.button("Fon Raporu", key=f"scanner_fund_report_{selected}"):
            apply_turkiye_fund_report_handoff(
                st.session_state,
                st.query_params,
                selected,
            )
            st.switch_page("pages/9_Fund_Report.py")
    else:
        st.caption("Production snapshot yok. Canonical identity ile araştırma detayı yukarıdadır. Buy yok.")

st.subheader("İnceleme kuyruğu")
queue = payload.get("review_queue") or []
if queue:
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "FUND": row["fund_code"],
                    "STATUS": row["scanner_status"],
                    "Missing/Blocked": ", ".join(row.get("missing_evidence") or ()) or row.get("reason"),
                }
                for row in queue
            ]
        ),
        hide_index=True,
        use_container_width=True,
    )
else:
    st.caption("İnceleme kuyruğu boş.")
