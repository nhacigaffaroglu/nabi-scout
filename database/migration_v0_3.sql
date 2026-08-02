-- NABI Scout v0.3 Candidate Intelligence migration

alter table public.investment_candidates
    add column if not exists fair_value numeric,
    add column if not exists discount_to_fair_value numeric,
    add column if not exists pe_ratio numeric,
    add column if not exists peg_ratio numeric,
    add column if not exists revenue_growth numeric,
    add column if not exists eps_growth numeric,
    add column if not exists operating_margin numeric,
    add column if not exists roic numeric,
    add column if not exists net_debt_ebitda numeric,
    add column if not exists free_cash_flow_margin numeric,
    add column if not exists dividend_yield numeric,
    add column if not exists financial_health_score numeric,
    add column if not exists investment_thesis text,
    add column if not exists growth_catalysts text;

create index if not exists idx_candidates_fair_value
on public.investment_candidates(fair_value);

create index if not exists idx_candidates_discount
on public.investment_candidates(discount_to_fair_value desc);

create index if not exists idx_candidates_roic
on public.investment_candidates(roic desc);

notify pgrst, 'reload schema';
