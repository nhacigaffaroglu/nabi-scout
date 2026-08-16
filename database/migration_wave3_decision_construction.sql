-- Wave 3 — decision learning + portfolio construction (additive, idempotent).
-- PRE-DEPLOY MIGRATION REQUIRED — apply manually before live verification.

-- Decision journal evolution (optional structured fields; historical rows remain valid).
alter table public.wealth_decision_journal
    add column if not exists decision_type text;

alter table public.wealth_decision_journal
    add column if not exists key_assumptions text;

alter table public.wealth_decision_journal
    add column if not exists expected_catalysts text;

alter table public.wealth_decision_journal
    add column if not exists primary_risks text;

alter table public.wealth_decision_journal
    add column if not exists confidence_at_decision text;

alter table public.wealth_decision_journal
    add column if not exists research_reference text;

alter table public.wealth_decision_journal
    add column if not exists portfolio_context_snapshot jsonb;

alter table public.wealth_decision_journal
    drop constraint if exists wealth_decision_journal_decision_type_check;

alter table public.wealth_decision_journal
    add constraint wealth_decision_journal_decision_type_check
    check (
        decision_type is null
        or decision_type in (
            'initiated_position',
            'increased_position',
            'reduced_position',
            'closed_position',
            'held',
            'transferred',
            'reviewed_without_trade'
        )
    );

-- User-defined reference structure limits (diagnostics only; not investment advice).
create table if not exists public.portfolio_reference_limits (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    portfolio_id uuid not null,
    max_single_position_pct numeric(6, 2),
    max_top3_concentration_pct numeric(6, 2),
    max_sector_pct numeric(6, 2),
    max_institution_pct numeric(6, 2),
    max_kontrol_et_pct numeric(6, 2),
    min_cash_pct numeric(6, 2),
    min_research_covered_pct numeric(6, 2),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint portfolio_reference_limits_user_portfolio_uidx unique (user_id, portfolio_id)
);

alter table public.portfolio_reference_limits
    drop constraint if exists portfolio_reference_limits_user_portfolio_fkey;

alter table public.portfolio_reference_limits
    add constraint portfolio_reference_limits_user_portfolio_fkey
    foreign key (user_id, portfolio_id)
    references public.wealth_portfolios (user_id, id)
    on delete cascade;

create index if not exists portfolio_reference_limits_user_idx
    on public.portfolio_reference_limits (user_id);

alter table public.portfolio_reference_limits enable row level security;

drop policy if exists "portfolio reference limits select own"
    on public.portfolio_reference_limits;
create policy "portfolio reference limits select own"
on public.portfolio_reference_limits for select to authenticated
using (auth.uid() = user_id);

drop policy if exists "portfolio reference limits insert own"
    on public.portfolio_reference_limits;
create policy "portfolio reference limits insert own"
on public.portfolio_reference_limits for insert to authenticated
with check (auth.uid() = user_id);

drop policy if exists "portfolio reference limits update own"
    on public.portfolio_reference_limits;
create policy "portfolio reference limits update own"
on public.portfolio_reference_limits for update to authenticated
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "portfolio reference limits delete own"
    on public.portfolio_reference_limits;
create policy "portfolio reference limits delete own"
on public.portfolio_reference_limits for delete to authenticated
using (auth.uid() = user_id);

notify pgrst, 'reload schema';
