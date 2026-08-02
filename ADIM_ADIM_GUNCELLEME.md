# NABI Scout — Scout Scanner v3

## 1. Supabase

SQL Editor'da:

database/migration_scanner_v3.sql

dosyasını çalıştır.

## 2. GitHub

Şu dosyaları yükle/değiştir:

- services/security_classifier.py
- services/sec_financial_client.py
- services/scanner_v3_scoring.py
- services/scanner_v3_engine.py
- pages/2_Scout_Tarama.py
- database/migration_scanner_v3.sql

Commit mesajı:

Release NABI Scout Scanner v3 Intelligence

Deploy sonrası Streamlit uygulamasını reboot et.

## 3. İlk test

Scout Scanner v3:

- Tarama evreni: Dinamik ABD Temiz Hisse Evreni v2
- Başlangıç sırası: 1
- Sembol sayısı: 5
- Aday havuzuna yazma eşiği: 0
- Minimum veri tamlığı: 50
- Portföy uyumu: 55

Beklenen:

- Acquisition Corp / SPAC benzeri kayıtlar ELENDİ görünmeli.
- AAL, AAOI gibi normal şirketlerde skorlar hesaplanmalı.
- FCF CAGR, hisse adedi değişimi ve sermaye tahsisi skoru üretilmeli.
- Veri tamlığı ve karar eşikleri sağlanmıyorsa aday havuzuna yazılmamalı.

## Not

Scanner v3 bir araştırma önceliklendirme motorudur.
Ürettiği skorlar yatırım tavsiyesi değildir.
Katılım uygunluğu ayrı ve doğrulanabilir bir modül olarak geliştirilecektir.
