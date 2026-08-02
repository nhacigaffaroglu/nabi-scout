# NABI Scout v0.5.1 Ücretsiz Universe Hotfix

## 1. Supabase

SQL Editor'da `database/migration_v0_5_1.sql` çalıştır.

## 2. GitHub

Şu dosyaları yükle/değiştir:

- services/free_universe_client.py
- services/universe_engine.py
- services/fmp_client.py
- pages/2_Evren_Motoru.py
- database/migration_v0_5_1.sql

Commit:
`Hotfix v0.5.1 Free Universe and API masking`

## 3. İlk test

Evren Motoru:
- Evren adı: ABD Hisse Evreni
- NASDAQ: açık
- NYSE: açık
- Hisseler: açık
- ETF: kapalı
- Maksimum sembol: 100
- SEC e-postası: kendi e-posta adresiniz veya uygulama için geçerli iletişim adresi

Evreni keşfet.

Beklenen:
- Kaynak: Nasdaq Trader + SEC
- Sembol sayısı: 100
- FMP 402 hatası görünmemeli
- FMP API key hiçbir hata mesajında görünmemeli

Sonra Scout Tarama ekranından dinamik evreni seçip yalnızca 5 sembol tara.
