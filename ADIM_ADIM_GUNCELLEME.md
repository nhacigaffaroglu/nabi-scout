# NABI Scout v0.4 Modüler Güncelleme

1. Supabase SQL Editor'da `database/migration_v0_4.sql` çalıştır.
2. GitHub'a paket içindeki yeni/değişen dosyaları yükle.
3. `requirements.txt` dosyasını değiştir.
4. Commit: `Release NABI Scout v0.4 Scout Collector`
5. Streamlit deploy tamamlanınca yeni `Scout Tarama` sayfasını aç.

İlk test:
- Tarama evreni: Katılım ETF 3
- Aday eşiği: 0
- Portföy uyumu: 55
- Taramayı başlat

Ücretsiz planda bazı FMP endpointleri kapalıysa sonuçta erişim sorunu
görünebilir. Tarama tamamlanıyor ve en az bazı alanlar geliyorsa collector
altyapısı çalışıyor demektir.
