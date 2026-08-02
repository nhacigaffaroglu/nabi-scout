import pandas as pd
import streamlit as st

from config.scan_universe import PARTICIPATION_DEFAULTS, SCAN_UNIVERSES
from repositories.candidate_repository import CandidateRepository
from repositories.scan_repository import ScanRepository
from repositories.universe_repository import UniverseRepository
from services.fmp_client import FMPClient
from services.scanner_v5_engine import ScannerV5Engine
from services.sec_financial_client import SECFinancialClient
from services.supabase_client import get_supabase_client
from services.ui import configure_page, render_sidebar

configure_page("Scout Scanner v5 | NABI Scout", "🧾")
render_sidebar()
st.title("🧾 Scout Scanner v5")
st.caption("Gelişmiş değerleme metrikleri ve gerekçeli NABI Investment Memo üretir.")

client = get_supabase_client()
candidate_repo = CandidateRepository(client)
scan_repo = ScanRepository(client)
universe_repo = UniverseRepository(client)

dynamic_names = universe_repo.get_universe_names()
options = [f"Sabit: {n}" for n in SCAN_UNIVERSES] + [f"Dinamik: {n}" for n in dynamic_names]
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
threshold = st.slider("Aday havuzuna yazma eşiği", 0, 100, 60)
minimum_completeness = st.slider("Minimum veri tamlığı", 0, 100, 65)
portfolio_fit = st.slider("Varsayılan portföy uyumu", 0, 100, 55)
sec_email = st.text_input("SEC iletişim e-postası", value="nabi-scout@example.com")

start = int(start_index) - 1
selected_rows = all_rows[start:start + batch_size]
st.write("**Bu çalışmadaki semboller:**", ", ".join(r["symbol"] for r in selected_rows))

if st.button("Scanner v5 taramasını başlat", type="primary"):
    engine = ScannerV5Engine(
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
            and candidate.get("nabi_score", 0) >= threshold
            and candidate.get("decision") in {"GÜÇLÜ ADAY", "ADAY", "İZLE"}
        )
        if should_write:
            candidate_repo.upsert_by_symbol(candidate)
            updated += 1
        if result["excluded"]:
            excluded += 1
        if candidate.get("decision") == "GÜÇLÜ ADAY":
            strong += 1
        if result.get("errors"):
            errors += 1

        scan_repo.add_result(run_id, result)
        output.append({
            "Sembol": symbol,
            "Şirket": candidate.get("company_name"),
            "Profil": candidate.get("investment_profile"),
            "Veri Tamlığı": candidate.get("data_completeness"),
            "ROIC": candidate.get("roic"),
            "Gelir CAGR 3Y": candidate.get("revenue_cagr_3y"),
            "EPS CAGR 3Y": candidate.get("eps_cagr_3y"),
            "FCF CAGR 3Y": candidate.get("fcf_cagr_3y"),
            "EV/EBIT": candidate.get("ev_to_ebit"),
            "PEG": candidate.get("peg_ratio_calculated"),
            "Fiyat/FCF": candidate.get("price_to_fcf"),
            "NABI Score": candidate.get("nabi_score"),
            "Karar": candidate.get("decision"),
            "Memo": candidate.get("memo_conclusion"),
            "Kaydedildi": "Evet" if should_write else "Hayır",
        })
        progress.progress(index / len(selected_rows))

    scan_repo.complete_run(run_id, len(selected_rows), updated, strong, errors)
    st.success(f"Scanner v5 tamamlandı. {updated} aday güncellendi, {excluded} özel menkul kıymet elendi.")
    st.dataframe(pd.DataFrame(output), use_container_width=True, hide_index=True)
