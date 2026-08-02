# NABI Scout — Scout Scanner v2

## 1. Supabase

SQL Editor'da `database/migration_scanner_v2.sql` çalıştır.

## 2. GitHub

Şu dosyaları yükle/değiştir:

- services/scanner_v2_scoring.py
- services/sec_financial_client.py
- services/scanner_v2_engine.py
- pages/2_Scout_Tarama.py
- database/migration_scanner_v2.sql

Commit:
`Release NABI Scout Scout Scanner v2`

Deploy sonrasında uygulamayı reboot et.

## 3. İlk test

Önce büyük ve bilinen şirketleri içeren sıraya ulaşmak için
Başlangıç sırası alanını kullanabilirsin. Alternatif olarak Evren
Motoru'nda isim/sembol filtresiyle örneğin Microsoft veya AAPL için
küçük bir test evreni oluşturabilirsin.

Önerilen ilk test:
- Tarama evreni: Dinamik ABD Temiz Hisse Evreni
- Başlangıç sırası: 1
- Sembol sayısı: 5
- Aday eşiği: 0
- Veri eksikleri kaydet: kapalı
- Portföy uyumu: 55

Beklenen:
- CIK dolu olmalı.
- Veri tamlığı şirketlere göre yaklaşık %50–95 aralığında olmalı.
- Kalite, Büyüme, Değerleme, Finansal Güç ve Risk skorları birbirinden farklılaşmalı.
- Veri tamlığı %50'nin altındaki kayıtlar aday havuzuna yazılmamalı.
- Tarama geçmişi scan_runs ve scan_results tablolarına yazılmalı.

## Bilinen sınırlar

- Bankalar ve sigorta şirketleri klasik sanayi şirketlerinden farklı finansal
  etiketler kullanır; ilk sürümde skorları daha düşük veri tamlığı gösterebilir.
- SEC Company Facts yalnızca SEC raporlaması bulunan şirketlerde çalışır.
- Katılım uygunluğu bu sürümde otomatik ve kesin olarak belirlenmez.
- NABI Score yatırım tavsiyesi değil, araştırma önceliklendirme skorudur.
