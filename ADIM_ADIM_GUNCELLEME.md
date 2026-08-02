# NABI Scout v8 — Investment Thesis Engine

1. Supabase SQL Editor'da `database/migration_v8_thesis.sql` çalıştır.
2. GitHub'a yükle/değiştir:
   - services/investment_thesis_engine.py
   - services/scanner_v8_engine.py
   - pages/2_Scout_Tarama.py
   - pages/4_Aday_Detayi.py
   - database/migration_v8_thesis.sql
3. Commit: `Release NABI Scout v8 Investment Thesis Engine`
4. Streamlit uygulamasını reboot et.

İlk test:
- Evren: ABD Temiz Hisse Evreni v2
- Başlangıç: 1
- Sembol: 5
- Minimum veri tamlığı: 50
- Minimum Conviction: 0
- Portföy uyumu: 55

Beklenen:
- Tarama ekranında Tez Tipi ve Tez Özeti görünür.
- Detay ekranında yatırım tezi, güçlü/zayıf noktalar, olumlu/olumsuz senaryo,
  yeniden inceleme koşulları ve değerleme görüşü görünür.
