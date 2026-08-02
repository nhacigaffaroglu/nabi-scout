alter table public.investment_candidates
    add column if not exists company_name text,
    add column if not exists country text;

create index if not exists idx_candidates_symbol
on public.investment_candidates(symbol);

create index if not exists idx_candidates_decision
on public.investment_candidates(decision);

create index if not exists idx_candidates_score
on public.investment_candidates(nabi_score desc);
