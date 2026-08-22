-- Contribution period reconciliation — evidence completeness, not accounting.
-- Marks that the user has entered/reconciled all external deposits and withdrawals
-- through reconciled_through. Does not create cash-flow rows.
-- Idempotent: safe to run multiple times in Supabase SQL Editor.
-- PRE-DEPLOY MIGRATION REQUIRED — do not apply automatically from application code.

create table if not exists public.wealth_contribution_reconciliations (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    portfolio_id uuid not null,
    reconciled_through date not null,
    provenance text not null,
    notes text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint wealth_contribution_reconciliations_user_portfolio_uidx
        unique (user_id, portfolio_id),
    constraint wealth_contribution_reconciliations_provenance_check
        check (provenance in ('USER_DEFINED'))
);

alter table public.wealth_contribution_reconciliations
    drop constraint if exists wealth_contribution_reconciliations_user_portfolio_fkey;

alter table public.wealth_contribution_reconciliations
    add constraint wealth_contribution_reconciliations_user_portfolio_fkey
    foreign key (user_id, portfolio_id)
    references public.wealth_portfolios (user_id, id)
    on delete cascade;

create index if not exists wealth_contribution_reconciliations_user_idx
    on public.wealth_contribution_reconciliations (user_id);

alter table public.wealth_contribution_reconciliations enable row level security;

drop policy if exists "contribution reconciliations select own"
    on public.wealth_contribution_reconciliations;
create policy "contribution reconciliations select own"
on public.wealth_contribution_reconciliations for select to authenticated
using (auth.uid() = user_id);

drop policy if exists "contribution reconciliations insert own"
    on public.wealth_contribution_reconciliations;
create policy "contribution reconciliations insert own"
on public.wealth_contribution_reconciliations for insert to authenticated
with check (auth.uid() = user_id);

drop policy if exists "contribution reconciliations update own"
    on public.wealth_contribution_reconciliations;
create policy "contribution reconciliations update own"
on public.wealth_contribution_reconciliations for update to authenticated
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

notify pgrst, 'reload schema';
