import pandas as pd
import streamlit as st

from config.scan_universe import (
    PARTICIPATION_DEFAULTS,
    SCAN_UNIVERSES,
)
from repositories.candidate_repository import CandidateRepository
from repositories.scan_repository import ScanRepository
from repositories.universe_repository import UniverseRepository
from services.collector_engine import CollectorEngine
from services.fmp_client import FMPClient
from services.sec_financial_client import SECFinancialClient
from services.supabase_client import get_supabase_client
from services.ui import configure_page, render_sidebar

configure_page("Scout Tarama | NABI Scout", "🛰️")
render_sidebar()

st.title("🛰️ Scout Financial Engine")
st.caption(
    "Fiyat/profil için FMP, resmi finansal tablolar için "
    "SEC Company Facts kullanır."
)

client = get_supabase_client()
candidate_repo = CandidateRepository(client)
scan_repo = ScanRepository(client)
universe_repo = UniverseRepository(client)

dynamic_names = universe_repo.get_universe_names()
options = (
    [f"Sabit: {name}" for name in SCAN_UNIVERSES]
    + [f"Dinamik: {name}" for name in dynamic_names]
)

selected = st.selectbox("Tarama evreni", options)

symbol_rows = []
if selected.startswith("Sabit: "):
    universe_name = selected.replace("Sabit: ", "", 1)
    symbol_rows = [
        {"symbol": symbol, "cik": None}
        for symbol in SCAN_UNIVERSES[universe_name]
    ]
else:
    universe_name = selected.replace("Dinamik: ", "", 1)
    symbol_rows = universe_repo.get_symbols(
        universe_name,
        limit=100,
    )

batch_size = st.slider(
    "Bu çalışmada taranacak sembol sayısı",
    min_value=1,
    max_value=max(
        1,
        min(25, len(symbol_rows)),
    ),
    value=min(
        5,
        max(1, len(symbol_rows)),
    ),
)

threshold = st.slider(
    "Aday havuzuna yazma eşiği",
    0,
    100,
    60,
)
portfolio_fit = st.slider(
    "Varsayılan portföy uyumu",
    0,
    100,
    55,
)
sec_email = st.text_input(
    "SEC iletişim e-postası",
    value="nabi-scout@example.com",
)

symbol_rows = symbol_rows[:batch_size]
st.write(
    "**Bu çalışmadaki semboller:**",
    ", ".join(row["symbol"] for row in symbol_rows),
)
st.warning(
    "Katılım durumu kesinleşmeyen hisseler 'Kontrol Et' "
    "olarak tutulur ve doğrudan yatırım önerisi sayılmaz."
)

if st.button("Finansal taramayı başlat", type="primary"):
    fmp = FMPClient.from_streamlit_secrets()
    sec = SECFinancialClient(contact_email=sec_email)
    engine = CollectorEngine(fmp, sec)

    run_id = scan_repo.create_run(
        universe_name,
        len(symbol_rows),
    )
    progress = st.progress(0)
    results = []
    updated = strong = error_count = 0

    for index, row in enumerate(symbol_rows, 1):
        symbol = row["symbol"]
        cik = row.get("cik")

        status, participation_score = (
            PARTICIPATION_DEFAULTS.get(
                symbol,
                ("Kontrol Et", 60),
            )
        )

        result = engine.collect(
            symbol,
            cik=cik,
            participation_status=status,
            participation_score=participation_score,
            portfolio_fit=portfolio_fit,
        )
        candidate = result["candidate"]

        should_write = (
            candidate.get("nabi_score", 0) >= threshold
            or candidate.get("decision") == "VERİ EKSİK"
        )

        if should_write:
            candidate_repo.upsert_by_symbol(candidate)
            updated += 1

        if candidate.get("decision") == "GÜÇLÜ ADAY":
            strong += 1

        if result["errors"]:
            error_count += 1

        scan_repo.add_result(run_id, result)

        results.append({
            "Sembol": symbol,
            "CIK": cik,
            "Durum": result["status"],
            "NABI Score": candidate.get("nabi_score"),
            "Kalite": candidate.get("quality_score"),
            "Büyüme": candidate.get("growth_score"),
            "ROIC": candidate.get("roic"),
            "Gelir Büy.": candidate.get(
                "revenue_growth"
            ),
            "Veri Tamlığı": candidate.get(
                "data_completeness"
            ),
            "Karar": candidate.get("decision"),
            "Kaydedildi": (
                "Evet" if should_write else "Hayır"
            ),
        })

        progress.progress(index / len(symbol_rows))
        fmp.pause(0.2)

    scan_repo.complete_run(
        run_id,
        len(symbol_rows),
        updated,
        strong,
        error_count,
    )

    st.success(
        f"Finansal tarama tamamlandı. "
        f"{updated} kayıt güncellendi."
    )
    st.dataframe(
        pd.DataFrame(results),
        use_container_width=True,
        hide_index=True,
    )
