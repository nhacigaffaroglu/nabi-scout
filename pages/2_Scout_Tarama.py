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
from services.supabase_client import get_supabase_client
from services.ui import configure_page, render_sidebar

configure_page("Scout Tarama | NABI Scout", "🛰️")
render_sidebar()

st.title("🛰️ Scout Tarama")
st.caption(
    "Sabit veya Universe Engine tarafından oluşturulmuş evreni "
    "FMP üzerinden analiz eder."
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

if selected.startswith("Sabit: "):
    universe_name = selected.replace("Sabit: ", "", 1)
    symbols = SCAN_UNIVERSES[universe_name]
else:
    universe_name = selected.replace("Dinamik: ", "", 1)
    rows = universe_repo.get_symbols(universe_name, limit=100)
    symbols = [row["symbol"] for row in rows]

batch_size = st.slider(
    "Bu çalışmada taranacak sembol sayısı",
    min_value=1,
    max_value=max(1, min(50, len(symbols))),
    value=min(10, max(1, len(symbols))),
)

threshold = st.slider(
    "Aday havuzuna yazma eşiği",
    0, 100, 60,
)
portfolio_fit = st.slider(
    "Varsayılan portföy uyumu",
    0, 100, 55,
)

symbols = symbols[:batch_size]
st.write("**Bu çalışmadaki semboller:**", ", ".join(symbols))
st.warning(
    "Ücretsiz API çağrı sınırını korumak için dinamik evren "
    "küçük partiler halinde taranır."
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
            symbol,
            ("Kontrol Et", 60),
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
            "Veri Tamlığı": candidate.get(
                "data_completeness"
            ),
            "Kaydedildi": (
                "Evet" if should_write else "Hayır"
            ),
            "Erişim Sorunu": len(result["errors"]),
        })

        progress.progress(index / len(symbols))
        fmp.pause()

    scan_repo.complete_run(
        run_id,
        len(symbols),
        updated,
        strong,
        error_count,
    )

    st.success(
        f"Tarama tamamlandı. {updated} kayıt güncellendi."
    )
    st.dataframe(
        pd.DataFrame(results),
        use_container_width=True,
        hide_index=True,
    )
