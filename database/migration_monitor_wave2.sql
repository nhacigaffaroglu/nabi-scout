-- Wave 2 — Monitor events, user review state, run ledger, portfolio AI snapshots.
-- PRE-DEPLOY MIGRATION REQUIRED — do not apply automatically from application code.

create table if not exists public.monitor_events (
    id uuid primary key default gen_random_uuid(),
    user_id uuid references auth.users(id) on delete cascade,
    portfolio_id uuid references public.wealth_portfolios(id) on delete cascade,
    symbol text,
    event_type text not null,
    event_category text not null,
    severity text not null default 'info',
    materiality text not null default 'info',
    occurred_at timestamptz not null,
    detected_at timestamptz not null default now(),
    dedupe_key text not null,
    title text not null,
    summary text not null,
    evidence_type text,
    evidence_reference text,
    previous_value text,
    current_value text,
    absolute_change numeric,
    percentage_change numeric,
    event_payload jsonb not null default '{}'::jsonb,
    notification_eligible boolean not null default false,
    notification_reason text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint monitor_events_event_type_check check (
        char_length(event_type) > 0
    ),
    constraint monitor_events_materiality_check check (
        materiality in ('info', 'low', 'medium', 'high', 'critical')
    )
);

create unique index if not exists monitor_events_dedupe_key_uidx
    on public.monitor_events (dedupe_key);

create index if not exists monitor_events_user_detected_idx
    on public.monitor_events (user_id, detected_at desc)
    where user_id is not null;

create index if not exists monitor_events_symbol_detected_idx
    on public.monitor_events (symbol, detected_at desc)
    where symbol is not null;

create index if not exists monitor_events_category_detected_idx
    on public.monitor_events (event_category, detected_at desc);

alter table public.monitor_events enable row level security;

drop policy if exists "monitor events select" on public.monitor_events;
create policy "monitor events select"
on public.monitor_events for select to authenticated
using (user_id is null or auth.uid() = user_id);

drop policy if exists "monitor events insert own portfolio" on public.monitor_events;
create policy "monitor events insert own portfolio"
on public.monitor_events for insert to authenticated
with check (user_id is null or auth.uid() = user_id);

drop policy if exists "monitor events update own portfolio" on public.monitor_events;
create policy "monitor events update own portfolio"
on public.monitor_events for update to authenticated
using (user_id is null or auth.uid() = user_id)
with check (user_id is null or auth.uid() = user_id);

create table if not exists public.user_monitor_event_state (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    monitor_event_id uuid not null references public.monitor_events(id) on delete cascade,
    status text not null default 'new',
    portfolio_impact jsonb not null default '{}'::jsonb,
    reviewed_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint user_monitor_event_state_status_check check (
        status in ('new', 'reviewed', 'dismissed', 'resolved')
    ),
    constraint user_monitor_event_state_user_event_uidx unique (user_id, monitor_event_id)
);

create index if not exists user_monitor_event_state_user_status_idx
    on public.user_monitor_event_state (user_id, status, updated_at desc);

alter table public.user_monitor_event_state enable row level security;

drop policy if exists "user monitor event state own" on public.user_monitor_event_state;
create policy "user monitor event state own"
on public.user_monitor_event_state for all to authenticated
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

create table if not exists public.monitor_runs (
    id uuid primary key default gen_random_uuid(),
    run_id text not null,
    run_date date not null,
    trigger_type text not null,
    status text not null default 'RUNNING',
    events_created integer not null default 0,
    events_skipped integer not null default 0,
    report_payload jsonb not null default '{}'::jsonb,
    started_at timestamptz not null,
    finished_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create unique index if not exists monitor_runs_run_id_uidx
    on public.monitor_runs (run_id);

create index if not exists monitor_runs_run_date_idx
    on public.monitor_runs (run_date, started_at desc);

alter table public.monitor_runs enable row level security;

drop policy if exists "authenticated monitor runs access" on public.monitor_runs;
create policy "authenticated monitor runs access"
on public.monitor_runs for all to authenticated
using (true)
with check (true);

create table if not exists public.portfolio_ai_adviser_snapshots (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    portfolio_id uuid not null references public.wealth_portfolios(id) on delete cascade,
    semantic_identity text not null,
    context_version text not null,
    summary_version text not null,
    status text not null,
    evidence_level text not null,
    model_provider text,
    model_name text,
    generated_at timestamptz not null,
    response_payload jsonb not null,
    display_version text,
    validation_version text,
    created_at timestamptz not null default now(),
    constraint portfolio_ai_adviser_snapshots_user_portfolio_fkey
        foreign key (user_id, portfolio_id)
        references public.wealth_portfolios (user_id, id)
        on delete cascade
);

create unique index if not exists portfolio_ai_adviser_snapshots_identity_uidx
    on public.portfolio_ai_adviser_snapshots (user_id, portfolio_id, semantic_identity);

create index if not exists portfolio_ai_adviser_snapshots_user_generated_idx
    on public.portfolio_ai_adviser_snapshots (user_id, portfolio_id, generated_at desc);

alter table public.portfolio_ai_adviser_snapshots enable row level security;

drop policy if exists "portfolio ai adviser snapshots own" on public.portfolio_ai_adviser_snapshots;
create policy "portfolio ai adviser snapshots own"
on public.portfolio_ai_adviser_snapshots for all to authenticated
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

notify pgrst, 'reload schema';
