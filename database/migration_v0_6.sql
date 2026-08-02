alter table public.investment_candidates
    add column if not exists cik bigint,
    add column if not exists financial_period_end date;

create index if not exists idx_candidates_cik
on public.investment_candidates(cik);

notify pgrst, 'reload schema';
