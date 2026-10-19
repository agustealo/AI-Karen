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

-- Mixed runtime/tool/feedback/ML workloads share one ledger but must not
-- starve the learning evidence window for any individual source.
CREATE INDEX IF NOT EXISTS idx_outcome_records_tenant_user_source_recorded
    ON public.outcome_records (
        tenant_id, user_id, source, recorded_at DESC
    ) WHERE user_id IS NOT NULL;

COMMENT ON COLUMN public.outcome_records.source IS
    'Runtime execution, user feedback, or governed ML predictor evaluation. Each remains distinguishable; no source grants authority.';

COMMIT;
