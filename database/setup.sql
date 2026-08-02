-- NABI Scout v0.1 — Supabase database setup
-- Supabase SQL Editor içine tamamını yapıştırıp Run düğmesine basın.

create extension if not exists pgcrypto;

create table if not exists public.investment_candidates (
    id uuid primary key default gen_random_uuid(),
    symbol text not null,
    asset_type text not null,
    market text not null,
    currency text,
    participation_status text not null default 'Kontrol Et',
    sector_theme text,
    current_price numeric,
    return_12m numeric,
    return_3y_annualized numeric,
    quality_score numeric check (quality_score between 0 and 100),
    growth_score numeric check (growth_score between 0 and 100),
    valuation_score numeric check (valuation_score between 0 and 100),
    news_catalyst_score numeric check (news_catalyst_score between 0 and 100),
    portfolio_fit_score numeric check (portfolio_fit_score between 0 and 100),
    risk_score numeric check (risk_score between 0 and 100),
    liquidity_score numeric check (liquidity_score between 0 and 100),
    participation_score numeric check (participation_score between 0 and 100),
    nabi_score numeric check (nabi_score between 0 and 100),
    decision text,
    main_reason text,
    critical_risk text,
    research_status text not null default 'Araştırılacak',
    source_url text,
    notes text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique(symbol, market)
);

create table if not exists public.deep_analyses (
    id uuid primary key default gen_random_uuid(),
    candidate_id uuid not null references public.investment_candidates(id) on delete cascade,
    revenue_growth numeric,
    eps_growth numeric,
    operating_margin numeric,
    roic numeric,
    net_debt_ebitda numeric,
    valuation_summary text,
    investment_plans text,
    competitive_advantage text,
    management_notes text,
    analyst_note text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.news_items (
    id uuid primary key default gen_random_uuid(),
    candidate_id uuid not null references public.investment_candidates(id) on delete cascade,
    published_at timestamptz not null default now(),
    title text not null,
    news_type text,
    impact text,
    importance text,
    summary text,
    catalyst_risk text,
    source_url text,
    verified boolean not null default false,
    created_at timestamptz not null default now()
);

create table if not exists public.watchlist (
    id uuid primary key default gen_random_uuid(),
    candidate_id uuid not null references public.investment_candidates(id) on delete cascade,
    target_role text,
    buy_threshold numeric,
    target_price numeric,
    risk_threshold numeric,
    catalyst text,
    status text not null default 'İzle',
    notes text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique(candidate_id)
);

-- RLS
alter table public.investment_candidates enable row level security;
alter table public.deep_analyses enable row level security;
alter table public.news_items enable row level security;
alter table public.watchlist enable row level security;

-- İlk kurulum için yalnızca authenticated kullanıcılara tam erişim.
-- Streamlit giriş sistemi sonraki sürümde eklenecek.
drop policy if exists "authenticated candidates access" on public.investment_candidates;
create policy "authenticated candidates access"
on public.investment_candidates
for all
to authenticated
using (true)
with check (true);

drop policy if exists "authenticated analyses access" on public.deep_analyses;
create policy "authenticated analyses access"
on public.deep_analyses
for all
to authenticated
using (true)
with check (true);

drop policy if exists "authenticated news access" on public.news_items;
create policy "authenticated news access"
on public.news_items
for all
to authenticated
using (true)
with check (true);

drop policy if exists "authenticated watchlist access" on public.watchlist;
create policy "authenticated watchlist access"
on public.watchlist
for all
to authenticated
using (true)
with check (true);

-- Geçici geliştirme politikaları:
-- Streamlit Auth eklenene kadar publishable key ile test yapabilmek için anon erişimi.
-- Uygulamayı herkese açmadan önce bu dört policy kaldırılacaktır.
drop policy if exists "temporary anon candidates access" on public.investment_candidates;
create policy "temporary anon candidates access"
on public.investment_candidates
for all
to anon
using (true)
with check (true);

drop policy if exists "temporary anon analyses access" on public.deep_analyses;
create policy "temporary anon analyses access"
on public.deep_analyses
for all
to anon
using (true)
with check (true);

drop policy if exists "temporary anon news access" on public.news_items;
create policy "temporary anon news access"
on public.news_items
for all
to anon
using (true)
with check (true);

drop policy if exists "temporary anon watchlist access" on public.watchlist;
create policy "temporary anon watchlist access"
on public.watchlist
for all
to anon
using (true)
with check (true);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists investment_candidates_updated_at on public.investment_candidates;
create trigger investment_candidates_updated_at
before update on public.investment_candidates
for each row execute function public.set_updated_at();

drop trigger if exists deep_analyses_updated_at on public.deep_analyses;
create trigger deep_analyses_updated_at
before update on public.deep_analyses
for each row execute function public.set_updated_at();

drop trigger if exists watchlist_updated_at on public.watchlist;
create trigger watchlist_updated_at
before update on public.watchlist
for each row execute function public.set_updated_at();
