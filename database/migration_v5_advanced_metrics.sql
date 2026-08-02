alter table public.investment_candidates
    add column if not exists operating_income_estimated numeric,
    add column if not exists enterprise_value numeric,
    add column if not exists ev_to_ebit numeric,
    add column if not exists price_to_fcf numeric,
    add column if not exists peg_ratio_calculated numeric,
    add column if not exists owner_earnings numeric,
    add column if not exists memo_summary text,
    add column if not exists memo_strengths jsonb,
    add column if not exists memo_risks jsonb,
    add column if not exists memo_watch_items jsonb,
    add column if not exists memo_conclusion text,
    add column if not exists memo_version text;

create index if not exists idx_candidates_ev_ebit
on public.investment_candidates(ev_to_ebit);

create index if not exists idx_candidates_price_fcf
on public.investment_candidates(price_to_fcf);

notify pgrst, 'reload schema';
