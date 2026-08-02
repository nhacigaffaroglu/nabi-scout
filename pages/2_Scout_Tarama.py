import pandas as pd
import streamlit as st

from config.scan_universe import (
    PARTICIPATION_DEFAULTS,
    SCAN_UNIVERSES,
)
from repositories.candidate_repository import CandidateRepository
from repositories.scan_repository import ScanRepository
from repositories.universe_repository import UniverseRepository
from services.fmp_client import FMPClient
from services.scanner_v4_engine import ScannerV4Engine
from services.sec_financial_client import SECFinancialClient
from services.supabase_client import get_supabase_client
from services.ui import configure_page, render_sidebar

configure_page("Scout Scanner v4 | NABI Scout", "🧠")
render_sidebar()

st.title("🧠 Scout Scanner v4")
st.caption(
    "Finansal kalite, büyüme, değerleme, risk ve açıklanabilir "
    "NABI Score v4 üretir."
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
    all_rows = [
        {
            "symbol": symbol,
            "cik": None,
            "company_name": symbol,
            "exchange": None,
            "is_etf": False,
        }
        for symbol in SCAN_UNIVERSES[universe_name]
    ]
else:
    universe_name = selected.replace("Dinamik: ", "", 1)
    all_rows = universe_repo.get_symbols(
        universe_name,
        limit=2000,
    )

if not all_rows:
    st.warning("Seçilen evrende sembol bulunmuyor.")
    st.stop()

c1, c2 = st.columns(2)
start_index = c1.number_input(
    "Başlangıç sırası",
    min_value=1,
    max_value=len(all_rows),
    value=1,
    step=1,
)
batch_size = c2.slider(
    "Bu çalışmada taranacak sembol sayısı",
    min_value=1,
    max_value=min(25, len(all_rows)),
    value=min(5, len(all_rows)),
)

threshold = st.slider(
    "Aday havuzuna yazma eşiği",
    0,
    100,
    60,
)
minimum_completeness = st.slider(
    "Minimum veri tamlığı",
    0,
    100,
    65,
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

start = int(start_index) - 1
selected_rows = all_rows[start:start + batch_size]

st.write(
    "**Bu çalışmadaki semboller:**",
    ", ".join(row["symbol"] for row in selected_rows),
)
st.info(
    f"Evren büyüklüğü: {len(all_rows)} · "
    f"Taranan aralık: {start + 1}–{start + len(selected_rows)}"
)

if st.button("Scanner v4 taramasını başlat", type="primary"):
    fmp = FMPClient.from_streamlit_secrets()
    sec = SECFinancialClient(contact_email=sec_email)
    engine = ScannerV4Engine(fmp, sec)

    run_id = scan_repo.create_run(
        f"{universe_name} [{start + 1}-{start + len(selected_rows)}]",
        len(selected_rows),
    )
    progress = st.progress(0)
    results = []
    updated = strong = error_count = excluded_count = 0

    for index, row in enumerate(selected_rows, 1):
        symbol = row["symbol"]
        participation_status, participation_score = (
            PARTICIPATION_DEFAULTS.get(
                symbol,
                ("Kontrol Et", 60),
            )
        )

        result = engine.analyze(
            symbol=symbol,
            cik=row.get("cik"),
            company_name=row.get("company_name"),
            exchange=row.get("exchange"),
            is_etf=row.get("is_etf", False),
            participation_status=participation_status,
            participation_score=participation_score,
            portfolio_fit=portfolio_fit,
        )
        candidate = result["candidate"]

        should_write = (
            not result["excluded"]
            and candidate.get("data_completeness", 0)
            >= minimum_completeness
            and candidate.get("nabi_score", 0)
            >= threshold
            and candidate.get("decision")
            in {"GÜÇLÜ ADAY", "ADAY", "İZLE"}
        )

        if should_write:
            candidate_repo.upsert_by_symbol(candidate)
            updated += 1

        if result["excluded"]:
            excluded_count += 1
        if candidate.get("decision") == "GÜÇLÜ ADAY":
            strong += 1
        if result["errors"]:
            error_count += 1

        scan_repo.add_result(run_id, result)

        positive = candidate.get("positive_reasons") or []
        negative = candidate.get("negative_reasons") or []

        results.append({
            "Sembol": symbol,
            "Şirket": candidate.get("company_name"),
            "Profil": candidate.get("investment_profile"),
            "Güven": candidate.get("score_confidence"),
            "Veri Tamlığı": candidate.get("data_completeness"),
            "Kalite": candidate.get("quality_score"),
            "Büyüme": candidate.get("growth_score"),
            "Değerleme": candidate.get("valuation_score"),
            "Finansal Güç": candidate.get("financial_health_score"),
            "Risk": candidate.get("risk_score"),
            "Ceza": candidate.get("score_penalty"),
            "NABI Score": candidate.get("nabi_score"),
            "Karar": candidate.get("decision"),
            "En Güçlü Neden": (
                positive[0]["detail"] if positive else "—"
            ),
            "Ana Risk": (
                negative[0]["detail"] if negative else "—"
            ),
            "Kaydedildi": "Evet" if should_write else "Hayır",
        })

        progress.progress(index / len(selected_rows))
        fmp.pause(0.2)

    scan_repo.complete_run(
        run_id,
        len(selected_rows),
        updated,
        strong,
        error_count,
    )

    st.success(
        f"Scanner v4 tamamlandı. "
        f"{updated} aday kaydı güncellendi, "
        f"{excluded_count} özel menkul kıymet elendi."
    )
    st.dataframe(
        pd.DataFrame(results),
        use_container_width=True,
        hide_index=True,
    )
