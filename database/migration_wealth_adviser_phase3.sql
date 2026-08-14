-- Wealth OS Adviser Phase 3 — investor profile + goals (additive, idempotent).
-- User preference data; NOT append-only financial accounting.
-- Apply manually in Supabase SQL Editor. Do NOT auto-run in production.

create table if not exists public.wealth_investor_profiles (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    profile_version integer not null default 1,
    investment_horizon text,
    risk_preference text,
    liquidity_need text,
    cash_preference text,
    concentration_preference text,
    income_need text,
    experience_level text,
    notes text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (user_id)
);

create index if not exists wealth_investor_profiles_user_idx
    on public.wealth_investor_profiles (user_id);

create table if not exists public.wealth_adviser_goals (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    portfolio_id uuid,
    goal_type text not null,
    title text not null,
    target_date date,
    target_amount numeric,
    currency text,
    priority integer not null default 1,
    notes text,
    active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists wealth_adviser_goals_user_active_idx
    on public.wealth_adviser_goals (user_id, active, priority);

create index if not exists wealth_adviser_goals_user_portfolio_idx
    on public.wealth_adviser_goals (user_id, portfolio_id);

alter table public.wealth_adviser_goals
    drop constraint if exists wealth_adviser_goals_user_portfolio_fkey;

alter table public.wealth_adviser_goals
    add constraint wealth_adviser_goals_user_portfolio_fkey
    foreign key (user_id, portfolio_id)
    references public.wealth_portfolios (user_id, id)
    on delete cascade;

-- RLS
alter table public.wealth_investor_profiles enable row level security;
alter table public.wealth_adviser_goals enable row level security;

drop policy if exists "wealth investor profiles select own" on public.wealth_investor_profiles;
create policy "wealth investor profiles select own"
on public.wealth_investor_profiles for select to authenticated
using (auth.uid() = user_id);

drop policy if exists "wealth investor profiles insert own" on public.wealth_investor_profiles;
create policy "wealth investor profiles insert own"
on public.wealth_investor_profiles for insert to authenticated
with check (auth.uid() = user_id);

drop policy if exists "wealth investor profiles update own" on public.wealth_investor_profiles;
create policy "wealth investor profiles update own"
on public.wealth_investor_profiles for update to authenticated
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "wealth investor profiles delete own" on public.wealth_investor_profiles;
create policy "wealth investor profiles delete own"
on public.wealth_investor_profiles for delete to authenticated
using (auth.uid() = user_id);

drop policy if exists "wealth adviser goals select own" on public.wealth_adviser_goals;
create policy "wealth adviser goals select own"
on public.wealth_adviser_goals for select to authenticated
using (auth.uid() = user_id);

drop policy if exists "wealth adviser goals insert own" on public.wealth_adviser_goals;
create policy "wealth adviser goals insert own"
on public.wealth_adviser_goals for insert to authenticated
with check (auth.uid() = user_id);

drop policy if exists "wealth adviser goals update own" on public.wealth_adviser_goals;
create policy "wealth adviser goals update own"
on public.wealth_adviser_goals for update to authenticated
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "wealth adviser goals delete own" on public.wealth_adviser_goals;
create policy "wealth adviser goals delete own"
on public.wealth_adviser_goals for delete to authenticated
using (auth.uid() = user_id);

notify pgrst, 'reload schema';
