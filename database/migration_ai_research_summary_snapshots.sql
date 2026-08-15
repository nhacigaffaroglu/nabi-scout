-- AI Research Summary snapshots — symbol-level persisted summaries keyed by semantic identity.
-- Idempotent: safe to run multiple times in Supabase SQL Editor.
-- PRE-DEPLOY MIGRATION REQUIRED — do not apply automatically from application code.

create table if not exists public.ai_research_summary_snapshots (
    id uuid primary key default gen_random_uuid(),
    symbol text not null,
    semantic_identity text not null,
    source_context_version text not null,
    summary_version text not null,
    status text not null,
    evidence_level text not null,
    model_provider text,
    model_name text,
    generated_at timestamptz not null,
    summary_payload jsonb not null,
    display_version text,
    validation_version text,
    created_at timestamptz not null default now()
);

create index if not exists ai_research_summary_snapshots_symbol_generated_idx
    on public.ai_research_summary_snapshots (symbol, generated_at desc);

create unique index if not exists ai_research_summary_snapshots_symbol_identity_uidx
    on public.ai_research_summary_snapshots (symbol, semantic_identity);

alter table public.ai_research_summary_snapshots enable row level security;

drop policy if exists "authenticated ai research summary history access"
    on public.ai_research_summary_snapshots;
create policy "authenticated ai research summary history access"
on public.ai_research_summary_snapshots
for all
to authenticated
using (true)
with check (true);

notify pgrst, 'reload schema';
