-- NABI Akademi statik içerik kullandığı için yeni tablo gerektirmez.
-- Sürüm bilgisini mevcut aday kayıtlarında tutabilmek için alan eklenir.

alter table public.investment_candidates
    add column if not exists explanation_version text;

notify pgrst, 'reload schema';
