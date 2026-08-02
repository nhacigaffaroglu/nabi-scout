# NABI Scout — NABI Score v4 Intelligence

## 1. Supabase

SQL Editor'da:

database/migration_score_v4.sql

dosyasını çalıştır.

## 2. GitHub

Şu dosyaları yükle/değiştir:

- services/nabi_score_v4.py
- services/scanner_v4_engine.py
- pages/2_Scout_Tarama.py
- pages/4_Aday_Detayi.py
- database/migration_score_v4.sql

Önceki sürümden şu dosyalar da repoda bulunmalıdır:

- services/security_classifier.py
- services/sec_financial_client.py
- services/fmp_client.py

Commit mesajı:

Release NABI Score v4 Intelligence

Deploy sonrası Streamlit uygulamasını reboot et.

## 3. İlk test

Scanner v4:

- Tarama evreni: ABD Temiz Hisse Evreni v2
- Başlangıç sırası: 1
- Sembol sayısı: 5
- Aday eşiği: 0
- Minimum veri tamlığı: 50
- Portföy uyumu: 55

Kontrol edilecekler:

- Profil alanı dolmalı.
- Güven seviyesi dolmalı.
- En Güçlü Neden ve Ana Risk alanları görünmeli.
- Borç, negatif FCF veya sulandırma varsa puan cezası oluşmalı.
- Acquisition Corp türleri tarama öncesinde elenmeli.
- Aday Detayı sayfasında güçlü yönler ve riskler gösterilmeli.

## Not

NABI Score v4 araştırma önceliklendirme sistemidir.
Tek başına alım veya satım kararı değildir.
Katılım uygunluğu doğrulanmadan kayıt yatırım önerisi sayılmaz.
