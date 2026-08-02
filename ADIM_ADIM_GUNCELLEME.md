# NABI Scout — Universe Engine v2 CIK Sync Hotfix

## 1. Supabase

SQL Editor'da şunu çalıştır:

database/migration_universe_v2_hotfix.sql

## 2. GitHub

Şu dosyaları yükle veya değiştir:

- repositories/universe_repository.py
- services/free_universe_client.py
- pages/2_Evren_Motoru.py
- database/migration_universe_v2_hotfix.sql

Commit:

Hotfix Universe Engine v2 CIK Sync

Deploy bittikten sonra Streamlit uygulamasını reboot et.

## 3. Yeni evren oluştur

Evren Motoru v2:

- Evren adı: ABD Temiz Hisse Evreni v2
- NASDAQ: Açık
- NYSE: Açık
- Hisseler: Açık
- ETF: Kapalı
- Maksimum sembol: 100
- SEC iletişim e-postası: geçerli adres

Evreni oluştur ve CIK eşleştir düğmesine bas.

Beklenen:

- CIK kapsamı yaklaşık %100'e yakın olmalı.
- CIK sütununda sayısal değerler görünmeli.
- Acquisition Corp, warrant, unit ve preferred share sembolleri büyük ölçüde ayıklanmalı.

## 4. Scanner v2 testi

Scout Scanner v2:

- Tarama evreni: Dinamik: ABD Temiz Hisse Evreni v2
- Başlangıç sırası: 1
- Sembol sayısı: 5
- Aday eşiği: 0
- Veri eksik kayıtları kaydet: Kapalı

Beklenen:

- CIK artık None olmamalı.
- SEC Company Facts çağrısı çalışmalı.
- Veri tamlığı belirgin şekilde yükselmeli.
- Kalite, büyüme ve finansal güç skorları 50 sabitinde kalmamalı.
