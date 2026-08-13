-- Wealth OS Phase 3 — append-only portfolio snapshots (additive, idempotent).
-- Snapshots capture PortfolioIntelligenceView summaries for timeline/performance.
-- No changes to existing Wealth or NABI tables.

create table if not exists public.wealth_portfolio_snapshots (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    portfolio_id uuid not null references public.wealth_portfolios(id) on delete cascade,
    captured_at timestamptz not null default now(),
    base_currency text not null,
    priced_market_value numeric not null default 0,
    total_cost_basis numeric not null default 0,
    unrealized_pl numeric not null default 0,
    cash_value numeric not null default 0,
    invested_value numeric not null default 0,
    liabilities_total numeric,
    net_wealth_partial numeric,
    priced_position_coverage_pct numeric not null default 0,
    unpriced_position_count integer not null default 0,
    mixed_currency_warning boolean not null default false,
    valuation_payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists wealth_portfolio_snapshots_user_portfolio_captured_idx
    on public.wealth_portfolio_snapshots (user_id, portfolio_id, captured_at desc);

-- Composite ownership FK: snapshot cannot reference another user's portfolio.
alter table public.wealth_portfolio_snapshots
    drop constraint if exists wealth_portfolio_snapshots_portfolio_id_fkey;
alter table public.wealth_portfolio_snapshots
    drop constraint if exists wealth_portfolio_snapshots_portfolio_owner_fkey;
alter table public.wealth_portfolio_snapshots
    add constraint wealth_portfolio_snapshots_portfolio_owner_fkey
    foreign key (user_id, portfolio_id)
    references public.wealth_portfolios (user_id, id)
    on delete cascade;

alter table public.wealth_portfolio_snapshots enable row level security;

-- Append-only: select + insert only.
drop policy if exists "wealth portfolio snapshots select own" on public.wealth_portfolio_snapshots;
create policy "wealth portfolio snapshots select own"
on public.wealth_portfolio_snapshots for select to authenticated
using (auth.uid() = user_id);

drop policy if exists "wealth portfolio snapshots insert own" on public.wealth_portfolio_snapshots;
create policy "wealth portfolio snapshots insert own"
on public.wealth_portfolio_snapshots for insert to authenticated
with check (auth.uid() = user_id);

notify pgrst, 'reload schema';
