alter table public.investment_candidates
    add column if not exists security_type text,
    add column if not exists exclude_reason text,
    add column if not exists fcf_cagr_3y numeric,
    add column if not exists share_change_3y numeric,
    add column if not exists payout_ratio numeric,
    add column if not exists capital_allocation_score numeric;

create index if not exists idx_candidates_scanner_v3
on public.investment_candidates(
    scanner_version,
    data_completeness desc,
    nabi_score desc
);

notify pgrst, 'reload schema';
