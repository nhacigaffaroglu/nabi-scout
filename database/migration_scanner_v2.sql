alter table public.investment_candidates
    add column if not exists exchange_name text,
    add column if not exists average_volume numeric,
    add column if not exists shares_outstanding numeric,
    add column if not exists revenue_cagr_3y numeric,
    add column if not exists eps_cagr_3y numeric,
    add column if not exists roe numeric,
    add column if not exists roa numeric,
    add column if not exists net_debt_to_fcf numeric,
    add column if not exists interest_coverage numeric,
    add column if not exists price_to_sales numeric,
    add column if not exists price_to_book numeric,
    add column if not exists risk_score numeric,
    add column if not exists annual_periods_found integer,
    add column if not exists scanner_version text;

create index if not exists idx_candidates_scanner_score
on public.investment_candidates(scanner_version, nabi_score desc);

create index if not exists idx_candidates_completeness_score
on public.investment_candidates(data_completeness desc, nabi_score desc);

notify pgrst, 'reload schema';
