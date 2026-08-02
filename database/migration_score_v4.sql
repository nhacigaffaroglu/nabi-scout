alter table public.investment_candidates
    add column if not exists profitability_score numeric,
    add column if not exists capital_efficiency_score numeric,
    add column if not exists shareholder_score numeric,
    add column if not exists investment_profile text,
    add column if not exists score_confidence text,
    add column if not exists score_penalty numeric,
    add column if not exists hard_flags jsonb,
    add column if not exists positive_reasons jsonb,
    add column if not exists negative_reasons jsonb,
    add column if not exists score_reasons jsonb;

create index if not exists idx_candidates_profile_score
on public.investment_candidates(
    investment_profile,
    nabi_score desc
);

create index if not exists idx_candidates_confidence_score
on public.investment_candidates(
    score_confidence,
    nabi_score desc
);

notify pgrst, 'reload schema';
