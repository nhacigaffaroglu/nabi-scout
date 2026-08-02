# NABI Scout v0.6 SEC Financial Engine

## 1. Supabase

SQL Editor'da `database/migration_v0_6.sql` çalıştır.

## 2. GitHub

Şu dosyaları yükle/değiştir:

- services/sec_financial_client.py
- services/free_universe_client.py
- services/universe_engine.py
- services/collector_engine.py
- pages/2_Scout_Tarama.py
- database/migration_v0_6.sql

Commit:
`Release NABI Scout v0.6 SEC Financial Engine`

## 3. Evreni yeniden oluştur

Eski evren warrant/unit sembolleri içerdiği için:
- Evren adı: ABD Temiz Hisse Evreni
- NASDAQ ve NYSE açık
- Hisseler açık
- ETF kapalı
- Maksimum sembol 100
- Evreni keşfet

Yeni evrende warrant, unit, right ve preferred share isimleri
ayıklanacaktır.

## 4. İlk finansal test

Scout Tarama:
- Dinamik: ABD Temiz Hisse Evreni
- Sembol sayısı: 5
- Eşik: 0
- Portföy uyumu: 55
- SEC e-postası: geçerli iletişim adresi

Beklenen:
- CIK sütunu dolu
- SEC Company Facts erişimi çalışıyor
- Veri tamlığı şirketlere göre yaklaşık %50–90 arasında
- Gelir büyümesi, marjlar, FCF ve ROIC alanlarından bir kısmı dolu
- FMP ücretli endpoint hataları artık ana finansal veriyi engellemiyor

Not:
XBRL etiketleri şirketler arasında farklılaşabilir. Eksik kalan etiketler
sonraki sürümde eşleme kütüphanesi genişletilerek artırılacaktır.
