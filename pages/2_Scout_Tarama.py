import pandas as pd
import streamlit as st

from config.scan_universe import PARTICIPATION_DEFAULTS, SCAN_UNIVERSES
from repositories.candidate_repository import CandidateRepository
from repositories.scan_repository import ScanRepository
from repositories.universe_repository import UniverseRepository
from services.fmp_client import FMPClient
from services.scanner_v8_engine import ScannerV8Engine
from services.sec_financial_client import SECFinancialClient
from services.supabase_client import get_supabase_client
from services.ui import configure_page, render_sidebar

configure_page("Scout Scanner v8 | NABI Scout", "🧠")
render_sidebar()
st.title("🧠 Scout Scanner v8")
st.caption("Decision Engine sonuçlarını gerekçeli yatırım tezine dönüştürür.")

client = get_supabase_client()
candidate_repo = CandidateRepository(client)
scan_repo = ScanRepository(client)
universe_repo = UniverseRepository(client)

dynamic_names = universe_repo.get_universe_names()
options = [f"Sabit: {name}" for name in SCAN_UNIVERSES] + [f"Dinamik: {name}" for name in dynamic_names]
selected = st.selectbox("Tarama evreni", options)

if selected.startswith("Sabit: "):
    universe_name = selected.replace("Sabit: ", "", 1)
    all_rows = [{"symbol": s, "cik": None, "company_name": s, "exchange": None, "is_etf": False}
                for s in SCAN_UNIVERSES[universe_name]]
else:
    universe_name = selected.replace("Dinamik: ", "", 1)
    all_rows = universe_repo.get_symbols(universe_name, limit=2000)

if not all_rows:
    st.warning("Seçilen evrende sembol bulunmuyor.")
    st.stop()

c1, c2 = st.columns(2)
start_index = c1.number_input("Başlangıç sırası", min_value=1, max_value=len(all_rows), value=1)
batch_size = c2.slider("Taranacak sembol sayısı", 1, min(25, len(all_rows)), min(5, len(all_rows)))
minimum_completeness = st.slider("Minimum veri tamlığı", 0, 100, 65)
minimum_conviction = st.slider("Minimum Conviction Score", 0, 100, 60)
portfolio_fit = st.slider("Varsayılan portföy uyumu", 0, 100, 55)
sec_email = st.text_input("SEC iletişim e-postası", value="nabi-scout@example.com")

start = int(start_index) - 1
selected_rows = all_rows[start:start + batch_size]
st.write("**Bu çalışmadaki semboller:**", ", ".join(row["symbol"] for row in selected_rows))

if st.button("Sprint 8 yatırım tezi taramasını başlat", type="primary"):
    engine = ScannerV8Engine(
        FMPClient.from_streamlit_secrets(),
        SECFinancialClient(contact_email=sec_email),
    )
    run_id = scan_repo.create_run(
        f"{universe_name} [{start + 1}-{start + len(selected_rows)}]",
        len(selected_rows),
    )

    progress = st.progress(0)
    output = []
    updated = strong = errors = excluded = 0

    for index, row in enumerate(selected_rows, 1):
        symbol = row["symbol"]
        p_status, p_score = PARTICIPATION_DEFAULTS.get(symbol, ("Kontrol Et", 60))
        result = engine.analyze(
            symbol=symbol,
            cik=row.get("cik"),
            company_name=row.get("company_name"),
            exchange=row.get("exchange"),
            is_etf=row.get("is_etf", False),
            participation_status=p_status,
            participation_score=p_score,
            portfolio_fit=portfolio_fit,
        )
        candidate = result["candidate"]

        should_write = (
            not result["excluded"]
            and candidate.get("data_completeness", 0) >= minimum_completeness
            and candidate.get("conviction_score", 0) >= minimum_conviction
            and candidate.get("decision_label") not in {
                "ŞİMDİLİK UZAK DUR",
                "VERİ EKSİK — ÖN ELEME",
            }
        )

        if should_write:
            candidate_repo.upsert_by_symbol(candidate)
            updated += 1
        if result["excluded"]:
            excluded += 1
        if candidate.get("decision_label") == "YÜKSEK ÖNCELİKLİ ARAŞTIRMA ADAYI":
            strong += 1
        if result.get("errors"):
            errors += 1

        scan_repo.add_result(run_id, result)
        output.append({
            "Sembol": symbol,
            "Şirket": candidate.get("company_name"),
            "Tez Tipi": candidate.get("thesis_type"),
            "NABI Score": candidate.get("nabi_score"),
            "Confidence": candidate.get("research_confidence"),
            "Conviction": candidate.get("conviction_score"),
            "Opportunity": candidate.get("opportunity_score"),
            "Karar": candidate.get("decision_label"),
            "Tez Özeti": candidate.get("thesis_summary"),
            "Kaydedildi": "Evet" if should_write else "Hayır",
        })
        progress.progress(index / len(selected_rows))

    scan_repo.complete_run(run_id, len(selected_rows), updated, strong, errors)
    st.success(
        f"Sprint 8.2 tamamlandı. {updated} araştırma adayı güncellendi, "
        f"{excluded} özel menkul kıymet elendi."
    )
    st.dataframe(pd.DataFrame(output), use_container_width=True, hide_index=True)
