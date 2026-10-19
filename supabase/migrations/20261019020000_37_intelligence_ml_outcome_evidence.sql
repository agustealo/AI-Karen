-- KAREN-LEARNING-ML-EVIDENCE-1
-- The existing append-only, tenant-RLS OutcomeStore gains a *separate*
-- evaluated-predictor evidence source. It is not a second learning database.
-- Evaluation labels are admitted only by governed Intelligence adapters.
BEGIN;

ALTER TABLE public.outcome_records
    DROP CONSTRAINT IF EXISTS outcome_records_source_check;

ALTER TABLE public.outcome_records
    ADD CONSTRAINT outcome_records_source_check
    CHECK (source IN (
        'runtime.execution', 'user.feedback', 'intelligence.ml'
    ));

COMMENT ON COLUMN public.outcome_records.source IS
    'Runtime execution, user feedback, or governed ML predictor evaluation. Each remains distinguishable; no source grants authority.';

COMMIT;
