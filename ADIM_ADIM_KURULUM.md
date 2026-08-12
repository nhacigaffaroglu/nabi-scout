# NABI Scout Web v0.1 — Adım Adım Kurulum

Bu kurulum bilgisayarınıza Python kurmadan yapılabilir.

## Aşama 1 — GitHub

1. https://github.com adresine gidin ve hesap açın/giriş yapın.
2. Sağ üstte `+` → `New repository`.
3. Repository name: `nabi-scout`
4. Visibility: `Private`
5. `Create repository`.
6. Depo ekranında `uploading an existing file` bağlantısına veya `Add file → Upload files` seçeneğine tıklayın.
7. Bu paketin içindeki dosya ve klasörleri ZIP'ten çıkarıp yükleyin.
8. `Commit changes` düğmesine basın.

## Aşama 2 — Supabase

1. https://supabase.com adresine gidin.
2. GitHub ile giriş yapabilirsiniz.
3. `New project` seçin.
4. Project name: `nabi-scout`
5. Güçlü bir database password belirleyin ve güvenli yerde saklayın.
6. Türkiye'ye yakın bir region seçin.
7. Proje kurulunca sol menüden `SQL Editor`.
8. `New query`.
9. `database/setup.sql` dosyasının tamamını kopyalayıp yapıştırın.
10. `Run` düğmesine basın.
11. Sol menü `Table Editor` altında dört tabloyu kontrol edin:
    - investment_candidates
    - deep_analyses
    - news_items
    - watchlist

## Aşama 3 — Supabase anahtarları

1. Supabase projesinde `Connect` veya `Project Settings → API Keys`.
2. Şunları kopyalayın:
    - Project URL
    - Publishable key (`sb_publishable_...`)
3. Secret/service_role anahtarını kullanmayın ve paylaşmayın.

## Aşama 4 — Streamlit Community Cloud

1. https://share.streamlit.io adresine gidin.
2. GitHub ile giriş yapın.
3. `Create app` / `New app`.
4. Repository: `nabi-scout`
5. Branch: `main`
6. Main file path: `app.py`
7. App URL için uygun bir isim seçin.
8. Deploy etmeden önce `Advanced settings` → `Secrets`.
9. Şunu yapıştırın:

```toml
[supabase]
url = "SUPABASE_PROJECT_URL"
publishable_key = "SUPABASE_PUBLISHABLE_KEY"
```

10. Değerleri Supabase'ten kopyaladıklarınızla değiştirin.
11. `Save` ve ardından `Deploy`.

## Aşama 5 — İlk test

1. Uygulama açıldığında ana sayfada Supabase bağlantı testini açın.
2. `Bağlantı başarılı` mesajını görün.
3. Sol menüden `Aday Havuzu`.
4. Test için `SPUS` ekleyin.
5. Dashboard'da adayın göründüğünü kontrol edin.

## Güvenlik uyarısı

İlk starter sürüm, kolay kurulum testi için geçici `anon` erişim politikaları içerir.
Uygulamayı internette herkese açık tutulmamalıdır.

## Aşama 6 — Supabase Auth ve RLS sıkılaştırma

1. Supabase Dashboard → **Authentication → Users** → **Add user**.
2. Uygulamaya giriş yapacak e-posta ve güçlü bir parola oluşturun.
3. SQL Editor'da `database/migration_auth_rls_hardening.sql` dosyasını çalıştırın.
4. Bu migration geçici `anon` erişim politikalarını kaldırır; yalnızca oturum açmış
   kullanıcılar (`authenticated`) veri okuyup yazabilir.
5. Streamlit uygulamasını yeniden başlatın ve giriş ekranından test kullanıcısıyla oturum açın.
6. Çıkış yapıldığında araştırma sayfalarının veri göstermediğini doğrulayın.

**GitHub Actions / headless tarama:** `SUPABASE_KEY` ortam değişkeni artık **service_role**
anahtarı olmalıdır. Publishable/anon anahtar RLS'i bypass etmez.

**Streamlit Secrets** (değişmedi):

```toml
[supabase]
url = "SUPABASE_PROJECT_URL"
publishable_key = "SUPABASE_PUBLISHABLE_KEY"
```

Parolalar veya service_role anahtarı Streamlit Secrets'a eklenmez; yalnızca Supabase Auth
üzerinden giriş yapılır.
