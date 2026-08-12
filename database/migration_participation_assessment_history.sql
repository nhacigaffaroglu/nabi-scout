-- Phase 6B.4 — Append-only equity participation assessment history.
-- Idempotent: safe to run multiple times in Supabase SQL Editor.

create table if not exists public.participation_assessment_snapshots (
    id uuid primary key default gen_random_uuid(),
    symbol text not null,
    assessed_at timestamptz not null default now(),
    methodology_id text,
    methodology_version text,
    status text not null,
    source text,
    confidence text,
    methodology_completeness text,
    data_completeness_pct numeric,
    holdings_coverage_pct numeric,
    freshness_label text,
    financial_overall_outcome text,
    business_overall_outcome text,
    provider_status jsonb not null default '{}'::jsonb,
    sec_available boolean not null default false,
    warnings jsonb not null default '[]'::jsonb,
    errors jsonb not null default '[]'::jsonb,
    missing_capabilities jsonb not null default '[]'::jsonb,
    source_evidence jsonb not null default '{}'::jsonb,
    assessment_payload jsonb not null,
    semantic_identity text not null,
    created_at timestamptz not null default now()
);

create index if not exists participation_assessment_snapshots_symbol_assessed_idx
    on public.participation_assessment_snapshots (symbol, assessed_at desc);

create index if not exists participation_assessment_snapshots_semantic_identity_idx
    on public.participation_assessment_snapshots (symbol, semantic_identity);

alter table public.participation_assessment_snapshots enable row level security;

drop policy if exists "authenticated participation assessment history access"
    on public.participation_assessment_snapshots;
create policy "authenticated participation assessment history access"
on public.participation_assessment_snapshots
for all
to authenticated
using (true)
with check (true);

drop policy if exists "temporary anon participation assessment history access"
    on public.participation_assessment_snapshots;
create policy "temporary anon participation assessment history access"
on public.participation_assessment_snapshots
for all
to anon
using (true)
with check (true);

notify pgrst, 'reload schema';
