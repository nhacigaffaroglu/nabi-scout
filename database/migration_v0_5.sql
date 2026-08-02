create table if not exists public.universe_runs (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    status text not null default 'RUNNING',
    source text,
    filters jsonb,
    total_symbols integer not null default 0,
    errors jsonb,
    started_at timestamptz not null default now(),
    completed_at timestamptz
);

create table if not exists public.universe_symbols (
    id uuid primary key default gen_random_uuid(),
    universe_run_id uuid references public.universe_runs(id)
        on delete set null,
    universe_name text not null,
    symbol text not null,
    company_name text,
    exchange text,
    country text,
    sector text,
    industry text,
    market_cap numeric,
    price numeric,
    volume numeric,
    beta numeric,
    is_etf boolean not null default false,
    is_actively_trading boolean not null default true,
    universe_source text,
    rank integer,
    is_selected boolean not null default true,
    discovered_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique(universe_name, symbol)
);

alter table public.universe_runs enable row level security;
alter table public.universe_symbols enable row level security;

grant select, insert, update, delete
on public.universe_runs, public.universe_symbols
to anon, authenticated;

drop policy if exists "temporary anon universe runs access"
on public.universe_runs;
create policy "temporary anon universe runs access"
on public.universe_runs
for all to anon
using (true) with check (true);

drop policy if exists "temporary anon universe symbols access"
on public.universe_symbols;
create policy "temporary anon universe symbols access"
on public.universe_symbols
for all to anon
using (true) with check (true);

drop policy if exists "authenticated universe runs access"
on public.universe_runs;
create policy "authenticated universe runs access"
on public.universe_runs
for all to authenticated
using (true) with check (true);

drop policy if exists "authenticated universe symbols access"
on public.universe_symbols;
create policy "authenticated universe symbols access"
on public.universe_symbols
for all to authenticated
using (true) with check (true);

create index if not exists idx_universe_symbols_name_rank
on public.universe_symbols(universe_name, rank);

create index if not exists idx_universe_symbols_market_cap
on public.universe_symbols(market_cap desc);

notify pgrst, 'reload schema';
