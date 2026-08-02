# NABI Scout — Sprint 10.1 Embedded Academy

## 1. Supabase

SQL Editor'da:

database/migration_sprint_10_1_academy.sql

dosyasını çalıştır.

## 2. GitHub

Şu dosyaları yükle/değiştir:

- services/academy_content.py
- services/academy_ui.py
- pages/4_Company_Report.py
- database/migration_sprint_10_1_academy.sql

## 3. Eski servis

Eğer repoda `services/academy_renderer.py` varsa kalabilir; ancak Company Report artık
`academy_ui.py` kullanır.

## 4. Commit

Release Sprint 10.1 Embedded NABI Academy

## 5. Reboot

Deploy tamamlandıktan sonra Streamlit uygulamasını reboot et.

## 6. Test

Company Report ekranında:

- NABI Academy bölümü görünmeli.
- Kalite, Büyüme, Borç ve Değerleme sekmeleri açılmalı.
- Her metrik kartında:
  - değer,
  - sade değerlendirme etiketi,
  - şirkete özel yorum,
  - Basit anlat,
  - Neden önemli,
  - Bu beni neden ilgilendiriyor,
  - genel yorum aralıkları,
  - dikkat notu
  görünmeli.
- Eksik metriklerde “Veri yok” yazmalı; sistem değer uydurmamalı.
