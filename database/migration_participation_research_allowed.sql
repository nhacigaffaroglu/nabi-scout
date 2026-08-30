-- Additive: persist canonical research_allowed on Participation snapshots.
-- Nullable. Does not backfill historical rows. Null stays fail-closed.

alter table public.participation_assessment_snapshots
    add column if not exists research_allowed boolean;

notify pgrst, 'reload schema';
