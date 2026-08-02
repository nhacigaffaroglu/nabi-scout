alter table public.investment_candidates
    add column if not exists thesis_type text,
    add column if not exists thesis_summary text,
    add column if not exists thesis_strengths jsonb,
    add column if not exists thesis_concerns jsonb,
    add column if not exists thesis_bull_case text,
    add column if not exists thesis_bear_case text,
    add column if not exists thesis_revisit_conditions jsonb,
    add column if not exists thesis_revisit_trigger text,
    add column if not exists thesis_valuation_view text,
    add column if not exists thesis_evidence jsonb,
    add column if not exists thesis_version text;

create index if not exists idx_candidates_thesis_type
on public.investment_candidates(thesis_type, conviction_score desc);

notify pgrst, 'reload schema';
