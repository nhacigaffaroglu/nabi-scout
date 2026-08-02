# NABI Scout v7 — Decision, Explain & Confidence Engine

## 1. Supabase

SQL Editor'da:

database/migration_v7_decision.sql

dosyasını çalıştır.

## 2. GitHub

Şu dosyaları yükle/değiştir:

- services/confidence_engine.py
- services/explain_engine.py
- services/decision_engine.py
- services/research_intelligence_engine.py
- services/scanner_v7_engine.py
- pages/2_Scout_Tarama.py
- pages/4_Aday_Detayi.py
- database/migration_v7_decision.sql

Önceki sürümden şu dosyalar kalmalıdır:

- services/scanner_v5_engine.py
- services/scanner_v4_engine.py
- services/advanced_metrics.py
- services/investment_memo.py
- services/academy_renderer.py
- services/financial_glossary.py

Commit:

Release NABI Scout v7 Decision Explain Confidence

Deploy sonrası Streamlit uygulamasını reboot et.

## 3. İlk test

- Evren: ABD Temiz Hisse Evreni v2
- Başlangıç: 1
- Sembol: 5
- Minimum veri tamlığı: 50
- Minimum Conviction: 0
- Portföy uyumu: 55

Beklenen:

- Confidence, Conviction, Opportunity ve Yatırım Notu sütunları görünmeli.
- Aday Detayı ekranı Decision Center olarak açılmalı.
- Kararı destekleyen nedenler ve başlıca riskler gösterilmeli.
- "Neden şimdi?", uygun yatırımcı ve uygun olmayan yatırımcı alanları görünmeli.
- Eski adaylarda bu alanlar boş olabilir; Scanner v7 ile yeniden taranmalıdır.
