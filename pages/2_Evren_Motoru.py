import pandas as pd
import streamlit as st

from repositories.universe_repository import UniverseRepository
from services.fmp_client import FMPClient
from services.supabase_client import get_supabase_client
from services.ui import configure_page, render_sidebar
from services.universe_engine import UniverseEngine

configure_page("Evren Motoru | NABI Scout", "🌍")
render_sidebar()

st.title("🌍 Scout Universe Engine")
st.caption(
    "Yatırım evrenini FMP şirket tarayıcısı veya sembol listesinden "
    "otomatik oluşturur."
)

client = get_supabase_client()
repo = UniverseRepository(client)

with st.form("universe_form"):
    universe_name = st.text_input(
        "Evren adı",
        value="ABD Kaliteli Büyük Şirketler",
    )

    c1, c2 = st.columns(2)
    nasdaq = c1.checkbox("NASDAQ", value=True)
    nyse = c1.checkbox("NYSE", value=True)
    amex = c1.checkbox("AMEX", value=False)
    country = c2.text_input("Ülke kodu", value="US")

    c3, c4, c5 = st.columns(3)
    min_market_cap_bn = c3.number_input(
        "Minimum piyasa değeri (milyar USD)",
        min_value=0.0,
        value=2.0,
    )
    min_price = c4.number_input(
        "Minimum fiyat",
        min_value=0.0,
        value=5.0,
    )
    min_volume = c5.number_input(
        "Minimum günlük hacim",
        min_value=0,
        value=500000,
        step=100000,
    )

    limit = st.slider(
        "Maksimum sembol",
        min_value=10,
        max_value=500,
        value=100,
        step=10,
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

    if not exchanges:
        st.error("En az bir borsa seçin.")
        st.stop()

    fmp = FMPClient.from_streamlit_secrets()
    engine = UniverseEngine(fmp)

    filters = {
        "exchanges": exchanges,
        "country": country,
        "min_market_cap": min_market_cap_bn * 1_000_000_000,
        "min_price": min_price,
        "min_volume": min_volume,
        "limit": limit,
    }

    run_id = repo.create_run(universe_name, filters)

    with st.spinner("Yatırım evreni keşfediliyor..."):
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
