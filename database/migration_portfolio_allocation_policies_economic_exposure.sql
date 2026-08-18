-- Extend portfolio_allocation_policies.dimension CHECK to allow ECONOMIC_EXPOSURE.
-- Additive only: drop/recreate the existing CHECK. Preserves rows. No new table/columns.
-- Idempotent: safe to run multiple times in Supabase SQL Editor.
-- PRE-DEPLOY MIGRATION REQUIRED — do not apply automatically from application code.

alter table public.portfolio_allocation_policies
    drop constraint if exists portfolio_allocation_policies_dimension_check;

alter table public.portfolio_allocation_policies
    add constraint portfolio_allocation_policies_dimension_check
        check (dimension in ('ASSET_CLASS', 'MARKET', 'ECONOMIC_EXPOSURE'));

notify pgrst, 'reload schema';
