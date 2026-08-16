# NABI Scout 2.0

Bağımsız yatırım işletim sistemi (Streamlit + Supabase). Keşfet → Araştır → Karar → Portföy → Monitör → Öğren.

**Başlatma:** `streamlit run app.py`

**Normal render maliyeti (Dashboard / Portföy Zekâsı / Monitör):** LLM=0, FMP=0, SEC=0, uzak FX=0, uzak fon=0

**Günlük otomasyon (UTC / İstanbul UTC+3):**

| Job | UTC | İstanbul |
|-----|-----|----------|
| Daily Scan | 03:00 | 06:00 |
| FX Refresh | 04:00 | 07:00 |
| Universe Expansion | 05:00 | 08:00 |
| Fund Holdings | 05:30 | 08:30 |
| Wealth Snapshot | 06:30 | 09:30 |
| Monitor Refresh | 07:30 | 10:30 |

Doğrulama: `python3 scripts/verify_nabi_v2_live.py`

---

# NABI Scout v1 (legacy notes)

Bağımsız yatırım araştırma ve portföy analizi platformu (Streamlit + Supabase + FMP).

## Modüller

| Modül | Açıklama |
|-------|----------|
| **Dashboard** | Günlük özet, manuel sembol analizi |
| **Scout Scanner** | Evren taraması, aday havuzu |
| **Company Report** | Şirket istihbaratı, yatırım tezi, katılım |
| **Wealth OS** | Ledger, pozisyonlar, performans, benchmark, diagnostik |
| **Danışman** | Deterministik grounding + doğrulanmış LLM yorumu |
| **Research Monitor** | Tarama değişiklikleri |

## Mimari (v1)

```
FMP / Provider
    ↓
Company Intelligence → Investment Thesis
    ↓
NABI + Participation + Wealth Exposure + Profile/Goals
    ↓
Unified Research Context → Adviser LLM (v3) → Kullanıcı
```

Deterministik katmanlar LLM tarafından **override edilemez**.

## Gerekli secrets

`/.streamlit/secrets.toml` örneği:

```toml
[supabase]
url = "..."
publishable_key = "..."

[fmp]
api_key = "..."

[wealth_adviser_llm]
enabled = false
api_key = ""
model = "gpt-4o-mini"
```

## Geliştirme oturumu (dev auto-login)

Yalnızca yerel geliştirme için:

```toml
[dev_auth]
enabled = true
email = "..."
password = "..."
```

**Production'da dev auto-login kapalı olmalıdır.**

## Migration checklist (manuel uygulama)

Supabase SQL Editor'de sırayla:

1. `database/migration_wealth_core_phase1.sql`
2. `database/migration_wealth_timeline_phase3.sql`
3. `database/migration_wealth_adviser_phase3.sql` — profil/hedef tabloları
4. `database/migration_investment_thesis_snapshots.sql` — tez geçmişi
5. Diğer katılım/tarama migration'ları (bkz. `database/`)

Uygulanmış migration'ları takip edin; uygulanmamış tablolar için UI graceful degrade eder.

## FMP bütçesi

- Company Report cold load: **≤15** provider çağrısı (4 emsal × ratios_ttm)
- Warm rerun (aynı oturum): **0** ek çağrı (bundle cache)
- Danışman: sayfa render'ında **0** LLM; gönderim başına **≤1** LLM + isteğe bağlı sembol başına 1 CI yüklemesi

## OpenAI / Danışman

- `WEALTH_ADVISER_LLM_ENABLED=true` ve API key gerekir
- Testlerde LLM varsayılan kapalı (mock)

## Zamanlanmış tarama

GitHub Actions `scripts/run_daily_scan.py` — `SUPABASE_SERVICE_ROLE_KEY` gerekir (UI yolunda kullanılmaz).

## Yerel çalıştırma

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Bilinen sınırlamalar

- Production refresh-token kalıcılığı çözülmedi; normal auth modunda oturum yenileme sınırlı olabilir
- Tez geçmişi migration uygulanmadan kaydedilemez
- Danışman otomatik işlem yapmaz; kesin al/sat miktarı üretmez
- Kısmi fiyatlı portföy değerlemesi toplam net servet değildir

## Kurulum ayrıntıları

Bkz. [ADIM_ADIM_KURULUM.md](ADIM_ADIM_KURULUM.md)
