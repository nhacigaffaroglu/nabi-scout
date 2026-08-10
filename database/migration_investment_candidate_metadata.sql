-- Candidate metadata added by foreign issuer, freshness, and FMP reliability sprints.
-- Idempotent and backward compatible.

alter table public.investment_candidates
    add column if not exists financial_currency text,
    add column if not exists financial_taxonomy text,
    add column if not exists pe_source text,
    add column if not exists freshness_status text,
    add column if not exists freshness_label text,
    add column if not exists period_age_days integer,
    add column if not exists freshness_score numeric;

notify pgrst, 'reload schema';
