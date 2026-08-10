ALTER TABLE scan_results
ADD COLUMN IF NOT EXISTS candidate_snapshot jsonb;

CREATE INDEX IF NOT EXISTS idx_scan_results_symbol_created
ON scan_results(symbol, created_at DESC);

notify pgrst, 'reload schema';
