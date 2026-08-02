alter table public.investment_candidates
    add column if not exists research_confidence numeric,
    add column if not exists research_confidence_level text,
    add column if not exists research_confidence_explanation text,
    add column if not exists research_confidence_reasons jsonb,
    add column if not exists score_factors jsonb,
    add column if not exists score_positive_factors jsonb,
    add column if not exists score_negative_factors jsonb,
    add column if not exists score_neutral_factors jsonb,
    add column if not exists quality_explanation jsonb,
    add column if not exists growth_explanation jsonb,
    add column if not exists valuation_explanation jsonb,
    add column if not exists decision_label text,
    add column if not exists decision_action text,
    add column if not exists investment_grade text,
    add column if not exists conviction_score numeric,
    add column if not exists opportunity_score numeric,
    add column if not exists decision_verdict text,
    add column if not exists decision_top_reasons jsonb,
    add column if not exists decision_top_risks jsonb,
    add column if not exists decision_suitable_for jsonb,
    add column if not exists decision_not_suitable_for jsonb,
    add column if not exists decision_why_now jsonb,
    add column if not exists decision_version text,
    add column if not exists research_engine_version text;

create index if not exists idx_candidates_conviction
on public.investment_candidates(conviction_score desc);

create index if not exists idx_candidates_opportunity
on public.investment_candidates(opportunity_score desc);

create index if not exists idx_candidates_grade
on public.investment_candidates(investment_grade, nabi_score desc);

notify pgrst, 'reload schema';
