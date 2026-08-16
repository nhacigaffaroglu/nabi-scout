-- Wealth OS v1.3 — goal projection assumptions on existing adviser goals table.
-- User assumptions are NOT NABI forecasts.

alter table public.wealth_adviser_goals
    add column if not exists monthly_contribution_assumption numeric;

alter table public.wealth_adviser_goals
    add column if not exists expected_annual_return_assumption numeric;

alter table public.wealth_adviser_goals
    add column if not exists assumption_notes text;

notify pgrst, 'reload schema';
