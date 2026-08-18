-- Portfolio allocation target policy — planning preference, not accounting.
-- One active policy per user-owned portfolio. Derived drift and routing results are never stored.
-- Idempotent: safe to run multiple times in Supabase SQL Editor.
-- PRE-DEPLOY MIGRATION REQUIRED — do not apply automatically from application code.

create table if not exists public.portfolio_allocation_policies (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    portfolio_id uuid not null,
    dimension text not null,
    targets jsonb not null,
    tolerance_pct numeric(6, 4) not null,
    provenance text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint portfolio_allocation_policies_user_portfolio_uidx unique (user_id, portfolio_id),
    constraint portfolio_allocation_policies_dimension_check
        check (dimension in ('ASSET_CLASS', 'MARKET')),
    constraint portfolio_allocation_policies_provenance_check
        check (provenance in ('USER_DEFINED', 'PRODUCT_POLICY')),
    constraint portfolio_allocation_policies_targets_array_check
        check (jsonb_typeof(targets) = 'array')
);

alter table public.portfolio_allocation_policies
    drop constraint if exists portfolio_allocation_policies_user_portfolio_fkey;

alter table public.portfolio_allocation_policies
    add constraint portfolio_allocation_policies_user_portfolio_fkey
    foreign key (user_id, portfolio_id)
    references public.wealth_portfolios (user_id, id)
    on delete cascade;

create index if not exists portfolio_allocation_policies_user_idx
    on public.portfolio_allocation_policies (user_id);

alter table public.portfolio_allocation_policies enable row level security;

drop policy if exists "portfolio allocation policies select own"
    on public.portfolio_allocation_policies;
create policy "portfolio allocation policies select own"
on public.portfolio_allocation_policies for select to authenticated
using (auth.uid() = user_id);

drop policy if exists "portfolio allocation policies insert own"
    on public.portfolio_allocation_policies;
create policy "portfolio allocation policies insert own"
on public.portfolio_allocation_policies for insert to authenticated
with check (auth.uid() = user_id);

drop policy if exists "portfolio allocation policies update own"
    on public.portfolio_allocation_policies;
create policy "portfolio allocation policies update own"
on public.portfolio_allocation_policies for update to authenticated
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "portfolio allocation policies delete own"
    on public.portfolio_allocation_policies;
create policy "portfolio allocation policies delete own"
on public.portfolio_allocation_policies for delete to authenticated
using (auth.uid() = user_id);

notify pgrst, 'reload schema';
