-- Security Intelligence snapshots — symbol-level scored history.
-- Idempotent: safe to run multiple times in Supabase SQL Editor.
-- PRE-DEPLOY MIGRATION REQUIRED — do not apply automatically from application code.
-- UPSERT identity: (symbol, as_of_key, facts_version, engine_version)

create table if not exists public.security_intelligence_snapshots (
    id uuid primary key default gen_random_uuid(),
    symbol text not null,
    as_of timestamptz,
    as_of_key text not null,
    facts_version text not null,
    engine_version text not null,
    overall_score numeric,
    overall_status text not null,
    overall_confidence numeric,
    investment_state text not null,
    participation_status text,
    research_allowed boolean,
    dimension_scores jsonb not null default '{}'::jsonb,
    dimension_statuses jsonb not null default '{}'::jsonb,
    data_quality jsonb not null default '{}'::jsonb,
    strengths jsonb not null default '[]'::jsonb,
    weaknesses jsonb not null default '[]'::jsonb,
    risk_flags jsonb not null default '[]'::jsonb,
    reason_codes jsonb not null default '[]'::jsonb,
    change_flags jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint security_intelligence_snapshots_identity_uidx
        unique (symbol, as_of_key, facts_version, engine_version)
);

create index if not exists security_intelligence_snapshots_symbol_as_of_idx
    on public.security_intelligence_snapshots (symbol, as_of desc);

alter table public.security_intelligence_snapshots enable row level security;

drop policy if exists "authenticated security intelligence snapshot access"
    on public.security_intelligence_snapshots;
create policy "authenticated security intelligence snapshot access"
on public.security_intelligence_snapshots
for all
to authenticated
using (true)
with check (true);

notify pgrst, 'reload schema';
