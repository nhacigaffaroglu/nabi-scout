-- Universe expansion run ledger — daily scheduler idempotency and audit trail.
-- Idempotent: safe to run multiple times in Supabase SQL Editor.
-- PRE-DEPLOY MIGRATION REQUIRED — do not apply automatically from application code.

create table if not exists public.universe_expansion_runs (
    id uuid primary key default gen_random_uuid(),
    run_id text not null,
    run_date date not null,
    trigger_type text not null,
    dry_run boolean not null default false,
    allow_second_run_today boolean not null default false,
    status text not null default 'RUNNING',
    stop_reason text,
    symbols_considered integer not null default 0,
    symbols_started integer not null default 0,
    symbols_completed integer not null default 0,
    symbols_retryable integer not null default 0,
    symbols_blocked integer not null default 0,
    symbols_skipped integer not null default 0,
    fmp_calls_used integer not null default 0,
    sec_calls_used integer not null default 0,
    report_payload jsonb not null default '{}'::jsonb,
    started_at timestamptz not null,
    finished_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create unique index if not exists universe_expansion_runs_run_id_uidx
    on public.universe_expansion_runs (run_id);

create index if not exists universe_expansion_runs_run_date_started_idx
    on public.universe_expansion_runs (run_date, started_at desc);

alter table public.universe_expansion_runs enable row level security;

drop policy if exists "authenticated universe expansion runs access"
    on public.universe_expansion_runs;
create policy "authenticated universe expansion runs access"
on public.universe_expansion_runs
for all
to authenticated
using (true)
with check (true);

notify pgrst, 'reload schema';
