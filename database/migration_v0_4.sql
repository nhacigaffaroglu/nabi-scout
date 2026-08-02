alter table public.investment_candidates
    add column if not exists market_cap numeric,
    add column if not exists revenue numeric,
    add column if not exists gross_margin numeric,
    add column if not exists net_margin numeric,
    add column if not exists free_cash_flow numeric,
    add column if not exists net_debt numeric,
    add column if not exists current_ratio numeric,
    add column if not exists debt_to_equity numeric,
    add column if not exists data_completeness numeric,
    add column if not exists data_source text,
    add column if not exists source_updated_at timestamptz,
    add column if not exists collector_notes text;

create table if not exists public.scan_runs (
    id uuid primary key default gen_random_uuid(),
    universe_name text not null,
    status text not null default 'RUNNING',
    total_symbols integer not null default 0,
    scanned_symbols integer not null default 0,
    inserted_or_updated integer not null default 0,
    strong_candidates integer not null default 0,
    error_count integer not null default 0,
    started_at timestamptz not null default now(),
    completed_at timestamptz
);

create table if not exists public.scan_results (
    id uuid primary key default gen_random_uuid(),
    scan_run_id uuid not null references public.scan_runs(id) on delete cascade,
    symbol text not null,
    status text,
    nabi_score numeric,
    decision text,
    data_completeness numeric,
    endpoint_status jsonb,
    errors jsonb,
    created_at timestamptz not null default now()
);

alter table public.scan_runs enable row level security;
alter table public.scan_results enable row level security;

grant select, insert, update, delete
on public.scan_runs, public.scan_results
to anon, authenticated;

drop policy if exists "temporary anon scan runs access" on public.scan_runs;
create policy "temporary anon scan runs access"
on public.scan_runs for all to anon using (true) with check (true);

drop policy if exists "temporary anon scan results access" on public.scan_results;
create policy "temporary anon scan results access"
on public.scan_results for all to anon using (true) with check (true);

drop policy if exists "authenticated scan runs access" on public.scan_runs;
create policy "authenticated scan runs access"
on public.scan_runs for all to authenticated using (true) with check (true);

drop policy if exists "authenticated scan results access" on public.scan_results;
create policy "authenticated scan results access"
on public.scan_results for all to authenticated using (true) with check (true);

notify pgrst, 'reload schema';
