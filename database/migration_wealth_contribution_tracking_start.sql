-- Contribution tracking start — portfolio metadata, not accounting.
-- Marks the first date from which external deposit/withdraw history is
-- authoritative for contribution-plan reporting. Does not create cash-flow rows.
-- Does not infer deposits from BUY / cost basis / snapshots.
-- Idempotent: safe to run multiple times in Supabase SQL Editor.
-- PRE-DEPLOY MIGRATION REQUIRED — do not apply automatically from application code.

alter table public.wealth_portfolios
    add column if not exists contribution_tracking_start_date date;

notify pgrst, 'reload schema';
