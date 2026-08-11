-- Research workflow columns and legacy research_status cleanup.
-- Idempotent: safe to run multiple times in Supabase SQL Editor.

ALTER TABLE public.investment_candidates
    ADD COLUMN IF NOT EXISTS research_next_action text,
    ADD COLUMN IF NOT EXISTS research_note text,
    ADD COLUMN IF NOT EXISTS last_reviewed_at timestamptz;

-- Legacy manual workflow values
UPDATE public.investment_candidates
SET research_status = 'YENI'
WHERE research_status = 'Araştırılacak';

UPDATE public.investment_candidates
SET research_status = 'INCELEMEDE'
WHERE research_status = 'İnceleniyor';

UPDATE public.investment_candidates
SET research_status = 'TAMAMLANDI'
WHERE research_status IN ('Tamamlandı', 'Arşiv');

-- Legacy scanner pollution
UPDATE public.investment_candidates
SET research_status = 'YENI'
WHERE research_status = 'Otomatik tarandı';

UPDATE public.investment_candidates
SET research_status = 'YENI'
WHERE research_status LIKE 'Scanner v% tarandı';

-- Noncanonical values are left unchanged; app-layer normalize_research_status handles them.

ALTER TABLE public.investment_candidates
    ALTER COLUMN research_status SET DEFAULT 'YENI';

notify pgrst, 'reload schema';
