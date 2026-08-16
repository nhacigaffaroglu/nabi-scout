-- Wave 4 — Full Wealth OS: FX rates, fund holdings, automation, snapshot idempotency.
-- PRE-DEPLOY MIGRATION REQUIRED — apply manually before live verification.

-- Persisted FX rates (global market data; no user portfolio exposure).
create table if not exists public.fx_rates (
    id uuid primary key default gen_random_uuid(),
    base_currency text not null,
    quote_currency text not null,
    rate numeric(18, 8) not null,
    rate_date date not null,
    source text not null default 'manual',
    retrieved_at timestamptz not null default now(),
    data_quality text not null default 'good',
    constraint fx_rates_pair_date_uidx unique (base_currency, quote_currency, rate_date)
);

create index if not exists fx_rates_pair_date_idx
    on public.fx_rates (base_currency, quote_currency, rate_date desc);

alter table public.fx_rates enable row level security;

drop policy if exists "fx rates read authenticated" on public.fx_rates;
create policy "fx rates read authenticated"
on public.fx_rates for select to authenticated
using (true);

drop policy if exists "fx rates read service" on public.fx_rates;
create policy "fx rates read service"
on public.fx_rates for select to service_role
using (true);

drop policy if exists "fx rates insert service" on public.fx_rates;
create policy "fx rates insert service"
on public.fx_rates for insert to service_role
with check (true);

drop policy if exists "fx rates update service" on public.fx_rates;
create policy "fx rates update service"
on public.fx_rates for update to service_role
using (true)
with check (true);

-- Fund holdings snapshots (global reference; keyed by fund symbol, not user).
create table if not exists public.fund_holdings_snapshots (
    id uuid primary key default gen_random_uuid(),
    fund_symbol text not null,
    fund_type text not null default 'etf',
    as_of date not null,
    source text not null,
    coverage_pct numeric(6, 2),
    underlying_count integer,
    created_at timestamptz not null default now(),
    constraint fund_holdings_snapshots_symbol_asof_uidx unique (fund_symbol, as_of, source)
);

create index if not exists fund_holdings_snapshots_symbol_idx
    on public.fund_holdings_snapshots (fund_symbol, as_of desc);

create table if not exists public.fund_holdings (
    id uuid primary key default gen_random_uuid(),
    snapshot_id uuid not null references public.fund_holdings_snapshots(id) on delete cascade,
    underlying_symbol text,
    underlying_name text,
    weight_pct numeric(8, 4),
    asset_type text,
    participation_status text,
    research_status text
);

create index if not exists fund_holdings_snapshot_idx
    on public.fund_holdings (snapshot_id);

alter table public.fund_holdings_snapshots enable row level security;
alter table public.fund_holdings enable row level security;

drop policy if exists "fund holdings snapshots read authenticated"
    on public.fund_holdings_snapshots;
create policy "fund holdings snapshots read authenticated"
on public.fund_holdings_snapshots for select to authenticated
using (true);

drop policy if exists "fund holdings read authenticated" on public.fund_holdings;
create policy "fund holdings read authenticated"
on public.fund_holdings for select to authenticated
using (true);

drop policy if exists "fund holdings snapshots write service"
    on public.fund_holdings_snapshots;
create policy "fund holdings snapshots write service"
on public.fund_holdings_snapshots for all to service_role
using (true)
with check (true);

drop policy if exists "fund holdings write service" on public.fund_holdings;
create policy "fund holdings write service"
on public.fund_holdings for all to service_role
using (true)
with check (true);

-- Automation run ledger (scheduler idempotency).
create table if not exists public.wealth_automation_runs (
    id uuid primary key default gen_random_uuid(),
    job_name text not null,
    run_date date not null,
    trigger_type text not null default 'scheduled',
    status text not null default 'RUNNING',
    started_at timestamptz not null default now(),
    finished_at timestamptz,
    records_updated integer not null default 0,
    provider_calls integer not null default 0,
    report_payload jsonb not null default '{}'::jsonb,
    constraint wealth_automation_runs_job_date_uidx unique (job_name, run_date, trigger_type)
);

create index if not exists wealth_automation_runs_job_date_idx
    on public.wealth_automation_runs (job_name, run_date desc);

alter table public.wealth_automation_runs enable row level security;

drop policy if exists "wealth automation runs service all"
    on public.wealth_automation_runs;
create policy "wealth automation runs service all"
on public.wealth_automation_runs for all to service_role
using (true)
with check (true);

-- Snapshot idempotency: one row per portfolio per UTC day.
-- Safe on databases with historical same-day duplicates (pre-DB constraint era).

alter table public.wealth_portfolio_snapshots
    add column if not exists snapshot_date date;

-- A. Backfill snapshot_date from captured_at (UTC calendar day).
update public.wealth_portfolio_snapshots
set snapshot_date = (captured_at at time zone 'UTC')::date
where snapshot_date is null;

alter table public.wealth_portfolio_snapshots
    alter column snapshot_date set default (timezone('UTC', now()))::date;

-- B. Detect duplicate groups (for operator visibility during migration runs).
do $$
declare
    v_groups integer := 0;
    v_extra_rows integer := 0;
begin
    select count(*), coalesce(sum(cnt - 1), 0)
    into v_groups, v_extra_rows
    from (
        select count(*) as cnt
        from public.wealth_portfolio_snapshots
        where snapshot_date is not null
        group by portfolio_id, snapshot_date
        having count(*) > 1
    ) dupes;

    raise notice 'wave4 snapshot dedupe: % duplicate (portfolio_id, snapshot_date) groups; % redundant rows pending removal',
        v_groups, v_extra_rows;
end $$;

-- C. Preserve nullable optional fields on canonical row when duplicates had values.
with ranked as (
    select
        id,
        portfolio_id,
        snapshot_date,
        liabilities_total,
        net_wealth_partial,
        row_number() over (
            partition by portfolio_id, snapshot_date
            order by captured_at desc, created_at desc, id desc
        ) as rn
    from public.wealth_portfolio_snapshots
    where snapshot_date is not null
),
canonical as (
    select id as keep_id, portfolio_id, snapshot_date
    from ranked
    where rn = 1
),
duplicate_values as (
    select
        c.keep_id,
        max(r.liabilities_total) filter (where r.liabilities_total is not null) as liabilities_total,
        max(r.net_wealth_partial) filter (where r.net_wealth_partial is not null) as net_wealth_partial
    from canonical c
    join ranked r
        on r.portfolio_id = c.portfolio_id
       and r.snapshot_date = c.snapshot_date
       and r.rn > 1
    group by c.keep_id
)
update public.wealth_portfolio_snapshots w
set
    liabilities_total = coalesce(w.liabilities_total, d.liabilities_total),
    net_wealth_partial = coalesce(w.net_wealth_partial, d.net_wealth_partial)
from duplicate_values d
where w.id = d.keep_id;

-- D. Remove redundant same-day rows (no FK references to wealth_portfolio_snapshots.id).
with ranked as (
    select
        id,
        row_number() over (
            partition by portfolio_id, snapshot_date
            order by captured_at desc, created_at desc, id desc
        ) as rn
    from public.wealth_portfolio_snapshots
    where snapshot_date is not null
)
delete from public.wealth_portfolio_snapshots w
using ranked r
where w.id = r.id
  and r.rn > 1;

-- E. DB-level uniqueness (idempotent).
create unique index if not exists wealth_portfolio_snapshots_portfolio_date_uidx
    on public.wealth_portfolio_snapshots (portfolio_id, snapshot_date);

-- Upsert-on-conflict for same-day snapshots requires UPDATE under RLS (append-only insert-only before Wave 4).
drop policy if exists "wealth portfolio snapshots update own" on public.wealth_portfolio_snapshots;
create policy "wealth portfolio snapshots update own"
on public.wealth_portfolio_snapshots for update to authenticated
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

-- Optional wealth asset metadata (pricing/research capability hints).
alter table public.wealth_assets
    add column if not exists pricing_method text;

alter table public.wealth_assets
    add column if not exists research_capability text;

alter table public.wealth_assets
    add column if not exists participation_capability text;

alter table public.wealth_assets
    add column if not exists issuer text;

notify pgrst, 'reload schema';
