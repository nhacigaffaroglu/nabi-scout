-- Wealth OS v1.3 — user investment decision journal (additive, idempotent).
-- User-authored entries; NOT append-only accounting.

create table if not exists public.wealth_decision_journal (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    portfolio_id uuid,
    account_id uuid,
    asset_id uuid,
    symbol text not null,
    action_context text not null,
    thesis text,
    key_evidence text,
    key_risks text,
    invalidation_conditions text,
    expected_horizon text,
    tags text[] not null default '{}',
    notes text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint wealth_decision_journal_action_context_check
        check (
            action_context in (
                'considering',
                'added',
                'increased',
                'reduced',
                'exited',
                'reviewed'
            )
        )
);

create index if not exists wealth_decision_journal_user_symbol_idx
    on public.wealth_decision_journal (user_id, symbol, created_at desc);

create index if not exists wealth_decision_journal_user_portfolio_idx
    on public.wealth_decision_journal (user_id, portfolio_id, created_at desc);

alter table public.wealth_decision_journal
    drop constraint if exists wealth_decision_journal_user_portfolio_fkey;

alter table public.wealth_decision_journal
    add constraint wealth_decision_journal_user_portfolio_fkey
    foreign key (user_id, portfolio_id)
    references public.wealth_portfolios (user_id, id)
    on delete set null;

alter table public.wealth_decision_journal
    drop constraint if exists wealth_decision_journal_user_account_fkey;

alter table public.wealth_decision_journal
    add constraint wealth_decision_journal_user_account_fkey
    foreign key (user_id, account_id)
    references public.wealth_accounts (user_id, id)
    on delete set null;

alter table public.wealth_decision_journal enable row level security;

drop policy if exists "wealth decision journal select own" on public.wealth_decision_journal;
create policy "wealth decision journal select own"
on public.wealth_decision_journal for select to authenticated
using (auth.uid() = user_id);

drop policy if exists "wealth decision journal insert own" on public.wealth_decision_journal;
create policy "wealth decision journal insert own"
on public.wealth_decision_journal for insert to authenticated
with check (auth.uid() = user_id);

drop policy if exists "wealth decision journal update own" on public.wealth_decision_journal;
create policy "wealth decision journal update own"
on public.wealth_decision_journal for update to authenticated
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "wealth decision journal delete own" on public.wealth_decision_journal;
create policy "wealth decision journal delete own"
on public.wealth_decision_journal for delete to authenticated
using (auth.uid() = user_id);

notify pgrst, 'reload schema';
