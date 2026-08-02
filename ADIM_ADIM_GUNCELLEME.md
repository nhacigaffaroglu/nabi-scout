# NABI Scout v5 — Advanced Metrics & Investment Memo

1. Supabase SQL Editor'da `database/migration_v5_advanced_metrics.sql` çalıştır.
2. GitHub'a şu dosyaları yükle:
   - services/advanced_metrics.py
   - services/investment_memo.py
   - services/scanner_v5_engine.py
   - pages/2_Scout_Tarama.py
   - pages/4_Aday_Detayi.py
   - database/migration_v5_advanced_metrics.sql
3. Commit: `Release NABI Scout v5 Advanced Metrics and Memo`
4. Streamlit uygulamasını reboot et.

İlk test:
- ABD Temiz Hisse Evreni v2
- Başlangıç 1
- 5 sembol
- Eşik 0
- Minimum veri tamlığı 50
- Portföy uyumu 55

Beklenen:
- EV/EBIT, PEG ve Fiyat/FCF sütunları görünür.
- Eksik veri varsa alan None kalır; değer uydurulmaz.
- Aday Detayı ekranında NABI Investment Memo görünür.
