-- Universe expansion queue — daily participation onboarding progress.
-- Idempotent: safe to run multiple times in Supabase SQL Editor.
-- After this migration:
-- - Streamlit users must sign in (authenticated JWT) for queue access.
-- - Headless/admin scripts must use SUPABASE_SERVICE_ROLE_KEY or dev_auth sign-in;
--   publishable/anon keys cannot write to this table.
--
-- PRE-DEPLOY MIGRATION REQUIRED — do not apply automatically from application code.

create table if not exists public.universe_expansion_queue (
    id uuid primary key default gen_random_uuid(),
    symbol text not null,
    source_universe text not null,
    priority integer not null default 100,
    status text not null default 'PENDING',
    attempt_count integer not null default 0,
    provider_calls_used jsonb not null default '{}'::jsonb,
    last_attempt_at timestamptz,
    next_retry_at timestamptz,
    completed_at timestamptz,
    last_error_category text,
    participation_status text,
    research_allowed boolean,
    claimed_at timestamptz,
    claim_run_id text,
    semantic_version text not null default 'universe-expansion-v1',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create unique index if not exists universe_expansion_queue_symbol_uidx
    on public.universe_expansion_queue (symbol);

create index if not exists universe_expansion_queue_status_priority_idx
    on public.universe_expansion_queue (status, priority, symbol);

create index if not exists universe_expansion_queue_next_retry_idx
    on public.universe_expansion_queue (next_retry_at)
    where status = 'RETRYABLE';

alter table public.universe_expansion_queue enable row level security;

drop policy if exists "authenticated universe expansion queue access"
    on public.universe_expansion_queue;
create policy "authenticated universe expansion queue access"
on public.universe_expansion_queue
for all
to authenticated
using (true)
with check (true);

notify pgrst, 'reload schema';
