import pandas as pd
import streamlit as st

from config.scan_universe import SCAN_UNIVERSES, PARTICIPATION_DEFAULTS
from repositories.candidate_repository import CandidateRepository
from repositories.scan_repository import ScanRepository
from services.collector_engine import CollectorEngine
from services.fmp_client import FMPClient
from services.supabase_client import get_supabase_client
from services.ui import configure_page, render_sidebar

configure_page("Scout Tarama | NABI Scout", "🛰️")
render_sidebar()

st.title("🛰️ Scout Tarama")
st.caption("FMP verilerini toplar, puanlar ve Supabase'e kaydeder.")

client = get_supabase_client()
candidate_repo = CandidateRepository(client)
scan_repo = ScanRepository(client)

universe_name = st.selectbox("Tarama evreni", list(SCAN_UNIVERSES))
symbols = SCAN_UNIVERSES[universe_name]
threshold = st.slider("Aday havuzuna yazma eşiği", 0, 100, 0)
portfolio_fit = st.slider("Varsayılan portföy uyumu", 0, 100, 55)

st.write("**Semboller:**", ", ".join(symbols))
st.warning(
    "Katılım durumu 'Kontrol Et' olan hisseler doğrudan yatırım önerisi değildir."
)

if st.button("Taramayı başlat", type="primary"):
    fmp = FMPClient.from_streamlit_secrets()
    engine = CollectorEngine(fmp)
    run_id = scan_repo.create_run(universe_name, len(symbols))
    progress = st.progress(0)
    results = []
    updated = strong = error_count = 0

    for index, symbol in enumerate(symbols, 1):
        status, part_score = PARTICIPATION_DEFAULTS.get(
            symbol, ("Kontrol Et", 60)
        )
        result = engine.collect(
            symbol,
            participation_status=status,
            participation_score=part_score,
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
            "Durum": result["status"],
            "NABI Score": candidate.get("nabi_score"),
            "Karar": candidate.get("decision"),
            "Veri Tamlığı": candidate.get("data_completeness"),
            "Kaydedildi": "Evet" if should_write else "Hayır",
            "Erişim Sorunu": len(result["errors"]),
        })
        progress.progress(index / len(symbols))
        fmp.pause()

    scan_repo.complete_run(
        run_id, len(symbols), updated, strong, error_count
    )
    st.success(f"Tarama tamamlandı. {updated} kayıt güncellendi.")
    st.dataframe(
        pd.DataFrame(results),
        use_container_width=True,
        hide_index=True,
    )
