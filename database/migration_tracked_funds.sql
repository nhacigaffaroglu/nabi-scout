-- Phase 5D.1 — Persistent fund tracking (separate from investment_candidates).
-- Idempotent: safe to run multiple times in Supabase SQL Editor.

create table if not exists public.tracked_funds (
    id uuid primary key default gen_random_uuid(),
    symbol text not null,
    fund_name text,
    exchange text,
    asset_class text,
    participation_status text,
    participation_score integer check (participation_score between 0 and 100),
    participation_source text,
    data_provider text,
    resolution_source text,
    last_reviewed_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique(symbol)
);

create index if not exists tracked_funds_symbol_idx
    on public.tracked_funds (symbol);

alter table public.tracked_funds enable row level security;

drop policy if exists "authenticated tracked funds access" on public.tracked_funds;
create policy "authenticated tracked funds access"
on public.tracked_funds
for all
to authenticated
using (true)
with check (true);

drop policy if exists "temporary anon tracked funds access" on public.tracked_funds;
create policy "temporary anon tracked funds access"
on public.tracked_funds
for all
to anon
using (true)
with check (true);

notify pgrst, 'reload schema';
