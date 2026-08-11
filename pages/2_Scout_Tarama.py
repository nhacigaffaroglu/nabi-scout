import pandas as pd
import streamlit as st

from config.scan_universe import PARTICIPATION_DEFAULTS, SCAN_UNIVERSES
from repositories.candidate_repository import CandidateRepository
from repositories.scan_repository import ScanRepository
from repositories.universe_repository import UniverseRepository
from repositories.watchlist_repository import WatchlistRepository
from services.fmp_client import FMPClient
from services.free_universe_client import FreeUniverseClient
from services.scan_runner_service import run_scan
from services.scan_universe_service import build_fixed_universe_rows
from services.scanner_v8_engine import ScannerV8Engine
from services.sec_financial_client import SECFinancialClient
from services.supabase_client import get_supabase_client
from services.ui import configure_page, render_sidebar

configure_page("Scout Scanner v9 | NABI Scout", "🧭")
render_sidebar()

st.title("🧭 Scout Scanner v9")
st.caption(
    "Tarama tablosu yalnızca özet gösterir. "
    "Ayrıntılı analiz Company Report ekranında açılır."
)


@st.cache_data(ttl=3600, show_spinner=False)
def load_sec_company_lookup(contact_email: str) -> dict:
    if not contact_email.strip():
        return {}

    rows = FreeUniverseClient(
        contact_email=contact_email.strip(),
    ).get_sec_companies()

    return {
        str(row.get("symbol") or "").strip().upper(): row
        for row in rows
        if row.get("symbol")
    }


client = get_supabase_client()
candidate_repo = CandidateRepository(client)
scan_repo = ScanRepository(client)
universe_repo = UniverseRepository(client)
watchlist_repo = WatchlistRepository(client)

sec_email = st.text_input(
    "SEC iletişim e-postası",
    value="nabi-scout@example.com",
    help=(
        "SEC veri taleplerinde User-Agent içinde kullanılır. "
        "Gerçek ve ulaşılabilir bir e-posta adresi kullanılması önerilir."
    ),
)

dynamic_names = universe_repo.get_universe_names()
options = (
    [f"Sabit: {name}" for name in SCAN_UNIVERSES]
    + [f"Dinamik: {name}" for name in dynamic_names]
)
selected = st.selectbox("Tarama evreni", options)

if selected.startswith("Sabit: "):
    universe_name = selected.replace("Sabit: ", "", 1)

    sec_lookup = {}
    if sec_email.strip():
        try:
            sec_lookup = load_sec_company_lookup(sec_email.strip())
        except Exception as exc:
            st.warning(
                "SEC sembol metadata listesi alınamadı. "
                "Sabit evren temel sembol bilgileriyle devam edecek. "
                f"Hata: {exc}"
            )

    all_rows = build_fixed_universe_rows(universe_name, sec_lookup)
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
)
batch_size = c2.slider(
    "Taranacak sembol sayısı",
    1,
    min(25, len(all_rows)),
    min(3, len(all_rows)),
)
minimum_completeness = st.slider(
    "Minimum veri tamlığı",
    0,
    100,
    65,
)
minimum_conviction = st.slider(
    "Minimum Araştırma Güveni",
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

start = int(start_index) - 1
selected_rows = all_rows[start:start + batch_size]
st.write(
    "**Bu çalışmadaki semboller:**",
    ", ".join(row["symbol"] for row in selected_rows),
)

with st.expander("Tarama metadata kontrolü", expanded=False):
    metadata_rows = []
    for row in selected_rows:
        metadata_rows.append({
            "Sembol": row.get("symbol"),
            "Şirket": row.get("company_name"),
            "CIK": row.get("cik"),
            "Borsa": row.get("exchange"),
            "ETF": "Evet" if row.get("is_etf") else "Hayır",
        })

    st.dataframe(
        pd.DataFrame(metadata_rows),
        use_container_width=True,
        hide_index=True,
    )

if "latest_scan_candidates" not in st.session_state:
    st.session_state["latest_scan_candidates"] = []

if "latest_scan_changes" not in st.session_state:
    st.session_state["latest_scan_changes"] = []

if st.button("Sprint 9 taramasını başlat", type="primary"):
    fmp_client = FMPClient.from_streamlit_secrets()
    engine = ScannerV8Engine(
        fmp_client,
        SECFinancialClient(contact_email=sec_email.strip()),
    )
    batch_universe_name = (
        f"{universe_name} [{start + 1}-{start + len(selected_rows)}]"
    )

    progress = st.progress(0)

    def _progress_callback(current: int, total: int) -> None:
        progress.progress(current / total)

    scan_result = run_scan(
        symbols=selected_rows,
        universe_name=batch_universe_name,
        source="manual",
        scan_repo=scan_repo,
        candidate_repo=candidate_repo,
        fmp_client=fmp_client,
        sec_client=SECFinancialClient(contact_email=sec_email.strip()),
        engine=engine,
        minimum_completeness=minimum_completeness,
        minimum_conviction=minimum_conviction,
        portfolio_fit=portfolio_fit,
        participation_defaults=PARTICIPATION_DEFAULTS,
        progress_callback=_progress_callback,
    )

    st.session_state["latest_scan_candidates"] = scan_result.candidates
    st.session_state["latest_scan_changes"] = scan_result.meaningful_changes
    st.session_state["latest_scan_symbols_without_previous"] = (
        scan_result.symbols_without_previous
    )

    if scan_result.status == "FAILED":
        st.error("Tarama başarısız oldu — hiçbir sembol işlenemedi.")
    else:
        st.success(
            f"Sprint 9 taraması tamamlandı. "
            f"{scan_result.updated} araştırma adayı güncellendi, "
            f"{scan_result.excluded} özel menkul kıymet elendi."
        )

if st.session_state["latest_scan_candidates"]:
    candidates = st.session_state["latest_scan_candidates"]
    meaningful_changes = st.session_state.get("latest_scan_changes") or []
    symbols_without_previous = int(
        st.session_state.get("latest_scan_symbols_without_previous") or 0
    )
    watched_ids = watchlist_repo.watched_candidate_ids()

    st.subheader("🔄 Bu taramada ne değişti?")
    if not meaningful_changes:
        if symbols_without_previous == len(candidates):
            st.info(
                "Bu semboller için karşılaştırılabilir önceki tarama "
                "bulunamadı."
            )
        else:
            st.info(
                "Önceki taramaya göre anlamlı değişiklik bulunmadı."
            )
            if symbols_without_previous:
                st.caption(
                    f"{symbols_without_previous} sembol için önceki "
                    "karşılaştırılabilir tarama yok."
                )
    else:
        if symbols_without_previous:
            st.caption(
                f"{symbols_without_previous} sembol için önceki "
                "karşılaştırılabilir tarama yok."
            )
        for item in meaningful_changes:
            change = item["change"]
            st.markdown(
                f"**{item['symbol']}** — "
                f"Değişim skoru {change.get('change_score', 0)}"
            )
            for event in change.get("changes") or []:
                st.markdown(f"• {event.get('message')}")
            st.markdown("")

    table_rows = []
    for candidate in candidates:
        table_rows.append({
            "Sembol": candidate.get("symbol"),
            "Şirket": candidate.get("company_name"),
            "Yatırım Tezi": candidate.get("thesis_type"),
            "NABI Skoru": candidate.get("nabi_score"),
            "Veri Güveni": candidate.get("research_confidence"),
            "Araştırma Güveni": candidate.get("conviction_score"),
            "Fırsat Potansiyeli": candidate.get("opportunity_score"),
            "Karar": candidate.get("decision_label"),
        })

    st.subheader("Tarama sonuçları")
    st.dataframe(
        pd.DataFrame(table_rows),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Sembol": st.column_config.TextColumn(
                "Sembol",
                width="small",
            ),
            "Şirket": st.column_config.TextColumn(
                "Şirket",
                width="medium",
            ),
            "Yatırım Tezi": st.column_config.TextColumn(
                "Yatırım Tezi",
                width="medium",
            ),
            "NABI Skoru": st.column_config.NumberColumn(
                "NABI Skoru",
                format="%.1f",
                width="small",
            ),
            "Veri Güveni": st.column_config.NumberColumn(
                "Veri Güveni",
                format="%.1f",
                width="small",
                help=(
                    "Analizin dayandığı finansal verilerin "
                    "kapsam ve güvenilirlik düzeyi."
                ),
            ),
            "Araştırma Güveni": st.column_config.NumberColumn(
                "Araştırma Güveni",
                format="%.1f",
                width="small",
                help=(
                    "Şirket hakkındaki araştırma sonucunun ne kadar "
                    "güçlü ve tutarlı olduğuna ilişkin birleşik puan."
                ),
            ),
            "Fırsat Potansiyeli": st.column_config.NumberColumn(
                "Fırsat Potansiyeli",
                format="%.1f",
                width="small",
                help=(
                    "Kalite, büyüme ve değerleme birlikte "
                    "değerlendirildiğinde araştırma fırsatı."
                ),
            ),
            "Karar": st.column_config.TextColumn(
                "Karar",
                width="medium",
            ),
        },
    )

    st.subheader("Şirket raporunu aç")
    st.caption(
        "Yatırım tezi ve açıklamalar artık tabloda değil, "
        "şirket raporunda tam metin gösterilir."
    )

    for index, candidate in enumerate(candidates):
        symbol = candidate.get("symbol") or "—"
        company = candidate.get("company_name") or symbol
        db_candidate = candidate_repo.get_by_symbol(symbol)
        candidate_id = db_candidate.get("id") if db_candidate else None
        is_watched = (
            str(candidate_id) in watched_ids
            if candidate_id
            else False
        )

        left, middle, right = st.columns([1.1, 4.5, 1.4])

        with left:
            st.markdown(f"### {symbol}")

        with middle:
            st.write(f"**{company}**")
            st.caption(
                f"{candidate.get('thesis_type') or 'Tez yok'} · "
                f"NABI {candidate.get('nabi_score') or 0:.1f} · "
                f"{candidate.get('decision_label') or 'Karar yok'}"
            )

        with right:
            if st.button(
                "📄 Raporu Aç",
                key=f"open_report_{symbol}_{index}",
                use_container_width=True,
            ):
                st.session_state["company_report_candidate"] = candidate
                st.query_params["symbol"] = symbol
                st.switch_page("pages/4_Company_Report.py")

            if not candidate_id:
                st.caption(
                    "Bu şirket aday havuzuna kaydedilmediği için "
                    "henüz izleme listesine eklenemiyor."
                )
            elif is_watched:
                if st.button(
                    "✓ İzleniyor",
                    key=f"watch_remove_{symbol}_{index}",
                    use_container_width=True,
                ):
                    watchlist_repo.deactivate(str(candidate_id))
                    st.rerun()
            elif st.button(
                "⭐ İzleme listesine ekle",
                key=f"watch_add_{symbol}_{index}",
                use_container_width=True,
            ):
                watchlist_repo.add_candidate(str(candidate_id))
                st.rerun()

        st.divider()
else:
    st.info(
        "Şirket raporlarını açmak için önce bir tarama çalıştırın."
    )
