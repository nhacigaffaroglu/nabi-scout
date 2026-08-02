import streamlit as st

from services.supabase_client import get_supabase_client
from services.ui import configure_page, sidebar_navigation, show_connection_status

configure_page("NABI Scout", "🔭")
sidebar_navigation()

st.title("🔭 NABI Scout")
st.caption("Nabi için doğru yatırım araçlarını araştıran bağımsız yatırım araştırma platformu.")

show_connection_status()

st.subheader("Başlangıç sürümü")
st.info(
    "Bu ilk sürümde uygulama ve veritabanı bağlantısını kuruyoruz. "
    "Canlı fiyat, bilanço, haber ve yapay zekâ araştırması sonraki aşamalarda eklenecek."
)

col1, col2, col3 = st.columns(3)
col1.metric("Aday havuzu", "Hazırlanıyor")
col2.metric("NABI Score", "v0.1")
col3.metric("Katılım filtresi", "Aktif")

st.subheader("İlk çalışma akışı")
st.markdown(
    """
1. Aday Havuzu'na yatırım aracı ekle.
2. Kalite, büyüme, değerleme ve risk puanlarını gir.
3. NABI Score sonucunu incele.
4. Güçlü adayları İzleme Listesi'ne al.
5. Sonraki sürümlerde verileri otomatik kaynaklardan güncelle.
"""
)

with st.expander("Supabase bağlantı testi"):
    try:
        supabase = get_supabase_client()
        response = supabase.table("investment_candidates").select("id", count="exact").limit(1).execute()
        count = getattr(response, "count", None)
        st.success(f"Bağlantı başarılı. Aday tablosu erişilebilir. Kayıt sayısı: {count or 0}")
    except Exception as exc:
        st.error(f"Bağlantı testi başarısız: {exc}")
