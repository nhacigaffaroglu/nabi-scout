-- Signal Intelligence events + evidence.
-- Idempotent: safe to run multiple times in Supabase SQL Editor.
-- PRE-DEPLOY MIGRATION REQUIRED — do not apply automatically from application code.
-- Production persist is disabled until this file is applied explicitly.
--
-- Event identity (application-computed event_id; never headline-only):
--   1. authoritative_event_id (SEC accession / KAP id / issuer-exchange-regulator id)
--   2. composite authoritative_event_id + logical_event_key when one source
--      document exposes multiple logical events
--   3. fingerprint fallback: symbol + event_type + date + factual_subject
-- Evidence identity is unique evidence_id. Secondary sources cite
-- authoritative_event_id and add evidence rows only.

create table if not exists public.signal_events (
    id uuid primary key default gen_random_uuid(),
    event_id text not null,
    symbol text not null,
    security_id text,
    event_type text not null,
    event_subtype text,
    headline text,
    description text,
    event_time timestamptz,
    effective_time timestamptz,
    source_authority text not null,
    verification_status text not null,
    materiality text not null,
    direction text not null,
    strength text not null,
    reason_codes jsonb not null default '[]'::jsonb,
    evidence_ids jsonb not null default '[]'::jsonb,
    factual_subject text,
    raw_reference text,
    authoritative_event_id text,
    logical_event_key text,
    as_of timestamptz,
    contract_version text not null,
    engine_version text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint signal_events_event_id_uidx unique (event_id)
);

create index if not exists signal_events_symbol_time_idx
    on public.signal_events (symbol, event_time desc);

create index if not exists signal_events_authoritative_idx
    on public.signal_events (symbol, authoritative_event_id);

create table if not exists public.signal_evidence (
    id uuid primary key default gen_random_uuid(),
    evidence_id text not null,
    event_id text not null,
    symbol text not null,
    source_id text not null,
    source_type text not null,
    source_authority text not null,
    source_url text,
    external_id text,
    retrieved_at timestamptz,
    as_of timestamptz,
    verification_status text not null,
    raw_reference text,
    headline text,
    reason_codes jsonb not null default '[]'::jsonb,
    contract_version text not null,
    engine_version text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint signal_evidence_evidence_id_uidx unique (evidence_id)
);

create index if not exists signal_evidence_event_idx
    on public.signal_evidence (event_id);

create index if not exists signal_evidence_external_idx
    on public.signal_evidence (source_type, external_id);

alter table public.signal_events enable row level security;
alter table public.signal_evidence enable row level security;

drop policy if exists "authenticated signal event access"
    on public.signal_events;
create policy "authenticated signal event access"
on public.signal_events
for all
to authenticated
using (true)
with check (true);

drop policy if exists "authenticated signal evidence access"
    on public.signal_evidence;
create policy "authenticated signal evidence access"
on public.signal_evidence
for all
to authenticated
using (true)
with check (true);

notify pgrst, 'reload schema';
