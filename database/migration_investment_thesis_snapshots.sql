-- Investment Thesis snapshots — symbol-level shared research history.
-- Idempotent: safe to run multiple times in Supabase SQL Editor.

create table if not exists public.investment_thesis_snapshots (
    id uuid primary key default gen_random_uuid(),
    symbol text not null,
    captured_at timestamptz not null default now(),
    thesis_version text not null,
    thesis_status text not null,
    semantic_identity text not null,
    thesis_payload jsonb not null,
    source_version text,
    created_at timestamptz not null default now()
);

create index if not exists investment_thesis_snapshots_symbol_captured_idx
    on public.investment_thesis_snapshots (symbol, captured_at desc);

create index if not exists investment_thesis_snapshots_semantic_identity_idx
    on public.investment_thesis_snapshots (symbol, semantic_identity);

alter table public.investment_thesis_snapshots enable row level security;

drop policy if exists "authenticated investment thesis history access"
    on public.investment_thesis_snapshots;
create policy "authenticated investment thesis history access"
on public.investment_thesis_snapshots
for all
to authenticated
using (true)
with check (true);

notify pgrst, 'reload schema';
