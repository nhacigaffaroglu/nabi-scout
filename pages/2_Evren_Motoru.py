import pandas as pd
import streamlit as st

from repositories.universe_repository import UniverseRepository
from services.free_universe_client import FreeUniverseClient
from services.supabase_client import get_supabase_client
from services.ui import configure_page, render_sidebar
from services.universe_engine import UniverseEngine

configure_page("Evren Motoru | NABI Scout", "🌍")
render_sidebar()

st.title("🌍 Scout Universe Engine")
st.caption(
    "ABD yatırım evrenini ücretsiz SEC ve Nasdaq Trader "
    "kaynaklarından oluşturur."
)

client = get_supabase_client()
repo = UniverseRepository(client)

with st.form("universe_form"):
    universe_name = st.text_input(
        "Evren adı",
        value="ABD Hisse Evreni",
    )

    c1, c2 = st.columns(2)
    nasdaq = c1.checkbox("NASDAQ", value=True)
    nyse = c1.checkbox("NYSE", value=True)
    amex = c1.checkbox("AMEX", value=False)
    arca = c1.checkbox("NYSE Arca", value=False)

    include_common = c2.checkbox(
        "Hisseleri dahil et",
        value=True,
    )
    include_etfs = c2.checkbox(
        "ETF'leri dahil et",
        value=False,
    )
    name_contains = c2.text_input(
        "İsim/sembol filtresi",
        placeholder="Boş bırakılabilir",
    )

    limit = st.slider(
        "Maksimum sembol",
        min_value=10,
        max_value=1000,
        value=100,
        step=10,
    )

    contact_email = st.text_input(
        "SEC iletişim e-postası",
        value="nabi-scout@example.com",
        help=(
            "SEC isteklerinde tanımlayıcı User-Agent için kullanılır. "
            "API anahtarı değildir."
        ),
    )

    submitted = st.form_submit_button(
        "Evreni keşfet",
        type="primary",
    )

if submitted:
    exchanges = []
    if nasdaq:
        exchanges.append("NASDAQ")
    if nyse:
        exchanges.append("NYSE")
    if amex:
        exchanges.append("AMEX")
    if arca:
        exchanges.append("ARCA")

    if not exchanges:
        st.error("En az bir borsa seçin.")
        st.stop()

    if not include_common and not include_etfs:
        st.error("Hisse veya ETF türlerinden en az birini seçin.")
        st.stop()

    source_client = FreeUniverseClient(
        contact_email=contact_email,
    )
    engine = UniverseEngine(source_client)

    filters = {
        "exchanges": exchanges,
        "include_etfs": include_etfs,
        "include_common_stocks": include_common,
        "limit": limit,
        "name_contains": name_contains,
    }

    run_id = repo.create_run(universe_name, filters)

    with st.spinner("Ücretsiz yatırım evreni oluşturuluyor..."):
        result = engine.discover(**filters)

    rows = result["rows"]
    repo.save_symbols(run_id, universe_name, rows)
    repo.complete_run(
        run_id,
        result["source"],
        len(rows),
        result["errors"],
    )

    st.success(
        f"{len(rows)} sembol bulundu. "
        f"Kaynak: {result['source']}"
    )

    if result["errors"]:
        st.warning(" | ".join(result["errors"]))

    st.dataframe(
        pd.DataFrame(rows),
        use_container_width=True,
        hide_index=True,
    )

st.subheader("Son evren çalışmaları")
st.dataframe(
    pd.DataFrame(repo.get_recent_runs()),
    use_container_width=True,
    hide_index=True,
)
