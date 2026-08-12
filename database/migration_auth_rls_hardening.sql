-- Phase 7 — Remove temporary anon RLS policies from active research tables.
-- Idempotent: safe to run multiple times in Supabase SQL Editor.
-- Does not alter table schemas or delete data.
--
-- After this migration:
-- - Streamlit users must sign in (authenticated JWT) for app data access.
-- - Headless jobs (GitHub Actions daily scan) must use the Supabase service_role
--   key in SUPABASE_KEY; publishable/anon keys no longer bypass RLS.

-- investment_candidates
drop policy if exists "temporary anon candidates access" on public.investment_candidates;
drop policy if exists "authenticated candidates access" on public.investment_candidates;
create policy "authenticated candidates access"
on public.investment_candidates
for all
to authenticated
using (true)
with check (true);

-- deep_analyses
drop policy if exists "temporary anon analyses access" on public.deep_analyses;
drop policy if exists "authenticated analyses access" on public.deep_analyses;
create policy "authenticated analyses access"
on public.deep_analyses
for all
to authenticated
using (true)
with check (true);

-- news_items
drop policy if exists "temporary anon news access" on public.news_items;
drop policy if exists "authenticated news access" on public.news_items;
create policy "authenticated news access"
on public.news_items
for all
to authenticated
using (true)
with check (true);

-- watchlist
drop policy if exists "temporary anon watchlist access" on public.watchlist;
drop policy if exists "authenticated watchlist access" on public.watchlist;
create policy "authenticated watchlist access"
on public.watchlist
for all
to authenticated
using (true)
with check (true);

-- scan_runs
drop policy if exists "temporary anon scan runs access" on public.scan_runs;
drop policy if exists "authenticated scan runs access" on public.scan_runs;
create policy "authenticated scan runs access"
on public.scan_runs
for all
to authenticated
using (true)
with check (true);

-- scan_results
drop policy if exists "temporary anon scan results access" on public.scan_results;
drop policy if exists "authenticated scan results access" on public.scan_results;
create policy "authenticated scan results access"
on public.scan_results
for all
to authenticated
using (true)
with check (true);

-- universe_runs
drop policy if exists "temporary anon universe runs access" on public.universe_runs;
drop policy if exists "authenticated universe runs access" on public.universe_runs;
create policy "authenticated universe runs access"
on public.universe_runs
for all
to authenticated
using (true)
with check (true);

-- universe_symbols
drop policy if exists "temporary anon universe symbols access" on public.universe_symbols;
drop policy if exists "authenticated universe symbols access" on public.universe_symbols;
create policy "authenticated universe symbols access"
on public.universe_symbols
for all
to authenticated
using (true)
with check (true);

-- tracked_funds
drop policy if exists "temporary anon tracked funds access" on public.tracked_funds;
drop policy if exists "authenticated tracked funds access" on public.tracked_funds;
create policy "authenticated tracked funds access"
on public.tracked_funds
for all
to authenticated
using (true)
with check (true);

-- participation_assessment_snapshots
drop policy if exists "temporary anon participation assessment history access"
    on public.participation_assessment_snapshots;
drop policy if exists "authenticated participation assessment history access"
    on public.participation_assessment_snapshots;
create policy "authenticated participation assessment history access"
on public.participation_assessment_snapshots
for all
to authenticated
using (true)
with check (true);

notify pgrst, 'reload schema';
