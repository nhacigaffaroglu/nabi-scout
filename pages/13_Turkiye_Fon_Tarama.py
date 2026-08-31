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
funnel = dict(payload.get("coverage_funnel") or {}).get("gates") or {}
st.markdown(
    f"Keşfedilen **{payload['discovered_count']}** · "
    f"Aktif **{payload['active_count']}** · "
    f"Uygun **{payload['participation_uygun_count']}** · "
    f"Scanner READY **{payload['scanner_ready_count']}** · "
    f"İnceleme **{payload['review_required_count']}**"
)

st.subheader("Kapsama hunisi")
if funnel:
    active = max(int(payload.get("active_count") or 1), 1)
    funnel_rows = [
        {
            "GATE": key,
            "COUNT": value,
            "% ACTIVE": round(100.0 * int(value) / active, 2) if key != "discovered" else None,
        }
        for key, value in funnel.items()
    ]
    st.dataframe(pd.DataFrame(funnel_rows), hide_index=True, use_container_width=True)

cols = st.columns(8)
with cols[0]:
    categories = ["(tümü)"] + sorted({row["category"] for row in payload["rows"]})
    category = st.selectbox("Kategori", categories)
with cols[1]:
    managers = ["(tümü)"] + sorted({str(row.get("founder") or "UNKNOWN") for row in payload["rows"]})
    manager = st.selectbox("Yönetici", managers)
with cols[2]:
    participation = st.selectbox(
        "Participation",
        ["(tümü)", "Uygun", "Kontrol Et", "Uygun Değil"],
    )
with cols[3]:
    fi_state = st.selectbox(
        "FI state",
        ["(tümü)"] + sorted({str(row.get("fi_state") or "") for row in payload["rows"] if row.get("fi_state")}),
    )
with cols[4]:
    status = st.selectbox("Durum", ["(tümü)", "READY", "REVIEW_REQUIRED", "BLOCKED", "PARTIAL"])
with cols[5]:
    min_completeness = st.slider("Min. completeness", 0.0, 1.0, 0.0, 0.05)
with cols[6]:
    min_confidence = st.slider("Min. confidence", 0.0, 1.0, 0.0, 0.05)
with cols[7]:
    top_n = st.number_input("Top N", min_value=1, max_value=50, value=10)

rows = list(payload["rows"])
if category != "(tümü)":
    rows = [row for row in rows if row["category"] == category]
if manager != "(tümü)":
    rows = [row for row in rows if str(row.get("founder") or "UNKNOWN") == manager]
if participation != "(tümü)":
    rows = [row for row in rows if row.get("participation") == participation]
if fi_state != "(tümü)":
    rows = [row for row in rows if row.get("fi_state") == fi_state]
if status != "(tümü)":
    rows = [row for row in rows if row.get("scanner_status") == status]
rows = [
    row
    for row in rows
    if ((row.get("data_completeness") or 0) >= min_completeness or row.get("data_completeness") is None)
    and ((row.get("confidence") or 0) >= min_confidence or row.get("confidence") is None)
]
ready = [row for row in rows if row.get("scanner_status") == "READY"]
ready = sorted(ready, key=lambda item: (-(item.get("fi_score") or -1), item.get("fund_code")))[: int(top_n)]

st.subheader("Kategori adayları")
if ready:
    table = pd.DataFrame(
        [
            {
                "CATEGORY": row["category"],
                "RANK": row["rank"],
                "FUND": row["fund_code"],
                "NAME": row.get("fund_name"),
                "MANAGER": row.get("founder"),
                "FI SCORE": row["fi_score"],
                "FI STATE": row["fi_state"],
                "CONFIDENCE": row["confidence"],
                "COMPLETENESS": row.get("data_completeness"),
                "PARTICIPATION": row["participation"],
                "EXPOSURE": row["exposure"],
                "1Y RETURN": row["return_1y"],
                "MAX DRAWDOWN": row["max_drawdown"],
                "STATUS": row["scanner_status"],
                "REASON": row["reason"],
            }
            for row in ready
        ]
    )
    st.dataframe(table, hide_index=True, use_container_width=True)
else:
    st.info("READY araştırma adayı yok.")

st.caption("Bu liste bir alım listesi değildir.")

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

st.subheader("İnceleme nedenleri")
reason_counts = dict(payload.get("review_reason_counts") or {})
if reason_counts:
    st.dataframe(
        pd.DataFrame(
            [{"REASON": key, "COUNT": value} for key, value in sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))]
        ),
        hide_index=True,
        use_container_width=True,
    )

st.subheader("İnceleme kuyruğu")
queue = payload.get("review_queue") or []
if queue:
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "FUND": row["fund_code"],
                    "MANAGER": row.get("founder"),
                    "STATUS": row["scanner_status"],
                    "PARTICIPATION": row.get("participation"),
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
