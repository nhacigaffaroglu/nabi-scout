# NABI Scout v6 — Research Detail & NABI Akademi

## 1. Supabase

SQL Editor'da:

database/migration_v6_academy.sql

dosyasını çalıştır.

## 2. GitHub

Şu dosyaları yükle/değiştir:

- services/financial_glossary.py
- services/academy_renderer.py
- pages/8_NABI_Akademi.py
- pages/4_Aday_Detayi.py
- database/migration_v6_academy.sql

Commit:

Release NABI Scout v6 Research Detail and Academy

Deploy tamamlandıktan sonra Streamlit uygulamasını reboot et.

## 3. Test

- Sol menüde NABI Akademi sayfası görünmeli.
- ROIC, CAGR, FCF, borç ve değerleme kavramları aranabilmeli.
- Aday Detayı 2.0 ekranında her metrik için:
  - sade anlatım,
  - neden önemli,
  - iyi değer aralığı,
  - bu şirketteki yorum,
  - günlük hayattan örnek
  gösterilmeli.
- Finansal verisi eksik olan alanlarda sistem değer uydurmamalı;
  “yeterli veri bulunamadı” demeli.
