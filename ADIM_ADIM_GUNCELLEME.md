# NABI Scout v9 — Company Report

## 1. Supabase

SQL Editor'da:

database/migration_v9_company_report.sql

dosyasını çalıştır.

Bu migration yeni kolon eklemez; yalnızca şema önbelleğini yeniler.

## 2. GitHub

Şu dosyaları yükle/değiştir:

- pages/2_Scout_Tarama.py
- pages/4_Company_Report.py
- database/migration_v9_company_report.sql

## 3. Eski sayfayı sil

Aşağıdaki eski detay sayfası varsa sil:

- pages/4_Aday_Detayi.py

Aynı işlevi yapan iki sayfa bırakılmamalıdır.

## 4. Commit

Release NABI Scout v9 Company Report

## 5. Reboot

Deploy tamamlandıktan sonra Streamlit uygulamasını reboot et.

## 6. Test

1. Scanner ekranında 5 şirket tara.
2. Tarama tablosunda artık uzun Tez Özeti sütunu bulunmamalı.
3. Tablo altında her şirket için “Raporu Aç” düğmesi görünmeli.
4. Düğmeye basıldığında Company Report açılmalı.
5. Company Report'ta:
   - karar özeti,
   - yatırım tezi,
   - güçlü ve zayıf noktalar,
   - olumlu ve olumsuz senaryo,
   - yeniden inceleme koşulları,
   - değerleme görüşü,
   - puanın kanıtları,
   - finansal göstergeler,
   - finansal terim açıklamaları
   tam metin görünmelidir.
