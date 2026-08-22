-- Planning FX assumptions — user-defined USDTRY rates by year, not market data.
-- USDTRY = TRY required for 1 USD. Provenance is USER_DEFINED only.
-- Does not store live FX, forecasts, or contribution accounting.
-- Idempotent: safe to run multiple times in Supabase SQL Editor.
-- PRE-DEPLOY MIGRATION REQUIRED — do not apply automatically from application code.

create table if not exists public.wealth_planning_fx_assumptions (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    portfolio_id uuid not null,
    year integer not null,
    usdtry numeric not null,
    provenance text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint wealth_planning_fx_assumptions_user_portfolio_year_uidx
        unique (user_id, portfolio_id, year),
    constraint wealth_planning_fx_assumptions_year_check
        check (year >= 1900),
    constraint wealth_planning_fx_assumptions_usdtry_check
        check (usdtry > 0),
    constraint wealth_planning_fx_assumptions_provenance_check
        check (provenance in ('USER_DEFINED'))
);

alter table public.wealth_planning_fx_assumptions
    drop constraint if exists wealth_planning_fx_assumptions_user_portfolio_fkey;

alter table public.wealth_planning_fx_assumptions
    add constraint wealth_planning_fx_assumptions_user_portfolio_fkey
    foreign key (user_id, portfolio_id)
    references public.wealth_portfolios (user_id, id)
    on delete cascade;

create index if not exists wealth_planning_fx_assumptions_user_idx
    on public.wealth_planning_fx_assumptions (user_id);

alter table public.wealth_planning_fx_assumptions enable row level security;

drop policy if exists "planning fx assumptions select own"
    on public.wealth_planning_fx_assumptions;
create policy "planning fx assumptions select own"
on public.wealth_planning_fx_assumptions for select to authenticated
using (auth.uid() = user_id);

drop policy if exists "planning fx assumptions insert own"
    on public.wealth_planning_fx_assumptions;
create policy "planning fx assumptions insert own"
on public.wealth_planning_fx_assumptions for insert to authenticated
with check (auth.uid() = user_id);

drop policy if exists "planning fx assumptions update own"
    on public.wealth_planning_fx_assumptions;
create policy "planning fx assumptions update own"
on public.wealth_planning_fx_assumptions for update to authenticated
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "planning fx assumptions delete own"
    on public.wealth_planning_fx_assumptions;
create policy "planning fx assumptions delete own"
on public.wealth_planning_fx_assumptions for delete to authenticated
using (auth.uid() = user_id);

notify pgrst, 'reload schema';
